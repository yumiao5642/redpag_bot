import asyncio, time, random, re
from decimal import Decimal
from dataclasses import dataclass
from typing import List, Optional, Union, Dict
import requests
from tronpy import Tron
from tronpy.keys import PrivateKey
from tronpy.providers import HTTPProvider
from ..config import (
    USDT_CONTRACT, TRON_FULLNODE_URL, USDT_DECIMALS,
    TRONGRID_API_KEY, TRONGRID_QPS
)
from ..logger import collect_logger
from tronpy.exceptions import TransactionNotFound

# 允许配置多个 Key，轮询
def _parse_keys(raw: str) -> Optional[Union[str, List[str]]]:
    if not raw:
        return None
    ks = [k.strip() for k in raw.split(",") if k.strip()]
    if not ks:
        return None
    return ks if len(ks) > 1 else ks[0]

def _get_client() -> Tron:
    """创建 Tron 客户端；带 TronGrid API Key（支持多个 Key 轮换）"""
    api_keys = _parse_keys(TRONGRID_API_KEY)
    provider = HTTPProvider(
        endpoint_uri=TRON_FULLNODE_URL or "https://api.trongrid.io",
        api_key=api_keys,
        timeout=20.0,
    )
    return Tron(provider)

@dataclass
class TronAddress:
    address: str
    private_key_hex: str  # 64 hex

def short_addr(addr: str) -> str:
    if not addr or len(addr) <= 12:
        return addr or ""
    return addr[:6] + "..." + addr[-6:]

# ========== 基础工具：全局异步限速 ==========
class AsyncRateLimiter:
    """简单的最小间隔限速器，按 QPS 计算调用间隔"""
    def __init__(self, qps: float):
        self.interval = 1.0 / max(qps, 0.1)
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            wait_for = self.interval - (now - self._last)
            if wait_for > 0:
                await asyncio.sleep(wait_for)
            self._last = time.monotonic()

_limiter = AsyncRateLimiter(TRONGRID_QPS)

async def _retry_with_backoff(coro_func, *args, **kwargs):
    """
    指数退避重试：处理 401/403/429 或 requests.HTTPError
    回退：1s / 2s / 4s / 8s（叠加轻微抖动）
    """
    for attempt in range(4):
        try:
            return await coro_func(*args, **kwargs)
        except Exception as e:
            code = getattr(getattr(e, "response", None), "status_code", None)
            if code in (401, 403, 429) or isinstance(e, requests.HTTPError):
                delay = (2 ** attempt) + random.uniform(0, 0.5)
                collect_logger.warning(
                    f"[TronGrid] 受限/未授权，重试 {attempt+1}/4，{delay:.2f}s 后重试；err={e}"
                )
                await asyncio.sleep(delay)
                continue
            raise

# ========== 账户/资源 ==========
def get_trx_balance(address: str) -> float:
    c = _get_client()
    acc = c.get_account(address)  # dict；balance 为 Sun
    bal_sun = int(acc.get("balance", 0))
    return bal_sun / 1_000_000.0

def get_account_resource(address: str) -> dict:
    """
    返回 {'bandwidth': int, 'energy': int}
    带宽 = (freeNetLimit - freeNetUsed) + (NetLimit - NetUsed)
    能量 = (EnergyLimit - EnergyUsed)
    """
    c = _get_client()
    info = c.get_account_resource(address)
    bw = max(0, int(info.get('freeNetLimit', 0)) - int(info.get('freeNetUsed', 0))) \
         + max(0, int(info.get('NetLimit', 0)) - int(info.get('NetUsed', 0)))
    en = max(0, int(info.get('EnergyLimit', 0)) - int(info.get('EnergyUsed', 0)))
    return {'bandwidth': bw, 'energy': en}

# ========== TRX 转账 ==========
def wait_tx_committed(txid: str, timeout: int = 45, interval: float = 1.5) -> dict:
    c = _get_client()
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            info = c.get_transaction_info(txid)
            if info and (info.get("result") == "SUCCESS" or info.get("blockNumber") is not None):
                return info
            if info and info.get("result") == "FAILED":
                return info
        except TransactionNotFound as e:
            last_err = e
        time.sleep(interval)
    if last_err:
        raise last_err
    return {}

def send_trx(priv_hex: str, from_addr: str, to_addr: str, amount_trx: float) -> str:
    c = _get_client()
    amt_sun = int(Decimal(str(amount_trx)) * Decimal(1_000_000))
    tx = c.trx.transfer(from_addr, to_addr, amt_sun).build().sign(PrivateKey(bytes.fromhex(priv_hex))).broadcast()
    txid = tx.txid
    info = wait_tx_committed(txid, timeout=45)
    if info and info.get("result") != "FAILED" and info.get("blockNumber") is not None:
        return txid
    raise RuntimeError(f"TRX topup not confirmed: {info or 'no-info'} txid={txid}")

# ========== 地址/合约 ==========
def generate_address() -> TronAddress:
    pk = PrivateKey.random()
    return TronAddress(
        address=pk.public_key.to_base58check_address(),
        private_key_hex=pk.hex(),
    )

async def get_usdt_balance(address: str) -> float:
    async def _call():
        await _limiter.wait()

        def _task():
            c = _get_client()
            usdt = c.get_contract(USDT_CONTRACT)
            raw = usdt.functions.balanceOf(address)
            return float(Decimal(raw) / (Decimal(10) ** USDT_DECIMALS))

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _task)

    return await _retry_with_backoff(_call)

async def usdt_transfer_all(priv_hex: str, from_addr: str, to_addr: str, amount: float) -> str:
    """
    将 amount USDT 从 from_addr 转到 to_addr，等待确认，返回 txid。
    回执非 SUCCESS（如 OUT_OF_ENERGY / REVERT），抛异常让上层重试。
    """
    async def _call():
        await _limiter.wait()

        def _task():
            c = _get_client()
            usdt = c.get_contract(USDT_CONTRACT)
            amt = int(Decimal(str(amount)) * (Decimal(10) ** USDT_DECIMALS))
            tx = (
                usdt.functions.transfer(to_addr, amt)
                .with_owner(from_addr)
                .fee_limit(30_000_000)
                .build()
                .sign(PrivateKey(bytes.fromhex(priv_hex)))
                .broadcast()
            )
            receipt = tx.wait()
            result = (receipt.get('receipt') or {}).get('result') or receipt.get('contractRet') or ''
            result = str(result).upper()
            if result != 'SUCCESS':
                raise RuntimeError(f"transfer receipt not SUCCESS: {result}  txid={tx.txid}")

            collect_logger.info(f"✅ USDT 转账确认成功：txid={tx.txid} result={result}")
            return tx.txid

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _task)

    return await _retry_with_backoff(_call)

# ========== 地址校验 ==========
_BASE58_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")

def is_valid_address(address: str) -> bool:
    """
    仅做快速格式校验：
    - 以 'T' 开头
    - 长度 34
    - 仅 Base58 字符（排除 0 O I l）
    """
    if not isinstance(address, str):
        return False
    if not _BASE58_RE.match(address):
        return False
    return True

# ========== TronGrid 最近转账 ==========
async def get_recent_transfers(address: str, limit: int = 10) -> List[Dict]:
    """
    读取地址最近 TRC20 转账（基于 TronGrid v1）。
    返回字段：hash/from/to/amount/asset
    """
    def _fetch():
        headers = {}
        if TRONGRID_API_KEY:
            # 兼容多个 key，随便取第一个
            k = TRONGRID_API_KEY.split(",")[0].strip()
            if k:
                headers["TRON-PRO-API-KEY"] = k
        url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20"
        r = requests.get(url, params={"limit": limit}, headers=headers, timeout=15)
        r.raise_for_status()
        js = r.json()
        out = []
        for it in js.get("data", []):
            v = it.get("token_info", {}) or {}
            decimals = int(v.get("decimals", 6))
            sym = v.get("symbol", "USDT")
            # 部分返回结构在 data 顶层也有 from/to/value
            _from = it.get("from") or it.get("value", {}).get("from", "")
            _to = it.get("to") or it.get("value", {}).get("to", "")
            raw_val = it.get("value") if isinstance(it.get("value"), str) else it.get("value", {}).get("value", 0)
            try:
                amount = float(raw_val) / (10 ** decimals)
            except Exception:
                amount = 0.0
            out.append({
                "hash": it.get("transaction_id", ""),
                "from": _from,
                "to": _to,
                "amount": amount,
                "asset": sym,
            })
        return out

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _fetch)

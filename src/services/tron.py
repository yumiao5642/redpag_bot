import asyncio, time, random, re
from decimal import Decimal
from dataclasses import dataclass
from typing import List, Optional, Union
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
from typing import List, Dict
import os, requests

TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "").split(",")[0].strip()


def get_trx_balance(address: str) -> float:
    """
    读取地址TRX余额（单位：TRX）
    """
    c = _get_client()
    acc = c.get_account(address)  # dict；balance 为 Sun
    bal_sun = int(acc.get("balance", 0))
    return bal_sun / 1_000_000.0

def wait_tx_committed(txid: str, timeout: int = 45, interval: float = 1.5) -> dict:
    """
    轮询查询交易信息，直到返回结果或超时。
    返回 info 字典；若 info.get('result') == 'FAILED' 则视为失败。
    """
    c = _get_client()
    deadline = time.time() + timeout
    last_err = None
    while time.time() < deadline:
        try:
            info = c.get_transaction_info(txid)
            # TRX 普通转账可能没有 contractRet；出现 'result': 'SUCCESS' 或包含 blockNumber 即可视为成功
            if info and (info.get("result") == "SUCCESS" or info.get("blockNumber") is not None):
                return info
            # 有明确失败
            if info and info.get("result") == "FAILED":
                return info
        except TransactionNotFound as e:
            last_err = e
        time.sleep(interval)
    # 超时也返回最后一次获取到的 info 或抛出
    if last_err:
        raise last_err
    return {}

@dataclass
class TronAddress:
    address: str
    private_key_hex: str  # 64 hex


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

def send_trx(priv_hex: str, from_addr: str, to_addr: str, amount_trx: float) -> str:
    c = _get_client()
    amt_sun = int(Decimal(str(amount_trx)) * Decimal(1_000_000))
    tx = c.trx.transfer(from_addr, to_addr, amt_sun).build().sign(PrivateKey(bytes.fromhex(priv_hex))).broadcast()
    txid = tx.txid
    info = wait_tx_committed(txid, timeout=45)
    # 判定成功：有块号且未标记 FAILED
    if info and info.get("result") != "FAILED" and info.get("blockNumber") is not None:
        return txid
    raise RuntimeError(f"TRX topup not confirmed: {info or 'no-info'} txid={txid}")

def generate_address() -> TronAddress:
    """仅用于占位/初始化，生产上请使用你现有的加密私钥方案"""
    pk = PrivateKey.random()
    return TronAddress(
        address=pk.public_key.to_base58check_address(),
        private_key_hex=pk.hex(),
    )


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
    将 amount USDT 从 from_addr 转到 to_addr，等待确认，返回 txid
    如果回执不是 SUCCESS（如 OUT_OF_ENERGY / REVERT 等），直接抛异常，让上层保持 collecting 状态重试。
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
            # 常见位置：contractResult/receipt/result/ret 等；tronpy 回执结构可能因节点差异略不同
            result = (receipt.get('receipt') or {}).get('result') or receipt.get('contractRet') or ''
            result = str(result).upper()
            if result != 'SUCCESS':
                raise RuntimeError(f"transfer receipt not SUCCESS: {result}  txid={tx.txid}")

            collect_logger.info(
                f"✅ USDT 转账确认成功：txid={tx.txid} result={result}"
            )
            return tx.txid

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _task)

    return await _retry_with_backoff(_call)

# ========== 地址校验 ==========
# 轻量级格式校验：T 开头 + 34 位 Base58 字符（排除 0 O I l）
_BASE58_RE = re.compile(r"^T[1-9A-HJ-NP-Za-km-z]{33}$")


def is_valid_address(address: str) -> bool:
    """
    仅做**快速格式校验**（Base58Check 的弱校验）：
    - 以 'T' 开头
    - 长度 34
    - 仅包含 Base58 字符（排除 0 O I l）
    如果需要更严格的链上校验，可在上层调用 `get_usdt_balance(address)` 等读链接口进一步验证。
    """
    if not isinstance(address, str):
        return False
    if not _BASE58_RE.match(address):
        return False
    return True


def get_trc20_balance(address: str, contract: str) -> float:
    """读取任意 TRC20 合约余额（6 位精度按 USDT 处理）。"""
    c = _get_client()  # 复用你文件里已有的 client 构造函数
    token = c.get_contract(contract)
    raw = token.functions.balanceOf(address)
    val = int(raw) if isinstance(raw, int) else int(raw[0])
    return val / 1_000_000.0

def fetch_recent_transfers(address: str, limit: int = 10) -> List[Dict]:
    """近 10 笔 TRC20 转账（基于 TronGrid）。"""
    if not TRONGRID_API_KEY:
        return []
    headers = {"TRON-PRO-API-KEY": TRONGRID_API_KEY}
    url = f"https://api.trongrid.io/v1/accounts/{address}/transactions/trc20?limit={limit}"
    r = requests.get(url, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json().get("data", [])
    items = []
    for it in data:
        items.append({
            "txid": it.get("transaction_id"),
            "token": it.get("token_info", {}).get("symbol", "TRC20"),
            "amount": float(it.get("value", 0)) / (10 ** int(it.get("token_info", {}).get("decimals", 6))),
            "from": it.get("from"),
            "to": it.get("to"),
            "ts": int(it.get("block_timestamp", 0)) // 1000,
        })
    return items

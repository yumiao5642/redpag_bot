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
                .fee_limit(15_000_000)  # 上限保护；有能量时不会真的花这么多 TRX
                .build()
                .sign(PrivateKey(bytes.fromhex(priv_hex)))
                .broadcast()
            )
            receipt = tx.wait()
            collect_logger.info(
                f"✅ USDT 转账完成：txid={tx.txid} status={receipt.get('receipt', {}).get('result')}"
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

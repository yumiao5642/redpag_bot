import asyncio
from decimal import Decimal
from dataclasses import dataclass
from tronpy import Tron
from tronpy.keys import PrivateKey
from ..config import USDT_CONTRACT, TRON_FULLNODE_URL, USDT_DECIMALS
from ..logger import collect_logger

def _get_client() -> Tron:
    if TRON_FULLNODE_URL:
        from tronpy.providers import HTTPProvider
        return Tron(provider=HTTPProvider(TRON_FULLNODE_URL))
    return Tron()  # 默认主网公共节点

@dataclass
class TronAddress:
    address: str
    private_key_hex: str  # 64 hex

def generate_address() -> TronAddress:
    # 生产不使用该方法，留给“新用户初始化”占位（你已使用）；真实地址来自加密私钥存储
    pk = PrivateKey.random()
    return TronAddress(address=pk.public_key.to_base58check_address(), private_key_hex=pk.hex())

async def get_usdt_balance(address: str) -> float:
    def _task():
        c = _get_client()
        usdt = c.get_contract(USDT_CONTRACT)
        raw = usdt.functions.balanceOf(address)
        return float(Decimal(raw) / (Decimal(10) ** USDT_DECIMALS))
    return await asyncio.get_running_loop().run_in_executor(None, _task)

async def usdt_transfer_all(priv_hex: str, from_addr: str, to_addr: str, amount: float) -> str:
    """
    将 amount USDT 从 from_addr 转到 to_addr，等待确认，返回 txid
    """
    def _task():
        c = _get_client()
        usdt = c.get_contract(USDT_CONTRACT)
        amt = int(Decimal(str(amount)) * (Decimal(10) ** USDT_DECIMALS))
        tx = (
            usdt.functions.transfer(to_addr, amt)
            .with_owner(from_addr)
            .fee_limit(15_000_000)    # 15 TRX 上限，能量足时不会消耗这么多
            .build()
            .sign(PrivateKey(bytes.fromhex(priv_hex)))
            .broadcast()
        )
        receipt = tx.wait()  # 等待链上确认（抛异常则外层捕获）
        collect_logger.info(f"✅ USDT 转账完成：txid={tx.txid} status={receipt.get('receipt',{}).get('result')}")
        return tx.txid
    return await asyncio.get_running_loop().run_in_executor(None, _task)

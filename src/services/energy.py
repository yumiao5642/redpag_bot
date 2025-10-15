import httpx
from typing import Optional, Dict, Any
from ..config import TRONGAS_API_KEY
from ..logger import collect_logger

API_URL = "https://trongas.io/api/batchPay"

async def rent_energy(receive_address: str, pay_nums: int = 65000, rent_time: int = 1, order_notes: Optional[str] = None) -> Dict[str, Any]:
    """
    调用 trongas 能量租用接口：
    - 仅使用 apiKey（.env: TRONGAS_API_KEY）
    - 默认租 65,000，1 小时
    返回 data（包含 orderId、orderMoney、hash[] 等）
    """
    if not TRONGAS_API_KEY:
        raise RuntimeError("TRONGAS_API_KEY 未配置，无法租用能量")
    payload = {
        "apiKey": TRONGAS_API_KEY,
        "payNums": int(pay_nums),
        "rentTime": int(rent_time),
        "receiveAddress": receive_address,
        "orderNotes": order_notes or ""
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(API_URL, json=payload)
        r.raise_for_status()
        js = r.json()
    if js.get("code") != 10000:
        msg = f"trongas 下单失败：code={js.get('code')} msg={js.get('msg')}"
        collect_logger.error(msg)
        raise RuntimeError(msg)
    data = js.get("data") or {}
    collect_logger.info(f"⚡ 能量下单成功：orderId={data.get('orderId')} money={data.get('orderMoney')} TRX")
    return data

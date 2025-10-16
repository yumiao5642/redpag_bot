# src/services/energy.py
import os
import re
from typing import Any, Dict, Optional

import httpx

from ..config import TRONGAS_API_KEY
from ..logger import collect_logger

API_URL = "https://trongas.io/api/batchPay"


def _normalize_paynums(n: int) -> int:
    """
    将请求量 n 归一化到 >= 最小租用量，且按步长向上取整。
    TRONGAS_MIN_RENT 默认 32000，TRONGAS_RENT_STEP 默认 1000。
    """
    min_rent = int(os.getenv("TRONGAS_MIN_RENT", "32000"))
    step = max(int(os.getenv("TRONGAS_RENT_STEP", "1000")), 1)
    n = max(int(n), min_rent)
    n = ((n + step - 1) // step) * step
    return n


def _safe_notes(s: Optional[str]) -> str:
    """
    备注只允许：汉字 / 字母 / 数字 / 下划线 _ / 破折号 -
    并限制长度（<=32），防止触发 trongas 校验。
    """
    s = s or ""
    s = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]", "", s)
    s = s[:32]
    return s or "hb"


async def rent_energy(
    receive_address: str,
    pay_nums: int = 65000,
    rent_time: int = 1,
    order_notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    调用 trongas 能量租用接口（仅使用 apiKey）。
    - 单次最小 32000，按步长取整（默认 1000）。
    - 备注字符合规。
    """
    if not TRONGAS_API_KEY:
        raise RuntimeError("TRONGAS_API_KEY 未配置，无法租用能量")

    pay_nums = _normalize_paynums(pay_nums)
    order_notes = _safe_notes(order_notes)

    payload = {
        "apiKey": TRONGAS_API_KEY,
        "payNums": int(pay_nums),
        "rentTime": int(rent_time),
        "receiveAddress": receive_address,
        "orderNotes": order_notes,
    }

    collect_logger.info(
        f"⚡ 正在请求租用能量：payNums={pay_nums}, rentTime={rent_time}, addr={receive_address}, notes='{order_notes}'"
    )

    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(API_URL, json=payload)
        r.raise_for_status()
        data = r.json()
        # 统一错误抛出（保留服务端 code/msg）
        if data.get("code") != 10000:
            raise RuntimeError(
                f"trongas 下单失败：code={data.get('code')} msg={data.get('msg')}"
            )
        return data.get("data", {})

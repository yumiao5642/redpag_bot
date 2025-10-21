# -*- coding: utf-8 -*-
# src/services/risk.py
from __future__ import annotations
import re
import httpx
from typing import Tuple, List, Dict, Any
from ..config import GOPLUS_API_KEY, GOPLUS_BASE_URL
from ..logger import app_logger

_HIGH_RISK_FIELDS = [
    "phishing_activities",
    "sanctioned",
    "darkweb_transactions",
    "money_laundering",
    "cybercrime",
]
_MEDIUM_RISK_FIELDS = [
    "blacklist_doubt",
    "mixer",
    "honeypot_related_address",
    "financial_crime",
    "fake_token_deployer",
]

def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    try:
        if isinstance(v, (int, float)):
            return v > 0
        s = str(v).strip().lower()
        return s in ("1", "true", "yes")
    except Exception:
        return False

def _pick_any(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, dict):
                return v
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v[0]
        return obj
    if isinstance(obj, list) and obj and isinstance(obj[0], dict):
        return obj[0]
    return {}

# 关键：把 Header 里的值清洗成 ASCII（HTTP 头部要求 ASCII / Latin-1）
_ASCII_VISIBLE = re.compile(r"[^\x20-\x7E]")  # 仅保留可见 ASCII

def _ascii_or_none(s: str | None) -> str | None:
    if not s:
        return None
    # 去掉包裹的引号与前后空白
    s = s.strip().strip("'").strip('"').strip()
    # 去除所有非 ASCII 可见字符
    cleaned = _ASCII_VISIBLE.sub("", s)
    try:
        cleaned.encode("ascii")
        return cleaned if cleaned else None
    except UnicodeEncodeError:
        return None

async def check_address_risk(address: str) -> Tuple[str, List[str], Dict[str, Any]]:
    """
    返回: (risk_level, triggers, raw)
    - risk_level: "高" | "中" | "低" | "—"(查询失败)
    - triggers: 命中的风险字段列表
    - raw: 原始数据（可用于调试）
    """
    url = f"{GOPLUS_BASE_URL.rstrip('/')}/api/v1/address_security/{address}"

    headers: Dict[str, str] = {}
    token = _ascii_or_none(GOPLUS_API_KEY)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    else:
        if GOPLUS_API_KEY:  # 配置了但不合法 → 给出一次性告警
            app_logger.warning("[GoPlus] GOPLUS_API_KEY 包含非 ASCII 字符，已自动忽略并改为匿名请求。请检查 .env 是否有中文/全角符号/引号。")

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(url, params={"chain_id": "tron"}, headers=headers)
            r.raise_for_status()
            js = r.json() or {}

        raw = _pick_any(js.get("result") or js.get("data") or js)
        if not raw:
            return "—", [], js

        hi = [k for k in _HIGH_RISK_FIELDS if _truthy(raw.get(k))]
        md = [k for k in _MEDIUM_RISK_FIELDS if _truthy(raw.get(k))]

        if hi:
            level = "高"; triggers = hi + md
        elif md:
            level = "中"; triggers = md
        else:
            level = "低"; triggers = []

        return level, triggers, raw

    except Exception as e:
        # 注意：这里不要把异常对象直接拼接到 Header/URL（避免再次触发编码问题）
        app_logger.warning("[GoPlus] 风险查询失败（已忽略，继续执行）。详情：%s", str(e))
        return "—", [], {}

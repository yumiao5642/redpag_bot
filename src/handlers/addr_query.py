# -*- coding: utf-8 -*-
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .common import fmt_amount, show_main_menu
from ..services.tron import (
    is_valid_address, get_trx_balance, get_usdt_balance,
    get_account_resource, get_recent_transfers
)
from ..services.risk import check_address_risk  # ← 新增

_FULL_BAR = "｜"  # 全角竖线，表格更美观

def _pad(s: str, width: int, align: str = "left") -> str:
    """
    使用等宽字体显示时的简单填充；中文宽度在 Telegram Code 字体下也基本可接受。
    align: left/center/right
    """
    s = str(s)
    n = len(s)
    if n >= width:
        return s[:width]
    pad = width - n
    if align == "right":
        return " " * pad + s
    if align == "center":
        left = pad // 2
        right = pad - left
        return " " * left + s + " " * right
    return s + " " * pad

def _fmt_row(dt: str, typ: str, asset: str, amt: str, peer: str) -> str:
    return (
        _pad(dt,   16) + _FULL_BAR +
        _pad(typ,   3, "center") + _FULL_BAR +
        _pad(asset, 4, "center") + _FULL_BAR +
        _pad(amt,   9, "right") + _FULL_BAR +
        " " + peer
    )

def _overview_block(trx: float, usdt: float, bandwidth: int, energy: int) -> str:
    head = _fmt_row("资产/资源", "—", "—", "—", "—")
    r1 = _fmt_row("TRX 余额", "", "", f"{trx:.6f}", "")
    r2 = _fmt_row("USDT 余额", "", "", f"{usdt:.6f}", "")
    r3 = _fmt_row("资源", "", "", f"BW {bandwidth}", f"EN {energy}")
    return "\n".join([head, r1, r2, r3])

async def addr_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb
    await update.message.reply_text("请发送要校验的 TRON 地址：", reply_markup=cancel_kb("addr_query"))
    context.user_data["addr_query_waiting"] = True
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb, show_main_menu

    if not context.user_data.pop("addr_query_waiting", False):
        return
    addr = (update.message.text or "").strip()

    if not is_valid_address(addr):
        await update.message.reply_text("当前仅支持TRC-20格式地址,请重新输入", reply_markup=cancel_kb("addr_query"))
        await show_main_menu(update.effective_chat.id, context)
        return

    # 基本信息
    trx = get_trx_balance(addr)
    usdt = await get_usdt_balance(addr)
    res = get_account_resource(addr)

    # GoPlus 风险（失败不阻断）
    risk_level, triggers, _ = await check_address_risk(addr)
    # 触发字段 → 中文
    cn_map = {
        "phishing_activities": "网络钓鱼",
        "sanctioned": "被制裁",
        "darkweb_transactions": "暗网交易",
        "money_laundering": "洗钱",
        "cybercrime": "网络犯罪",
        "blacklist_doubt": "可疑黑名单",
        "mixer": "混币",
        "honeypot_related_address": "蜜罐关联",
        "financial_crime": "金融犯罪",
        "fake_token_deployer": "伪代币部署",
    }
    reasons = [cn_map.get(t, t) for t in (triggers or [])]

    if risk_level == "低":
        risk_line = "风险评估：正常 【数据来源-慢雾科技】"
    elif risk_level in ("中", "高"):
        suffix = f"（{('、'.join(reasons))}）" if reasons else ""
        risk_line = f"风险评估：{risk_level}{suffix} 【数据来源-慢雾科技】"
    else:
        risk_line = "风险评估：未知"

    # 最近 10 笔 TRC20 转账
    transfers = await get_recent_transfers(addr, limit=10)

    # 组织输出
    lines = [
        f"🧭 地址查询",
        f"📮 地址：`{addr}`",
        risk_line,
        "",
        "账户概览：",
        "```" + _overview_block(trx, usdt, res['bandwidth'], res['energy']) + "```",
        "",
        "最近转账（最多 10 条）：",
    ]

    if transfers:
        header = _fmt_row("时间", "类", "币", "金额", "对方地址")
        rows = [header]
        for t in transfers:
            dt = datetime.fromtimestamp(t["ts"]).strftime("%Y-%m-%d %H:%M") if t.get("ts") else "-"
            direction = "入" if (t.get("to","").lower() == addr.lower()) else "出"
            asset = t.get("asset") or "USDT"
            amt = fmt_amount(t.get("amount", 0))
            peer = t.get("from") if direction == "入" else t.get("to")
            rows.append(_fmt_row(dt, direction, asset, amt, peer))
        lines.append("```" + "\n".join(rows) + "```")
    else:
        lines.append("```无最近转账```")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(update.effective_chat.id, context)

# -*- coding: utf-8 -*-
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .common import fmt_amount, show_main_menu
from ..services.tron import (
    is_valid_address, get_trx_balance, get_usdt_balance,
    get_account_resource, get_recent_transfers, get_account_meta, probe_account_type
)
from ..services.risk import check_address_risk
from ..utils.monofmt import pad as mpad  # ← 新增
_FULL_BAR = "｜"

def _pad(s: str, width: int, align: str = "left") -> str:
    # 用等宽排版工具替代原逻辑
    return mpad(s, width, align)

def _fmt_row(dt: str, typ: str, asset: str, amt: str, peer: str) -> str:
    # 统一列宽：时间(16)｜类(2)｜币(5)｜金额(12右对齐)｜对方地址(34)
    return (
        _pad(dt,   16) + _FULL_BAR +
        _pad(typ,   2, "center") + _FULL_BAR +
        _pad(asset, 5, "center") + _FULL_BAR +
        _pad(amt,  12, "right") + _FULL_BAR +
        " " + peer
    )

def _fnum(x, d=2):
    try:
        return f"{float(x):,.{d}f}"
    except Exception:
        return str(x)

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

    trx = get_trx_balance(addr)
    usdt = await get_usdt_balance(addr)
    res  = get_account_resource(addr)
    meta = await get_account_meta(addr)
    label_info = probe_account_type(addr)

    if label_info.get("is_exchange"):
        type_text = f"交易所账户：{label_info.get('name') or '-'}"
    elif label_info.get("is_official"):
        type_text = f"官方/项目方账户：{label_info.get('name') or '-'}"
    elif meta.get("is_contract"):
        type_text = "合约账户"
    else:
        type_text = "普通账户"

    risk_level, triggers, _ = await check_address_risk(addr)
    cn_map = {
        "phishing_activities": "网络钓鱼", "sanctioned": "被制裁", "darkweb_transactions": "暗网交易",
        "money_laundering": "洗钱", "cybercrime": "网络犯罪", "blacklist_doubt": "可疑黑名单",
        "mixer": "混币", "honeypot_related_address": "蜜罐关联", "financial_crime": "金融犯罪", "fake_token_deployer": "伪代币部署",
    }
    reasons = [cn_map.get(t, t) for t in (triggers or [])]
    if risk_level == "低":
        risk_line = "风险评估：正常 【数据来源-慢雾科技】"
    elif risk_level in ("中", "高"):
        suffix = f"（{('、'.join(reasons))}）" if reasons else ""
        risk_line = f"风险评估：{risk_level}{suffix} 【数据来源-慢雾科技】"
    else:
        risk_line = "风险评估：未知"

    top_lines = [
        f"🧭 地址查询： {addr}",
        f"⏰ 创建时间：{meta.get('created_at') or '-'}",
        f"🌟 最后活跃：{meta.get('last_active') or '-'}",
        f"👤 账户类型：{type_text}",
        f"🚨 {risk_line}",
        "",
        "账户概览：",
        f"💰 TRX 余额：{_fnum(trx)} TRX",
        f"💰 TRX 质押：{_fnum(meta.get('frozen_trx') or 0)} TRX",
        f"💰 USDT余额：{_fnum(usdt)} USDT",
        f"🔋 能量：{_fnum(res.get('energy'), 0)} / {_fnum(res.get('energy_limit', 0), 0)}",
        f"📡 质押带宽：{_fnum(max(0, res.get('bandwidth_stake_total', 0) - res.get('bandwidth_stake_used', 0)), 0)} / {_fnum(res.get('bandwidth_stake_total', 0), 0)}",
        f"📡 免费带宽：{_fnum(max(0, res.get('bandwidth_free_total', 0) - res.get('bandwidth_free_used', 0)), 0)} / {_fnum(res.get('bandwidth_free_total', 0), 0)}",
        ""
    ]

    transfers = await get_recent_transfers(addr, limit=10)
    if transfers:
        rows = ["最近转账（最多 10 条）：",
                _fmt_row("时间", "类", "币", "金额", "对方地址")]
        for t in transfers:
            dt = datetime.fromtimestamp(t["ts"]).strftime("%Y-%m-%d %H:%M") if t.get("ts") else "-"
            direction = "入" if (t.get("to","").lower() == addr.lower()) else "出"
            asset = t.get("asset") or "USDT"
            amt = fmt_amount(t.get("amount", 0))
            peer = t.get("from") if direction == "入" else t.get("to")
            rows.append(_fmt_row(dt, direction, asset, amt, peer))
        top_lines.append("```" + "\n".join(rows) + "```")
    else:
        top_lines.append("```最近转账（最多 10 条）：\n无最近转账```")

    await update.message.reply_text("\n".join(top_lines), parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(update.effective_chat.id, context)

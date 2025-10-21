# -*- coding: utf-8 -*-
from telegram import Update
from telegram.ext import ContextTypes
from ..models import list_ledger_recent, get_wallet
from .common import fmt_amount

_CN = {
    "recharge": "充值",
    "withdraw": "提现",
    "redpacket_send": "发送红包",
    "redpacket_claim": "领取红包",
    "adjust": "调整",
}

# --- src/handlers/ledger.py 替换 show_ledger ---
async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = fmt_amount((wallet or {}).get("usdt_trc20_balance", 0.0))

    rows = await list_ledger_recent(u.id, 10)
    header = f"💼 当前余额：{bal} USDT-TRC20\n—— 最近 10 笔账变 ——"
    if not rows:
        await update.message.reply_text(header + "\n```暂无记录```", parse_mode="Markdown"); return

    lines = ["时间 | 类型 | 变更额 | 余额后"]
    cn = {"recharge":"充值","withdraw":"提现","redpacket_send":"发送红包","redpacket_claim":"领取红包","adjust":"调整"}
    for r in rows:
        t = str(r["created_at"])[:19]
        ct = cn.get(r["change_type"], r["change_type"])
        amt = fmt_amount(r["amount"])
        after = fmt_amount(r["balance_after"])
        lines.append(f"{t} | {ct} | {amt} | {after}")

    text = header + "\n\n" + "```" + "\n".join(lines) + "```"   # 关键：header 与 ``` 间空一行，避免“顶到标题行”
    await update.message.reply_text(text, parse_mode="Markdown")

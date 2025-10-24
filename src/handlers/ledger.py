# -*- coding: utf-8 -*-
from telegram import Update
from telegram.ext import ContextTypes
from ..models import list_ledger_recent, get_wallet
from ..consts import LEDGER_TYPE_CN  # 统一使用全局映射
from .common import fmt_amount


def _fmt_delta(x) -> str:
    try:
        v = float(x)
        s = f"{v:.2f}"
        return (" " + s) if v >= 0 else s  # 正数前补一个空格
    except Exception:
        return " 0.00"

async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = fmt_amount((wallet or {}).get("usdt_trc20_balance", 0.0))
    rows = await list_ledger_recent(u.id, 10)
    header = f"💼 当前余额：{bal} USDT-TRC20\n—— 最近 10 笔账变 ——"
    if not rows:
        await update.message.reply_text(header + "\n```暂无记录```", parse_mode="Markdown")
        return

    lines = ["时间｜类型｜变更额｜余额后｜订单号"]
    for r in rows:
        t = str(r["created_at"])[:19]
        ct = LEDGER_TYPE_CN.get(r["change_type"], r["change_type"])
        amt = _fmt_delta(r["amount"])                 # 只在“变更额”列做左侧空格补齐
        after = fmt_amount(r["balance_after"])
        on = (r.get("order_no") or "")
        tail = on[-4:] if len(on) >= 4 else on
        show_on = ("…" + tail) if tail else ""
        lines.append(f"{t}｜{ct}｜{amt}｜{after}｜{show_on}")

    text = header + "\n\n" + "```" + "\n".join(lines) + "```"
    await update.message.reply_text(text, parse_mode="Markdown")

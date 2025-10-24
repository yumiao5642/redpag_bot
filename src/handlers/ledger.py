# -*- coding: utf-8 -*-
from telegram import Update
from telegram.ext import ContextTypes
from ..models import list_ledger_recent, get_wallet
from ..consts import LEDGER_TYPE_CN
from .common import fmt_amount
from ..utils.monofmt import pad as mpad  # ← 新增

def _fmt_row(t, typ, delta, after, on):
    # 时间(19)｜类型(8)｜变更额(12右)｜余额后(12右)｜订单号(12)
    return (
        f"{mpad(t, 19)}｜{mpad(typ, 8)}｜{mpad(delta, 12, 'right')}｜"
        f"{mpad(after, 12, 'right')}｜{mpad(on, 12)}"
    )

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

    header = f"💼 当前余额：{bal} USDT-TRC20"
    if not rows:
        text = header + "\n```最近 10 笔账变：\n暂无记录```"
        await update.message.reply_text(text, parse_mode="Markdown")
        return

    lines = ["最近 10 笔账变：", _fmt_row("时间", "类型", "变更额", "余额后", "订单号")]
    for r in rows:
        t = str(r["created_at"])[:19]
        ct = LEDGER_TYPE_CN.get(r["change_type"], r["change_type"])
        amt = _fmt_delta(r["amount"])
        after = fmt_amount(r["balance_after"])
        on = (r.get("order_no") or "")
        tail = on[-4:] if len(on) >= 4 else on
        show_on = ("…" + tail) if tail else ""
        lines.append(_fmt_row(t, ct, amt, after, show_on))

    text = header + "\n\n" + "```" + "\n".join(lines) + "```"
    await update.message.reply_text(text, parse_mode="Markdown")

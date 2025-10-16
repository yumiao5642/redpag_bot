# -*- coding: utf-8 -*-
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .common import fmt_amount, show_main_menu
from ..services.tron import (
    is_valid_address, get_trx_balance, get_usdt_balance,
    get_account_resource, get_recent_transfers
)
from ..config import USDT_CONTRACT

async def addr_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请发送要校验的 TRON 地址：")
    context.user_data["addr_query_waiting"] = True

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("addr_query_waiting", False):
        return
    addr = (update.message.text or "").strip()

    if not is_valid_address(addr):
        await update.message.reply_text("当前仅支持TRC-20格式地址,请重新输入")
        await show_main_menu(update.effective_chat.id, context)
        return

    trx = get_trx_balance(addr)
    usdt = await get_usdt_balance(addr)  # 从 USDT_CONTRACT 读取
    res = get_account_resource(addr)     # dict: {'bandwidth': int, 'energy': int}
    transfers = await get_recent_transfers(addr, limit=10)

    lines = [
        f"📮 地址：`{addr}`",
        f"TRX：{fmt_amount(trx)}",
        f"USDT：{fmt_amount(usdt)}",
        f"带宽：{res['bandwidth']} / 能量：{res['energy']}",
        ""
    ]
    if transfers:
        lines.append("🧾 最近 10 笔转账：")
        for t in transfers:
            dr = "↗️ 收" if t["to"].lower()==addr.lower() else "↘️ 付"
            asset = t.get("asset","USDT")
            amt = fmt_amount(t["amount"])
            lines.append(f"{dr} {asset} {amt}  {t['hash'][:10]}…")
    else:
        lines.append("（无最近转账）")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(update.effective_chat.id, context)

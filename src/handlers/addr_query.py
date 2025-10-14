
from telegram import Update
from telegram.ext import ContextTypes
from ..services.tron import is_valid_address

async def addr_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请发送要校验的 TRON 地址：")
    context.user_data["addr_query_waiting"] = True

async def addr_query_ontext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("addr_query_waiting", False):
        return
    addr = (update.message.text or "").strip()
    ok = is_valid_address(addr)
    await update.message.reply_text(f"地址 {addr} 校验结果：{'✅有效' if ok else '❌无效'}。\n（链上余额查询后续接入）")

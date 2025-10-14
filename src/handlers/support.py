
from telegram import Update
from telegram.ext import ContextTypes
from ..config import SUPPORT_CONTACT

async def show_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"联系客服：{SUPPORT_CONTACT}")

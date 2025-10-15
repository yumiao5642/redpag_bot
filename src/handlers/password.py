
import hashlib
from telegram import Update
from telegram.ext import ContextTypes
from ..models import set_tx_password_hash, get_tx_password_hash
from ..logger import password_logger
from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from .common import show_main_menu

from telegram import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from .common import show_main_menu

NUM_KB = ReplyKeyboardMarkup([
    [KeyboardButton("0"), KeyboardButton("1"), KeyboardButton("4")],
    [KeyboardButton("6"), KeyboardButton("9"), KeyboardButton("2")],
    [KeyboardButton("7"), KeyboardButton("3"), KeyboardButton("5")],
    [KeyboardButton("取消"), KeyboardButton("8"), KeyboardButton("⌫")]
], resize_keyboard=True, one_time_keyboard=True)

async def start_set_password(update, context):
    await update.message.reply_text("🔐 请输入新交易密码（4~6位数字）：\n\n`* * * *`",
        reply_markup=NUM_KB, parse_mode="Markdown")

def _hash_pw(user_id: int, pw: str) -> str:
    # 简单盐：user_id + sha256
    return hashlib.sha256(f"{user_id}:{pw}".encode()).hexdigest()

async def set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请输入新交易密码（不会回显，建议 6~18 位，避免过于简单）：")
    context.user_data["waiting_pw_new"] = True

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if context.user_data.pop("waiting_pw_new", False):
        pw = (update.message.text or "").strip()
        if len(pw) < 6 or len(pw) > 32:
            await update.message.reply_text("密码长度建议 6~18 位，请重新输入 /setpw"); return
        hpw = _hash_pw(u.id, pw)
        await set_tx_password_hash(u.id, hpw)
        password_logger.info(f"🔑 用户 {u.id} 设置/修改了交易密码")
        await update.message.reply_text("交易密码设置成功！")
        return

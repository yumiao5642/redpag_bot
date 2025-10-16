# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from .common import show_main_menu
from ..services.encryption import hash_password
from ..models import set_tx_password_hash, get_user_tx_password_hash

_NUMPAD = InlineKeyboardMarkup([
    [InlineKeyboardButton("1", callback_data="pwd:1"), InlineKeyboardButton("2", callback_data="pwd:2"), InlineKeyboardButton("3", callback_data="pwd:3")],
    [InlineKeyboardButton("4", callback_data="pwd:4"), InlineKeyboardButton("5", callback_data="pwd:5"), InlineKeyboardButton("6", callback_data="pwd:6")],
    [InlineKeyboardButton("7", callback_data="pwd:7"), InlineKeyboardButton("8", callback_data="pwd:8"), InlineKeyboardButton("9", callback_data="pwd:9")],
    [InlineKeyboardButton("⌫", callback_data="pwd:BK"), InlineKeyboardButton("0", callback_data="pwd:0"), InlineKeyboardButton("✅ 确认", callback_data="pwd:OK")],
])

async def start_set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["pwd_buf"] = ""
    await update.message.reply_text("请输入交易密码（仅数字）：", reply_markup=_NUMPAD)


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


async def password_kb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    buf = context.user_data.get("pwd_buf","")

    key = q.data.split(":")[1]
    if key == "BK":
        buf = buf[:-1]
    elif key == "OK":
        if len(buf) < 4:
            await q.message.edit_text(f"密码至少 4 位，请继续输入：\n当前：{'*'*len(buf)}", reply_markup=_NUMPAD)
            context.user_data["pwd_buf"] = buf
            return
        h = hash_password(buf)
        await set_tx_password_hash(update.effective_user.id, h)
        await q.message.edit_text("✅ 交易密码已设置/更新。")
        await show_main_menu(q.message.chat_id, context)
        return
    else:
        if len(buf) < 12: buf += key

    context.user_data["pwd_buf"] = buf
    await q.message.edit_text(f"请输入交易密码（仅数字）：\n当前：{'*'*len(buf)}", reply_markup=_NUMPAD)

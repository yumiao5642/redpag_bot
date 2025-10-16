<<<<<<< HEAD
# src/handlers/password.py
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
=======
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

>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)

from ..models import has_tx_password, set_tx_password_hash
from ..services.encryption import hash_password
from .common import show_main_menu


def _kb(masked=True):
    # 0-9 九宫格 + 取消 + 显示/隐藏
    rows = []
    nums = ["0", "1", "4", "6", "9", "2", "7", "3", "5", "8"]
    for i in range(0, 9, 3):
        rows.append(
            [
                InlineKeyboardButton(nums[i + j], callback_data=f"pwd:{nums[i+j]}")
                for j in range(3)
            ]
        )
    rows.append(
        [
            InlineKeyboardButton("取消", callback_data="pwd:back"),
            InlineKeyboardButton("0", callback_data="pwd:0"),
            InlineKeyboardButton("👁" if masked else "🙈", callback_data="pwd:vis"),
        ]
    )
    rows.append([InlineKeyboardButton("确定", callback_data="pwd:ok")])
    return InlineKeyboardMarkup(rows)


async def start_set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    context.user_data["pwd_buf"] = ""
    context.user_data["pwd_mask"] = True
    existed = await has_tx_password(u.id)
    title = "修改交易密码" if existed else "设置交易密码"
    hint = "请输入新交易密码（4~6位数字）"
    await update.message.reply_text(
        f"🛠 {title}\n{hint}\n\n🔑 " + "•" * 0, reply_markup=_kb(True)
    )


async def password_kb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "").split(":")[1]
    buf = context.user_data.get("pwd_buf", "")
    masked = context.user_data.get("pwd_mask", True)

    if data == "back":
        await q.edit_message_text("已取消设置。")
        await show_main_menu(q.message.chat_id, context)
        return
<<<<<<< HEAD
    if data == "vis":
        masked = not masked
        context.user_data["pwd_mask"] = masked
        disp = "•" * len(buf) if masked else buf
        await q.edit_message_text(
            f"🛠 设置交易密码\n\n🔑 {disp}", reply_markup=_kb(masked)
        )
        return
    if data == "ok":
        if len(buf) < 4 or len(buf) > 6:
            await q.answer("请输入4~6位数字", show_alert=True)
            return
        u = q.from_user
        await set_tx_password_hash(u.id, hash_password(buf))
        await q.edit_message_text("✅ 交易密码设置成功")
        await show_main_menu(q.message.chat_id, context)
        return

    # 数据是数字
    if len(buf) >= 6:
        await q.answer("最多6位数字", show_alert=True)
        return
    buf += data
    context.user_data["pwd_buf"] = buf
    disp = "•" * len(buf) if masked else buf
    await q.edit_message_text(f"🛠 设置交易密码\n\n🔑 {disp}", reply_markup=_kb(masked))
=======


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
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)

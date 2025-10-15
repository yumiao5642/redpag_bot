# src/handlers/password.py
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..models import set_tx_password_hash, has_tx_password
from ..services.encryption import hash_password
from .common import show_main_menu

def _kb(masked=True):
    # 0-9 九宫格 + 取消 + 显示/隐藏
    rows = []
    nums = ["0","1","4","6","9","2","7","3","5","8"]
    for i in range(0, 9, 3):
        rows.append([InlineKeyboardButton(nums[i+j], callback_data=f"pwd:{nums[i+j]}") for j in range(3)])
    rows.append([InlineKeyboardButton("取消", callback_data="pwd:back"),
                 InlineKeyboardButton("0", callback_data="pwd:0"),
                 InlineKeyboardButton("👁" if masked else "🙈", callback_data="pwd:vis")])
    rows.append([InlineKeyboardButton("确定", callback_data="pwd:ok")])
    return InlineKeyboardMarkup(rows)

async def start_set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    context.user_data["pwd_buf"] = ""
    context.user_data["pwd_mask"] = True
    existed = await has_tx_password(u.id)
    title = "修改交易密码" if existed else "设置交易密码"
    hint = "请输入新交易密码（4~6位数字）"
    await update.message.reply_text(f"🛠 {title}\n{hint}\n\n🔑 " + "•"*0, reply_markup=_kb(True))

async def password_kb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = (q.data or "").split(":")[1]
    buf = context.user_data.get("pwd_buf","")
    masked = context.user_data.get("pwd_mask", True)

    if data == "back":
        await q.edit_message_text("已取消设置。")
        await show_main_menu(q.message.chat_id, context); return
    if data == "vis":
        masked = not masked
        context.user_data["pwd_mask"] = masked
        disp = "•"*len(buf) if masked else buf
        await q.edit_message_text(f"🛠 设置交易密码\n\n🔑 {disp}", reply_markup=_kb(masked))
        return
    if data == "ok":
        if len(buf) < 4 or len(buf) > 6:
            await q.answer("请输入4~6位数字", show_alert=True); return
        u = q.from_user
        await set_tx_password_hash(u.id, hash_password(buf))
        await q.edit_message_text("✅ 交易密码设置成功")
        await show_main_menu(q.message.chat_id, context); return

    # 数据是数字
    if len(buf) >= 6:
        await q.answer("最多6位数字", show_alert=True); return
    buf += data
    context.user_data["pwd_buf"] = buf
    disp = "•"*len(buf) if masked else buf
    await q.edit_message_text(f"🛠 设置交易密码\n\n🔑 {disp}", reply_markup=_kb(masked))

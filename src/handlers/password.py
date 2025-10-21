# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from .common import show_main_menu
from ..services.encryption import hash_password, verify_password
from ..models import set_tx_password_hash, get_tx_password_hash
from ..logger import password_logger
from telegram.error import BadRequest

# 键盘布局（尽量贴近截图）：三行 + 底部“取消 / 数字3 / 👁”
_PWD_KBD = InlineKeyboardMarkup([
    [InlineKeyboardButton("0", callback_data="pwd:0"),
     InlineKeyboardButton("5", callback_data="pwd:5"),
     InlineKeyboardButton("4", callback_data="pwd:4")],
    [InlineKeyboardButton("2", callback_data="pwd:2"),
     InlineKeyboardButton("8", callback_data="pwd:8"),
     InlineKeyboardButton("7", callback_data="pwd:7")],
    [InlineKeyboardButton("9", callback_data="pwd:9"),
     InlineKeyboardButton("1", callback_data="pwd:1"),
     InlineKeyboardButton("6", callback_data="pwd:6")],
    [InlineKeyboardButton("取消", callback_data="pwd:CANCEL"),
     InlineKeyboardButton("3", callback_data="pwd:3"),
     InlineKeyboardButton("👁", callback_data="pwd:TOGGLE")],
    [InlineKeyboardButton("⌫ 退格", callback_data="pwd:BK")]
])
def _kbd():
    return _PWD_KBD


def _mask(s: str, vis: bool) -> str:
    if vis:
        return s.ljust(4, "_")
    return ("•" * len(s)).ljust(4, "_")

def _render(stage: str, buf: str, vis: bool) -> str:
    title = "⚙️ 设置中心"
    hint = {"ask_old":"请输入旧交易密码","ask_new":"请输入新的交易密码","ask_confirm":"请再次输入新的交易密码"}[stage]
    return f"{title}\n\n{hint}\n--------------------------------\n🔑 {_mask(buf, vis)}"

async def set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """入口：根据是否已有密码决定从哪一步开始"""
    u = update.effective_user
    has_old = bool(await get_tx_password_hash(u.id))
    context.user_data["pwd_flow"] = {
        "stage": "ask_old" if has_old else "ask_new",
        "buf": "",
        "vis": False,
        "new1": None,
    }
    msg = _render(context.user_data["pwd_flow"]["stage"], "", False)
    await update.message.reply_text(msg, reply_markup=_kbd())

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 保留：如果未来需要纯文本模式可在此接管；当前键盘模式即可
    pass

async def password_kb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("pwd_flow")
    if not st:
        try:
            await q.message.edit_text("会话已过期，请重新进入“设置密码/修改密码”。")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        return

    def _safe_edit(txt: str):
        try:
            if (q.message.text or "").strip() == txt.strip():
                return
            return q.edit_message_text(txt, reply_markup=_PWD_KBD)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

    key = q.data.split(":",1)[1]
    if key == "CANCEL":
        context.user_data.pop("pwd_flow", None)
        try:
            await q.message.edit_text("已取消。")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        await show_main_menu(q.message.chat_id, context)
        return
    if key == "TOGGLE":
        st["vis"] = not st["vis"]
        await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
        return
    if key == "BK":
        st["buf"] = st["buf"][:-1]
        await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
        return

    # 数字键
    if key.isdigit() and len(key) == 1:
        if len(st["buf"]) >= 4:
            await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
            return
        st["buf"] += key
        await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
        # 满 4 位自动进入下一步 / 完成
        if len(st["buf"]) == 4:
            u = update.effective_user
            if st["stage"] == "ask_old":
                stored = await get_tx_password_hash(u.id)
                if not stored or not verify_password(st["buf"], stored):
                    st["buf"] = ""
                    await _safe_edit("旧密码不正确，请重新输入。\n\n" + _render("ask_old", "", st["vis"]))
                    return
                st["stage"] = "ask_new"; st["buf"] = ""; st["new1"] = None
                await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
                return
            elif st["stage"] == "ask_new":
                st["new1"] = st["buf"]; st["buf"] = ""; st["stage"] = "ask_confirm"
                await _safe_edit(_render(st["stage"], st["buf"], st["vis"]))
                return
            elif st["stage"] == "ask_confirm":
                if st["buf"] != st.get("new1"):
                    st["stage"] = "ask_new"; st["buf"] = ""; st["new1"] = None
                    await _safe_edit("两次输入不一致，请重新设置新密码。\n\n" + _render(st["stage"], st["buf"], st["vis"]))
                    return
                # 保存
                hpw = hash_password(st["buf"])
                await set_tx_password_hash(u.id, hpw)
                password_logger.info(f"🔑 用户 {u.id} 设置/修改了交易密码")
                context.user_data.pop("pwd_flow", None)
                try:
                    await q.message.edit_text("✅ 交易密码已更新。")
                except BadRequest as e:
                    if "Message is not modified" not in str(e):
                        raise
                await show_main_menu(q.message.chat_id, context)
                return

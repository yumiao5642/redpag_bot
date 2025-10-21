from telegram import Update
from telegram.error import BadRequest
from typing import Optional
from telegram import (
    InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from ..models import ensure_user, get_wallet, set_tron_wallet
from ..services.tron import generate_address
from ..services.encryption import encrypt_text
from ..logger import user_click_logger, app_logger

def fmt_amount(x) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return str(x)

async def ensure_user_and_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username, u.first_name, u.last_name)
    wallet = await get_wallet(u.id)
    if not wallet or not wallet.get("tron_address"):
        addr = generate_address()
        await set_tron_wallet(u.id, addr.address, encrypt_text(addr.private_key_hex))
        app_logger.info(f"🔐 为用户 {u.id} 生成 TRON 地址: {addr.address}")

    # 日志：ID（昵称｜@用户名）
    disp = ((u.first_name or "") + (u.last_name or "")).strip()
    user_click_logger.info(
        f"👆 用户 {u.id}（{disp or '-'}｜@{u.username or '-'}） 触发交互：{update.effective_message.text if update.effective_message else 'callback'}"
    )

MAIN_KB = ReplyKeyboardMarkup(
    [
        [KeyboardButton("💰 我的钱包")],
        [KeyboardButton("🧧 红包"), KeyboardButton("➕ 充值")],
        [KeyboardButton("💸 提现"), KeyboardButton("🧭 地址查询")],
        [KeyboardButton("🔐 设置密码/修改密码")]
    ],
    resize_keyboard=True
)

async def show_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: Optional[str]=None):
    if not text:
        text = "👇 请选择功能："
    await context.bot.send_message(chat_id, text, reply_markup=MAIN_KB)


def cancel_kb(tag: str = "input"):
    """
    通用“取消”按钮（行内键盘）
    tag 仅用于排查来源，不影响行为
    """
    return InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data=f"cancel:{tag}")]])

def clear_user_flow_flags(context: ContextTypes.DEFAULT_TYPE):
    """
    清理所有可能存在的“等待输入”状态位
    """
    keys = [
        "addrbook_waiting", "addrbook_del_waiting",
        "withdraw_add_waiting", "wd_wait_amount", "wd_target",
        "rp_query_waiting", "await_field",
        "addr_query_waiting",
        "rppwd_flow", "pwd_flow",
    ]
    for k in keys:
        context.user_data.pop(k, None)

async def cancel_any_input(update, context: ContextTypes.DEFAULT_TYPE):
    """
    通用“取消”按钮回调：清理状态 → 回复“已取消” → 回主菜单
    """
    q = update.callback_query
    await q.answer()
    clear_user_flow_flags(context)
    try:
        if (q.message.text or "").strip() != "已取消。":
            await q.edit_message_text("已取消。")
    except BadRequest:
        pass
    from .common import show_main_menu
    await show_main_menu(q.message.chat_id, context)

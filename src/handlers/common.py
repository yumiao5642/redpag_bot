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
from ..keyboards import MAIN_MENU

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
    disp = ((u.first_name or "") + (u.last_name or "")).strip()
    user_click_logger.info(
        f"👆 用户 {u.id}（{disp or '-'}｜@{u.username or '-'}） 触发交互：{update.effective_message.text if update.effective_message else 'callback'}"
    )


async def show_main_menu(chat_id: int, context: ContextTypes.DEFAULT_TYPE, text: Optional[str]=None):
    if not text:
        text = "👇 请选择功能："
    await context.bot.send_message(chat_id, text, reply_markup=MAIN_MENU)

def cancel_kb(tag: str = "input"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("取消", callback_data=f"cancel:{tag}")]])

def clear_user_flow_flags(context: ContextTypes.DEFAULT_TYPE):
    keys = [
        "addrbook_waiting", "addrbook_del_waiting",
        "withdraw_add_waiting", "wd_wait_amount", "wd_target",
        "rp_query_waiting", "await_field",
        "addr_query_waiting",
        "rppwd_flow", "pwd_flow",
        "wd_pwd_flow",
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

async def safe_reply(update, context, text: str, **kwargs):
    """优先用传入的 parse_mode 发送；若 Markdown 解析失败，降级为纯文本再发一次。"""
    try:
        return await update.message.reply_text(text, **kwargs)
    except BadRequest as e:
        if "parse entities" in str(e).lower() or "can" in str(e).lower():
            kwargs.pop("parse_mode", None)
            return await update.message.reply_text(text, **kwargs)
        raise

async def gc_track(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, tag: str):
    bag = context.chat_data.setdefault("_gc", {})
    bag.setdefault(tag, set()).add(message_id)

async def gc_delete(context: ContextTypes.DEFAULT_TYPE, chat_id: int, tag: str):
    bag = context.chat_data.get("_gc", {})
    ids = list(bag.pop(tag, set()))
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id, mid)
        except Exception:
            # 删除失败忽略（可能用户已删除或过期）
            pass

async def autoclean_on_new_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    在进入新的操作（文本/菜单/指令等）前，自动清理默认临时 UI：
      - pwd    ：交易密码键盘
      - rppwd  ：红包支付密码键盘
      - wdpwd  ：提现密码键盘
    """
    if not update.effective_chat:
        return
    chat_id = update.effective_chat.id
    for tag in ("pwd", "rppwd", "wdpwd"):
        await gc_delete(context, chat_id, tag)

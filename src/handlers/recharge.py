from datetime import datetime, timezone
import math

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from .common import fmt_amount, show_main_menu
from ..services.qrcode_util import make_qr_png_bytes
from ..models import (
    get_wallet,
    get_active_recharge_order,
    create_recharge_order,
    get_recharge_order,
    get_user_balance,
    get_ledger_amount_by_ref,
)
from ..logger import recharge_logger


def _code(s: str) -> str:
    return f"`{s}`"


def _copy_hint() -> str:
    return "  👈 点击复制"


def _left_minutes(expire_at) -> int:
    try:
        if isinstance(expire_at, str):
            # 兼容字符串时间
            try:
                expire_dt = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
            except Exception:
                expire_dt = datetime.strptime(expire_at, "%Y-%m-%d %H:%M:%S")
        else:
            expire_dt = expire_at
        now = datetime.now(expire_dt.tzinfo) if getattr(expire_dt, "tzinfo", None) else datetime.now()
        sec = (expire_dt - now).total_seconds()
        return 0 if sec <= 0 else math.ceil(sec / 60)
    except Exception:
        return 0


async def _get_or_create_order(user_id: int):
    order = await get_active_recharge_order(user_id)
    if order:
        return order
    # 无有效订单 → 基于用户专属地址创建一张 15 分钟
    w = await get_wallet(user_id)
    addr = (w or {}).get("tron_address")
    if not addr:
        raise RuntimeError("用户钱包地址不存在，无法创建充值订单")
    oid = await create_recharge_order(user_id, addr, None, 15)
    return await get_recharge_order(oid)


async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """点【➕ 充值】：弹出二维码+地址/订单号（CODE 样式）+ 刷新按钮"""
    u = update.effective_user
    order = await _get_or_create_order(u.id)

    addr = order["address"]
    odno = order["order_no"]
    expire_at = order["expire_at"]
    left_min = _left_minutes(expire_at)

    # 生成二维码（图片内叠加地址，缩放 50%）
    png = make_qr_png_bytes(addr, scale=0.5, caption=addr)

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_refresh:{order['id']}"),
                InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_menu"),
            ]
        ]
    )

    caption_lines = [
        "🧾 充值订单",
        f"地址：{_code(addr)}{_copy_hint()}",
        f"订单号：{_code(odno)}{_copy_hint()}",
        f"到期时间：{expire_at}（剩余{left_min}分钟）",
        "",
        "充值金额 10U 起，15 分钟内有效，请复制地址或扫描二维码进行充值。",
    ]
    await update.message.reply_photo(
        photo=png,
        caption="\n".join(caption_lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb,
    )


async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 刷新状态 / 返回主菜单"""
    q = update.callback_query
    await q.answer()

    if q.data == "back_to_menu":
        await show_main_menu(q.message.chat_id, context, "已返回主菜单")
        return

    if not q.data.startswith("recharge_refresh:"):
        return

    try:
        oid = int(q.data.split(":")[1])
    except Exception:
        await q.message.reply_text("参数错误，请重新发起充值。")
        await show_main_menu(q.message.chat_id, context)
        return

    order = await get_recharge_order(oid)
    if not order:
        await q.message.reply_text("未找到订单，请重新发起充值。")
        await show_main_menu(q.message.chat_id, context)
        return

    status = order.get("status", "unknown")
    if status == "success":
        # 到账金额：读取 ledger 中该订单的入账总和
        credited = await get_ledger_amount_by_ref("recharge", "recharge_orders", oid)
        user_bal = await get_user_balance(order["user_id"])
        text = (
            "✅ 充值成功！\n"
            f"订单号：{_code(order['order_no'])}{_copy_hint()}\n"
            f"到账金额：{fmt_amount(credited)} USDT\n"
            f"当前余额：{fmt_amount(user_bal)} USDT\n"
        )
        await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        await show_main_menu(q.message.chat_id, context)
        return

    left_min = _left_minutes(order.get("expire_at"))
    await q.message.reply_text(f"当前状态：{status}（剩余 {left_min} 分钟）")
    await show_main_menu(q.message.chat_id, context)

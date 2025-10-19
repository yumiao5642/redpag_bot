from io import BytesIO
from datetime import datetime, timezone
import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..config import MIN_DEPOSIT_USDT
from ..services.qrcode_util import make_qr_png_bytes
from ..services.format import fmt_amount
from ..services.tron import short_addr  # 如后续需要可使用
from ..models import (
    get_active_recharge_order,
    create_recharge_order,
    get_recharge_order,
    get_wallet,
)
from ..db import fetchone
from ..logger import recharge_logger


def _code(s):  # Telegram CODE 样式
    return f"`{s}`"

def _copy_hint():
    return "  👈 点击复制"

def _remain_minutes(expire_at: datetime) -> int:
    now = datetime.now(expire_at.tzinfo) if expire_at and expire_at.tzinfo else datetime.now()
    sec = (expire_at - now).total_seconds() if expire_at else 0
    if sec <= 0:
        return 0
    return math.ceil(sec / 60)

async def _get_active_order_by_user(user_id: int):
    """
    取用户当前未过期 waiting 订单；若无则返回 None
    """
    try:
        # 首选 models 能力
        row = await get_active_recharge_order(user_id)
        if row:
            return row
    except Exception:
        pass

    # 兜底：直接查库（列名根据你的表结构）
    row = await fetchone(
        """
        SELECT * FROM recharge_orders
         WHERE user_id=%s AND status='waiting' AND expire_at>NOW()
         ORDER BY id DESC LIMIT 1
        """,
        (user_id,)
    )
    return row

async def _get_or_create_recharge_order(user_id: int, expire_minutes: int = 15):
    """
    存在未过期 waiting 订单则复用；否则新建
    """
    row = await _get_active_order_by_user(user_id)
    if row:
        return row

    wallet = await get_wallet(user_id)
    tron_addr = (wallet or {}).get("tron_address")
    if not tron_addr:
        raise RuntimeError("该账户尚未生成专属充值地址，请联系管理员初始化钱包。")

    oid = await create_recharge_order(user_id, tron_addr, expected_amount=None, expire_minutes=expire_minutes)
    return await get_recharge_order(oid)

def _decorate_order_for_view(order: dict) -> dict:
    """
    给订单补充展示字段：left_min / expire_text
    """
    if not order:
        return order
    expire_at = order.get("expire_at")
    if isinstance(expire_at, str):
        # 如果你的驱动已转换为 datetime 就不需要此步
        try:
            expire_at = datetime.fromisoformat(expire_at)
        except Exception:
            expire_at = None
    left_min = _remain_minutes(expire_at) if expire_at else 0
    order["left_min"] = left_min
    if expire_at:
        # 简单格式化：YYYY-MM-DD HH:MM
        order["expire_text"] = expire_at.strftime("%Y-%m-%d %H:%M")
    else:
        order["expire_text"] = "已过期"
    return order

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """点【➕ 充值】：弹出二维码+地址/订单号（CODE 样式）+ 刷新按钮"""
    u = update.effective_user

    order = await _get_or_create_recharge_order(u.id, expire_minutes=15)
    order = _decorate_order_for_view(order)

    addr = order["address"]
    odno = order["order_no"]

    # 生成二维码（图片内叠加地址）
    png = make_qr_png_bytes(addr, scale=0.5, caption=addr)
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_refresh:{order['id']}"),
            InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_menu")
        ]]
    )

    caption_lines = [
        "🧾 充值订单",
        f"地址：{_code(addr)}{_copy_hint()}",
        f"订单号：{_code(odno)}{_copy_hint()}",
        f"到期时间：{order['expire_text']}（剩余{order['left_min']}分钟）",
        "",
        f"充值金额 {fmt_amount(MIN_DEPOSIT_USDT)}U 起，15 分钟内有效，请复制地址或扫描二维码进行充值。"
    ]
    await update.message.reply_photo(
        photo=BytesIO(png),
        caption="\n".join(caption_lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 刷新状态 / 返回主菜单"""
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    # 返回主菜单
    if data == "back_to_menu":
        from .common import show_main_menu
        await show_main_menu(q.message.chat_id, context, "已返回主菜单")
        return

    # 刷新状态
    if data.startswith("recharge_refresh:"):
        oid = int(data.split(":")[1])

        order = await get_recharge_order(oid)
        if not order:
            await q.message.reply_text("未找到订单，请重新发起充值。")
            from .common import show_main_menu
            await show_main_menu(q.message.chat_id, context)
            return

        if order["status"] == "success":
            # ✅ 已充值成功：显示到账金额 + 最新余额
            credited = order.get("credited_amount", order.get("amount", 0))
            wallet = await get_wallet(order["user_id"])
            user_bal = float((wallet or {}).get("usdt_trc20_balance", 0.0))

            text = (
                "✅ 充值成功！\n"
                f"订单号：{_code(order['order_no'])}{_copy_hint()}\n"
                f"到账金额：{fmt_amount(credited)} USDT\n"
                f"当前余额：{fmt_amount(user_bal)} USDT\n"
            )
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            from .common import show_main_menu
            await show_main_menu(q.message.chat_id, context)
            return

        # 其它状态：回显剩余时间
        order = _decorate_order_for_view(order)
        await q.message.reply_text(f"当前状态：{order['status']}（剩余 {order['left_min']} 分钟）")
        from .common import show_main_menu
        await show_main_menu(q.message.chat_id, context)

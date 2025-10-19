from io import BytesIO
from datetime import datetime, timedelta, timezone
import math
from ..models import create_recharge_order, get_wallet, get_active_recharge_order, get_recharge_order
from ..logger import recharge_logger
from .common import fmt_amount, show_main_menu
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from ..config import MIN_DEPOSIT_USDT
from ..services.qrcode_util import make_qr_png_bytes
from ..services.format import fmt_amount
from ..services.tron import short_addr  # 若没有就简单切片实现
from ..models import (
    get_active_recharge_order,   # 如你仓库没有，下面 helper 有 fallback
    create_recharge_order,
    get_recharge_order,
    get_wallet,
)
from ..db import fetchone  # 若 models 缺 get_active_recharge_order，会用到


async def create_recharge_order_if_needed(user_id: int, expire_minutes: int = 15):
    """
    如果存在未过期 waiting 订单，则直接复用；
    否则创建一个新的充值订单并返回。
    """
    # 1) 优先走 models 已有能力
    try:
        if get_active_recharge_order:  # type: ignore
            existing = await get_active_recharge_order(user_id)
            if existing:
                return existing
    except Exception:
        pass

    # 2) fallback：直接查库
    row = await fetchone(
        """
        SELECT id
          FROM recharge_orders
         WHERE user_id=%s AND status='waiting' AND expires_at>NOW()
         ORDER BY id DESC LIMIT 1
        """,
        (user_id,),
    )
    if row and row.get("id"):
        return await get_recharge_order(row["id"])

    # 3) 没有可复用订单 -> 创建新订单
    wallet = await get_wallet(user_id)
    tron_addr = (wallet or {}).get("tron_address")
    if not tron_addr:
        raise RuntimeError("该账户尚未生成专属充值地址，请联系管理员初始化钱包。")

    oid = await create_recharge_order(user_id, tron_addr, expected_amount=None, expire_minutes=expire_minutes)
    return await get_recharge_order(oid)

def _remain_minutes(expire_at: datetime) -> int:
    now = datetime.now(expire_at.tzinfo) if expire_at.tzinfo else datetime.now()
    sec = (expire_at - now).total_seconds()
    if sec <= 0:
        return 0
    return math.ceil(sec / 60)


def _code(s):  # Telegram CODE 样式
    return f"`{s}`"

def _copy_hint():
    return "  👈 点击复制"

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """点【➕ 充值】：弹出二维码+地址/订单号（CODE 样式）+ 刷新按钮"""
    u = update.effective_user
    order = await get_recharge_order_by_user(u.id)  # 未过期则返回当前订单
    if not order:
        order = await create_recharge_order_if_needed(u.id)

    addr = order["address"]
    odno = order["order_no"]
    expire_ts = order["expire_at"]  # 服务器返回的时间戳/字符串

    # 生成二维码（图片内已叠加地址）
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
        "充值金额 10U 起，15 分钟内有效，请复制地址或扫描二维码进行充值。"
    ]
    await update.message.reply_photo(
        photo=png,
        caption="\n".join(caption_lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 刷新状态 / 返回主菜单"""
    q = update.callback_query
    await q.answer()

    if q.data == "back_to_menu":
        await show_main_menu(q.message.chat_id, context, "已返回主菜单")
        return

    if q.data.startswith("recharge_refresh:"):
        oid = int(q.data.split(":")[1])
        # 查询状态（你已有的订单读取接口，拿到 status/amount等）
        # 伪代码：
        # order = await get_recharge_order(oid)
        order = await context.bot_data["repo"].get_recharge_order(oid) if "repo" in context.bot_data else None
        # 如果你的项目没有 repo 容器，就按你现有的函数改，比如 get_recharge_order_by_id(oid)

        if not order:
            await q.message.reply_text("未找到订单，请重新发起充值。")
            await show_main_menu(q.message.chat_id, context)
            return

        if order["status"] == "success":
            # ✅ 已充值成功：显示到账金额 + 最新余额
            credited = order.get("credited_amount", order.get("amount", 0))
            user_bal = await get_user_balance(order["user_id"], "USDT-trc20")
            text = (
                "✅ 充值成功！\n"
                f"订单号：{_code(order['order_no'])}{_copy_hint()}\n"
                f"到账金额：{fmt_amount(credited)} USDT\n"
                f"当前余额：{fmt_amount(user_bal)} USDT\n"
            )
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            await show_main_menu(q.message.chat_id, context)
            return

        # 其它状态：回显剩余时间
        left_min = order.get("left_min", 0)
        await q.message.reply_text(f"当前状态：{order['status']}（剩余 {left_min} 分钟）")
        await show_main_menu(q.message.chat_id, context)

from io import BytesIO
from datetime import datetime, timedelta, timezone
import math
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import create_recharge_order, get_wallet, get_active_recharge_order, get_recharge_order
from ..services.qrcode_util import make_qr_png_bytes
from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from .common import fmt_amount

def _remain_minutes(expire_at: datetime) -> int:
    now = datetime.now(expire_at.tzinfo) if expire_at.tzinfo else datetime.now()
    sec = (expire_at - now).total_seconds()
    if sec <= 0:
        return 0
    return math.ceil(sec / 60)

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    addr = wallet.get("tron_address") if wallet else "-"

    # 1) 如果已有未过期 waiting 订单 → 直接复用
    order = await get_active_recharge_order(u.id)
    if order is None:
        order_id = await create_recharge_order(u.id, addr, None, 15)
        order = await get_recharge_order(order_id)

    # 2) 计算到期绝对时间与剩余分钟
    # expire_at 为 datetime（aiomysql DictCursor 默认返回 str 需转换；做兼容）
    expire_at = order.get("expire_at")
    if isinstance(expire_at, str):
        try:
            expire_at = datetime.fromisoformat(expire_at.replace(" ", "T"))
        except Exception:
            # MySQL 默认格式 '%Y-%m-%d %H:%M:%S'
            expire_at = datetime.strptime(order["expire_at"], "%Y-%m-%d %H:%M:%S")
    remain = _remain_minutes(expire_at)

    # 3) 生成二维码
    png_bytes = make_qr_png_bytes(addr)
    bio = BytesIO(png_bytes); bio.name = "addr_qr.png"

    # 4) 文案（显示到期具体时间 + 剩余分钟）
    caption = (
        f"🔌 充值地址（USDT-TRC20）：\n{addr}\n\n"
        f"订单号: {order.get('order_no') or order.get('id')}\n"
        f"创建时间: {order.get('created_at')}\n"
        f"到期时间: {expire_at.strftime('%Y-%m-%d %H:%M')} （剩余 {remain} 分钟）\n\n"
        f"充值金额 {fmt_amount(MIN_DEPOSIT_USDT)} U 起。充值订单 15 分钟内有效，如超时请重新点击充值！"
    )

    # 5) 按钮布局：第一行仅“📋”小按钮；第二行“刷新状态”
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋", callback_data=f"recharge_copy:{order['id']}")],
        [InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_status:{order['id']}")]
    ])

    await update.message.reply_photo(photo=bio, caption=caption, reply_markup=kb)
    recharge_logger.info(f"🧾 用户 {u.id} 使用充值订单 {order['id']}（{order.get('order_no')}），地址 {addr}")

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = q.from_user

    if data.startswith("recharge_copy:"):
        wallet = await get_wallet(u.id)
        addr = wallet.get("tron_address") if wallet else "-"
        await q.answer(text=f"地址：\n{addr}\n（请长按复制）", show_alert=True)
        return

    if data.startswith("recharge_status:"):
        try:
            order_id = int(data.split(":")[1])
        except Exception:
            await q.answer("订单号不合法", show_alert=True); return
        order = await get_recharge_order(order_id)
        if not order:
            await q.answer("订单不存在或已过期", show_alert=True); return
        display = {
            "waiting": "等待用户转账",
            "collecting": "待归集",
            "verifying": "验证中",
            "success": "充值成功",
            "expired": "已过期",
            "failed": "失败",
        }
        # 计算剩余时间
        expire_at = order.get("expire_at")
        if isinstance(expire_at, str):
            try:
                expire_at = datetime.fromisoformat(expire_at.replace(" ", "T"))
            except Exception:
                expire_at = datetime.strptime(order["expire_at"], "%Y-%m-%d %H:%M:%S")
        remain = _remain_minutes(expire_at)
        txt = (f"🔄 订单状态刷新\n"
               f"订单号：{order.get('order_no') or order_id}\n"
               f"当前状态：{display.get(order['status'], order['status'])}\n"
               f"创建时间：{order.get('created_at')}\n"
               f"到期时间：{expire_at.strftime('%Y-%m-%d %H:%M')}（剩余 {remain} 分钟）\n")
        await q.message.reply_text(txt)
        return

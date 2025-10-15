from io import BytesIO
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import create_recharge_order, get_wallet, get_recharge_order
from ..services.qrcode_util import make_qr_png_bytes
from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from datetime import datetime
from .common import fmt_amount

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    addr = wallet.get("tron_address") if wallet else "-"
    order_id = await create_recharge_order(u.id, addr, None, 15)

    # 生成二维码（用 BytesIO 更兼容 telegram-telegram-bot v20）
    png_bytes = make_qr_png_bytes(addr)
    bio = BytesIO(png_bytes); bio.name = "addr_qr.png"
    caption = (
        f"🔌 充值地址（USDT-TRC20）：\n{addr}\n\n"
        f"订单号: {order_id}\n创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n到期时间: 15 分钟后\n\n"
        f"充值金额 {fmt_amount(MIN_DEPOSIT_USDT)} U 起，请复制或扫描二维码进行充值。充值订单 15 分钟内有效，如超时请重新点击充值！"
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("复制地址", callback_data=f"recharge_copy:{order_id}")],
        [InlineKeyboardButton("刷新状态", callback_data=f"recharge_status:{order_id}")]
    ])
    await update.message.reply_photo(photo=bio, caption=caption, reply_markup=kb)
    recharge_logger.info(f"🧾 用户 {u.id} 创建充值订单 {order_id}，地址 {addr}")

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理充值页的两个按钮：复制地址 / 刷新状态"""
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = q.from_user

    if data.startswith("recharge_copy:"):
        # Telegram 无法真正“复制到剪贴板”，这里用弹窗展示 + 再发一条文本
        wallet = await get_wallet(u.id)
        addr = wallet.get("tron_address") if wallet else "-"
        await q.answer(text=f"地址：\n{addr}\n（请长按复制）", show_alert=True)
        await q.message.reply_text(f"📋 充值地址：`{addr}`", parse_mode="Markdown")
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
        txt = (f"🔄 订单状态刷新\n"
               f"订单号：{order_id}\n"
               f"当前状态：{display.get(order['status'], order['status'])}\n"
               f"创建时间：{order['created_at']}\n"
               f"到期时间：{order.get('expire_at')}\n")
        await q.message.reply_text(txt)
        return

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import create_recharge_order, get_wallet
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

    png = make_qr_png_bytes(addr)
    caption = (
        f"🔌 充值地址（USDT-TRC20）：\n{addr}\n\n"
        f"订单号: {order_id}\n创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n到期时间: 15 分钟后\n\n"
        f"充值金额 {fmt_amount(MIN_DEPOSIT_USDT)} U 起，请复制或扫描二维码进行充值。充值订单 15 分钟内有效，如超时请重新点击充值！"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("复制地址", callback_data=f"recharge_copy:{order_id}")],
                               [InlineKeyboardButton("刷新状态", callback_data=f"recharge_status:{order_id}")]])
    await update.message.reply_photo(photo=png, caption=caption, reply_markup=kb)
    recharge_logger.info(f"🧾 用户 {u.id} 创建充值订单 {order_id}，地址 {addr}")


from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputFile
from telegram.ext import ContextTypes
from ..models import create_recharge_order, get_wallet
from ..services.qrcode_util import make_qr_png_bytes
from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from datetime import datetime

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    addr = wallet.get("tron_address") if wallet else "-"
    order_id = await create_recharge_order(u.id, addr, None, 15)

    # 生成二维码
    png = make_qr_png_bytes(addr)
    caption = (
        f"🔌 充值地址（USDT-TRC20）：\n{addr}\n\n"
        f"订单号: {order_id}\n创建时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n到期时间: 15 分钟后\n\n"
        f"充值金额{int(MIN_DEPOSIT_USDT)}U起，请复制或扫描二维码进行充值。充值订单15分钟内有效，如超时请重新点击充值！"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("复制地址", callback_data=f"recharge_copy:{order_id}"),
                                InlineKeyboardButton("刷新状态", callback_data=f"recharge_status:{order_id}")]])
    await update.message.reply_photo(photo=png, caption=caption, reply_markup=kb)
    recharge_logger.info(f"🧾 用户 {u.id} 创建充值订单 {order_id}，地址 {addr}")

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("recharge_copy:"):
        await q.message.reply_text("地址已显示在上方，请长按复制（Telegram 暂不支持一键复制）。")
    elif data.startswith("recharge_status:"):
        await q.message.reply_text("状态查询占位：请稍后由归集程序更新订单状态。")

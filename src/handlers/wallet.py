
from telegram import Update
from telegram.ext import ContextTypes
from ..models import get_wallet
from ..keyboards import WALLET_MENU

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = wallet["usdt_trc20_balance"] if wallet else 0
    addr = wallet.get("tron_address") if wallet else "-"
    text = (
        f"账户ID： {u.id}\n\n"
        f"账户余额：\nUSDT-trc20：{bal}\n"
        f"充值地址（专属）：{addr}\n\n"
        "请选择功能："
    )
    await update.message.reply_text(text, reply_markup=WALLET_MENU)

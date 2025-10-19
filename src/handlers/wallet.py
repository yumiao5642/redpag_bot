from telegram import Update
from telegram.ext import ContextTypes

from ..models import ensure_user, get_wallet
from ..keyboards import WALLET_MENU
from .common import fmt_amount

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.first_name or "", u.last_name or "")

    wallet = await get_wallet(u.id)
    bal = (wallet or {}).get("usdt_trc20_balance", 0.0)
    bal_str = fmt_amount(bal)

    text = (
        f"👛 我的钱包\n"
        f"账户ID：`{u.id}`\n\n"
        f"账户余额：\n"
        f"• USDT-TRC20：*{bal_str}*\n"
    )
    await update.message.reply_markdown(text, reply_markup=WALLET_MENU)

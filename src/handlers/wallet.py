from telegram import Update
from telegram.ext import ContextTypes
from ..models import get_wallet
from ..keyboards import WALLET_MENU
from .common import fmt_amount, show_main_menu


async def show_wallet(update, context):
    u = update.effective_user
    w = await get_wallet(u.id)
    bal = fmt_amount(w.get("usdt_trc20_balance", 0))
    trx = fmt_amount(w.get("trx_balance", 0) if "trx_balance" in w else 0)

    text = (
        f"💼 **我的钱包**\n"
        f"账户ID：{u.id}\n\n"
        f"TRX：{trx}\n"
        f"USDT-trc20：{bal}\n"
        f"PHP：0\n"
    )
    await update.message.reply_markdown(text, reply_markup=WALLET_MENU)
    # 不再展示“充值地址（专属）”

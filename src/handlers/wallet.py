from telegram import Update
from telegram.ext import ContextTypes
from ..models import get_wallet, get_or_create_user, get_user_balance
from ..keyboards import WALLET_MENU
from .common import fmt_amount, show_main_menu


async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = fmt_amount(wallet["usdt_trc20_balance"] if wallet else 0)
    text = (
        f"账户ID： {u.id}\n\n"
        f"账户余额：\nUSDT-trc20：{bal}\n\n"
        "请选择功能："
    )
    await update.message.reply_text(text, reply_markup=WALLET_MENU)


async def my_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = await get_or_create_user(u.id, u.username or "")
    bal = await get_user_balance(u.id)

    lines = [
        "📟 我的钱包",
        f"账户ID：`{u.id}`",
        "",
        "账户余额：",
        f"• USDT-trc20：{fmt_amount(bal)}",
    ]
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    await show_main_menu(update.effective_chat.id, context)

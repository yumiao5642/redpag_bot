from telegram import Update
from telegram.ext import ContextTypes

from ..models import get_wallet
from ..keyboards import WALLET_MENU
from .common import fmt_amount

# 仅保留 show_wallet；移除对 models.get_or_create_user / get_user_balance 的依赖
# 同时按你的要求：取消显示“充值地址（专属）”

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)

    bal = fmt_amount(wallet["usdt_trc20_balance"] if wallet else 0.0)

    # 统一风格、两位小数；取消充值地址行
    text = (
        "📟 我的钱包\n"
        f"账户ID：`{u.id}`\n\n"
        "账户余额：\n"
        f"• USDT-trc20：{bal}\n\n"
        "请选择功能："
    )

    await update.message.reply_text(
        text,
        reply_markup=WALLET_MENU,
        parse_mode="Markdown"
    )

# 若你后续确实需要“我的钱包(my_wallet)”的另一种展示方式，
# 可以用现有模型接口封装一个不依赖 get_or_create_user / get_user_balance 的版本。
# 这里先删除/注释旧的 my_wallet 以避免导入报错。
#
# async def my_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     u = update.effective_user
#     wallet = await get_wallet(u.id)
#     bal = fmt_amount(wallet["usdt_trc20_balance"] if wallet else 0.0)
#     lines = [
#         "📟 我的钱包",
#         f"账户ID：`{u.id}`",
#         "",
#         "账户余额：",
#         f"• USDT-trc20：{bal}",
#     ]
#     await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

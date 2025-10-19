from telegram import Update
from telegram.ext import ContextTypes

from ..models import ensure_user, get_wallet
from ..services.format import fmt_amount  # 若无该工具，直接 f"{x:.2f}"
from ..keyboards import WALLET_MENU
from .common import fmt_amount

# 仅保留 show_wallet；移除对 models.get_or_create_user / get_user_balance 的依赖
# 同时按你的要求：取消显示“充值地址（专属）”

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username or "", u.first_name or "", u.last_name or "")

    wallet = await get_wallet(u.id)
    bal = (wallet or {}).get("usdt_trc20_balance", 0.0)
    bal_str = f"{float(bal):.2f}"

    text = (
        f"👛 我的钱包\n"
        f"账户ID：`{u.id}`\n\n"
        f"账户余额：\n"
        f"• USDT-TRC20：*{bal_str}*\n"
    )
    await update.message.reply_markdown(text)

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

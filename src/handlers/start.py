from telegram import Update
from telegram.ext import ContextTypes
from ..keyboards import MAIN_MENU
from ..handlers.common import ensure_user_and_wallet

WELCOME = (
    "🎉 欢迎使用 *USDT-TRC20 红包机器人* ！\n\n"
    "我可以帮你：\n"
    "• 查看钱包余额、充值/提现、账变明细\n"
    "• 发送红包（随机｜平均｜专属），群内一键领取\n"
    "• 绑定常用地址，快捷提现\n"
    "• 汇率查询 & 地址有效性校验\n"
    "• 设置/修改交易密码\n\n"
    "👇 请选择下方菜单开始体验。"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_and_wallet(update, context)
    await update.message.reply_text(WELCOME, reply_markup=MAIN_MENU, parse_mode="Markdown")

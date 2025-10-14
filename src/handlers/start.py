
from telegram import Update
from telegram.ext import ContextTypes
from ..keyboards import MAIN_MENU
from ..handlers.common import ensure_user_and_wallet

WELCOME = (
    "欢迎使用 USDT-TRC20 红包机器人！\n\n"
    "主菜单：\n"
    "一、我的钱包\n二、汇率查询\n三、地址查询\n四、联系客服\n五、设置密码/修改密码\n\n"
    "请点击下方按钮操作。"
)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_and_wallet(update, context)
    await update.message.reply_text(WELCOME, reply_markup=MAIN_MENU)

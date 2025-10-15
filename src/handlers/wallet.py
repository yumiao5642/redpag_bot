# src/handlers/wallet.py
from telegram import Update
from telegram.ext import ContextTypes
from ..models import get_or_create_user, get_user_balance
from .common import fmt_amount, show_main_menu

async def my_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    user = await get_or_create_user(u.id, u.username or "")
    bal = await get_user_balance(user["id"])
    text = (
        f"👤 账户ID：{user['tg_id']}\n\n"
        f"💰 账户余额：\n"
        f"• USDT-TRC20：{fmt_amount(bal)}"
    )
    await update.message.reply_text(text)
    await show_main_menu(update.effective_chat.id, context)

async def help_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = (
        "欢迎使用 USDT-TRC20 红包机器人：\n"
        "• 我的钱包：余额/资金明细\n"
        "• 充值：生成订单，扫码或复制地址\n"
        "• 提现：绑定常用地址后申请\n"
        "• 红包：随机/平均/专属 类型发送\n"
        "• 设置密码：九宫格输入，资金操作二次校验"
    )
    await update.message.reply_text(txt)
    await show_main_menu(update.effective_chat.id, context)

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import get_wallet, list_user_addresses
from ..config import MIN_WITHDRAW_USDT, WITHDRAW_FEE_FIXED
from ..logger import withdraw_logger
from .common import fmt_amount
from .common import show_main_menu
from ..models import get_flag

if await get_flag("lock_withdraw"):   # withdraw.py
    await update.message.reply_text("⚠️ 维护中..请稍候尝试!")
    await show_main_menu(update.effective_chat.id, context)
    return

# ...
if await get_flag("lock_redpacket"):  # red_packet.py
    await update.message.reply_text("⚠️ 维护中..请稍候尝试!")
    await show_main_menu(update.effective_chat.id, context)
    return


async def show_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = wallet["usdt_trc20_balance"] if wallet else 0.0
    text = (f"账户ID：\n{u.id}\n\nUSDT-trc20 -- 当前余额: {fmt_amount(bal)} U\n"
            f"提示: 最小提款金额: {fmt_amount(MIN_WITHDRAW_USDT)} U\n手续费: 0% + {fmt_amount(WITHDRAW_FEE_FIXED)} U\n")
    if float(bal) < MIN_WITHDRAW_USDT + WITHDRAW_FEE_FIXED:
        text += "\n余额不足提现最低要求!"
        await update.message.reply_text(text); return

    addrs = await list_user_addresses(u.id)
    if not addrs:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("添加地址", callback_data="addr_add_start")]])
        await update.message.reply_text(text + "\n无常用钱包地址,请添加绑定:", reply_markup=kb)
        return

    lines = [text, "\n已添加常用地址："]
    btns = []
    for a in addrs:
        lines.append(f"- {a['alias']}  {a['address']}")
        btns.append([InlineKeyboardButton(f"提到 {a['alias']}", callback_data=f"withdraw_to:{a['id']}")])
    await update.message.reply_text("\n".join(lines), reply_markup=InlineKeyboardMarkup(btns))

async def withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    if data.startswith("withdraw_to:"):
        await q.message.reply_text("提现功能占位：将进行交易密码校验与链上转账，后续完善。")
        withdraw_logger.info(f"📤 提现占位：事件 {data}")

from telegram import Update
from telegram.ext import ContextTypes
from ..consts import LEDGER_TYPE_CN
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
    chat_id = update.effective_chat.id
    await context.bot.send_message(chat_id, text, reply_markup=WALLET_MENU, parse_mode="Markdown")

def _fmt_ledger_table(items):
    # 标题固定，防止“时间”跑行
    lines = ["—— 最近 10 笔账变 ——", "```", "时间       金额        类型        余额        订单号           备注",
             "---------- ---------- ----------- ----------- --------------- ----------------"]
    for it in items:
        t  = str(it["created_at"])[5:16]  # MM-DD HH:MM
        am = f"{it['amount']:+.6f}"
        tp = LEDGER_TYPE_CN.get(it["type"], it["type"])
        af = f"{it['balance_after']:.6f}"
        on = it.get("order_no","")
        rm = (it.get("remark") or "").replace("\n", " ")[:16]
        lines.append(f"{t:<10} {am:>10} {tp:<11} {af:>11} {on:<15} {rm}")
    lines.append("```")
    return "\n".join(lines)

async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    rows = await fetchall(
        "SELECT created_at, type, amount, balance_after, remark, order_no "
        "FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT 10", (u.id,)
    )
    if not rows:
        await update.message.reply_text("暂无账变记录。"); return
    await update.message.reply_text(_fmt_ledger_table(list(reversed(rows))), parse_mode="Markdown")

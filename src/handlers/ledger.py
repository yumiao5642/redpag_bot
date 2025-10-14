
from telegram import Update
from telegram.ext import ContextTypes
from ..models import list_ledger_recent

async def show_ledger(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    rows = await list_ledger_recent(u.id, 10)
    if not rows:
        await update.message.reply_text("暂无账变记录。"); return
    lines = ["最近10笔账变："]
    for r in rows:
        lines.append(f"[{r['created_at']}] {r['change_type']} 金额:{r['amount']} 余额:{r['balance_after']} 备注:{r.get('remark') or ''}")
    await update.message.reply_text("\n".join(lines))

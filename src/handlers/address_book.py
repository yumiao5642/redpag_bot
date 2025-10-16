from telegram import Update
from telegram.ext import ContextTypes

from ..logger import address_logger
from ..models import add_user_address, list_user_addresses
from ..services.tron import is_valid_address

ALIA_MAX = 15

TIPS = (
    '⚠️ 请依照"地址 别名"，两者之间请用空格隔开，添加地址及其别名！ 如 :\n'
    'TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t IM-个人\n\n发送 "列表" 查看已有地址。'
)


async def address_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    if text in ("列表", "list", "查看"):
        rows = await list_user_addresses(update.effective_user.id)
        if not rows:
            await update.message.reply_text("暂无常用地址。\n" + TIPS)
            return
        lines = ["常用地址列表："]
        for r in rows:
            lines.append(f"- {r['alias']}: {r['address']}")
        await update.message.reply_text("\n".join(lines))
        return

    parts = text.split()
    if len(parts) < 2:
        await update.message.reply_text("格式不正确。\n" + TIPS)
        return
    addr, alias = parts[0], " ".join(parts[1:])
    if len(alias) > ALIA_MAX:
        await update.message.reply_text(f"别名过长（>{ALIA_MAX}），请重新输入。")
        return
    if not is_valid_address(addr):
        await update.message.reply_text("TRX 地址格式不正确，请检查后重试。")
        return

    await add_user_address(update.effective_user.id, addr, alias)
    address_logger.info(
        f"📮 用户 {update.effective_user.id} 绑定地址：{addr}（{alias}）"
    )
    await update.message.reply_text('地址绑定成功！发送 "列表" 可查看。')

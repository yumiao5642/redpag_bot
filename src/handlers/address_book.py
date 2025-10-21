# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import add_user_address, list_user_addresses
from ..services.tron import is_valid_address
from ..logger import address_logger
from .common import show_main_menu

ALIA_MAX = 15

def _list_text(rows):
    if not rows:
        return "当前无常用地址。"
    lines = ["常用地址列表："]
    for r in rows:
        lines.append(f"- {r['alias']}  {r['address']}")
    return "\n".join(lines)

def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 添加地址", callback_data="addrbook:add")],
        [InlineKeyboardButton("🗑 删除地址", callback_data="addrbook:del")]
    ])

async def address_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await list_user_addresses(update.effective_user.id)
    await update.message.reply_text(_list_text(rows), reply_markup=_kb())

async def address_kb_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb
    q = update.callback_query
    await q.answer()
    if q.data == "addrbook:add":
        context.user_data["addrbook_waiting"] = True
        await q.message.reply_text(
            "添加地址格式：  `地址 别名`  （空格分隔）\n例如：\n`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t IM-个人`\n\n（点击上面蓝色文字可复制）",
            parse_mode="Markdown",
            reply_markup=cancel_kb("addrbook_add")
        )
    elif q.data == "addrbook:del":
        context.user_data["addrbook_del_waiting"] = True
        await q.message.reply_text("请输入要删除的地址或别名（仅限你自己添加的记录）：", reply_markup=cancel_kb("addrbook_del"))

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 删除流程
    if context.user_data.get("addrbook_del_waiting"):
        from ..models import soft_delete_user_address
        txt = (update.message.text or "").strip()
        context.user_data.pop("addrbook_del_waiting", None)
        if txt in ("取消","cancel","退出"):
            await update.message.reply_text("已取消删除。")
            await show_main_menu(update.effective_chat.id, context)
            return
        n = await soft_delete_user_address(update.effective_user.id, txt)
        if n:
            await update.message.reply_text("已删除。")
        else:
            await update.message.reply_text("未找到匹配的地址/别名。")
        rows = await list_user_addresses(update.effective_user.id)
        await update.message.reply_text(_list_text(rows), reply_markup=_kb())
        await show_main_menu(update.effective_chat.id, context)
        return

    # 添加流程
    if not context.user_data.get("addrbook_waiting"):
        return

    txt = (update.message.text or "").strip()
    if txt in ("取消","cancel","退出"):
        context.user_data.pop("addrbook_waiting", None)
        await update.message.reply_text("已取消添加。")
        await show_main_menu(update.effective_chat.id, context)
        return

    parts = txt.split()
    if len(parts) < 2:
        await update.message.reply_text("格式不正确，请按 “地址 别名” 发送。"); return

    addr, alias = parts[0], " ".join(parts[1:])
    if len(alias) > ALIA_MAX:
        await update.message.reply_text(f"别名过长（>{ALIA_MAX}），请重新输入。"); return
    if not is_valid_address(addr):
        await update.message.reply_text("TRX 地址格式不正确，请检查后重试。"); return

    await add_user_address(update.effective_user.id, addr, alias)
    address_logger.info(f"📮 用户 {update.effective_user.id} 绑定地址：{addr}（{alias}）")
    context.user_data.pop("addrbook_waiting", None)
    rows = await list_user_addresses(update.effective_user.id)
    await update.message.reply_text("地址绑定成功！\n\n" + _list_text(rows), reply_markup=_kb())
    await show_main_menu(update.effective_chat.id, context)

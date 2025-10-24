# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from ..models import add_user_address, list_user_addresses, soft_delete_user_address_by_id
from ..services.tron import is_valid_address
from ..logger import address_logger
from .common import show_main_menu
from ..utils.logfmt import log_user
from ..utils.monofmt import pad as mpad  # ← 新增

ALIA_MAX = 15

def _list_text(rows):
    if not rows:
        return "当前无常用地址。"
    col_addr = 34
    col_alias = 15
    lines = [
        "```已添加常用地址：",
        f"{mpad('地址', col_addr)}  {mpad('别名', col_alias)}"
    ]
    for r in rows:
        addr = (r['address'] or '').strip()
        alias = (r['alias'] or '').strip()
        lines.append(f"{mpad(addr, col_addr)}  {mpad(alias, col_alias)}")
    lines.append("```")
    return "\n".join(lines)

def _kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ 添加地址", callback_data="addrbook:add")],
        [InlineKeyboardButton("🗑 删除地址", callback_data="addrbook:del")]
    ])

def _del_kb(rows):
    """删除地址的按钮列表：每条一个按钮：地址｜别名；点击即删。"""
    if not rows:
        return InlineKeyboardMarkup([[InlineKeyboardButton("返回", callback_data="cancel:addrbook_del")]])
    btns = []
    for r in rows:
        label = f"{r['address']}｜{r['alias']}"
        btns.append([InlineKeyboardButton(label, callback_data=f"addrbook:del:{r['id']}")])
    btns.append([InlineKeyboardButton("取消", callback_data="cancel:addrbook_del")])
    return InlineKeyboardMarkup(btns)

async def address_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rows = await list_user_addresses(update.effective_user.id)
    await update.message.reply_text(_list_text(rows), reply_markup=_kb(), parse_mode=ParseMode.MARKDOWN)

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
        return

    if q.data == "addrbook:del":
        rows = await list_user_addresses(update.effective_user.id)
        if not rows:
            await q.message.reply_text("当前无可删除的地址。", reply_markup=_kb())
            return
        await q.message.reply_text("请选择要删除的地址：", reply_markup=_del_kb(rows))
        return

    if q.data.startswith("addrbook:del:"):
        addr_id = int(q.data.split(":")[2])
        # 先查名称用于回显
        rows = await list_user_addresses(update.effective_user.id)
        target = next((r for r in rows if r["id"] == addr_id), None)
        if not target:
            await q.message.reply_text("未找到该地址或已被删除。", reply_markup=_kb()); return
        n = await soft_delete_user_address_by_id(update.effective_user.id, addr_id)
        if n:
            # 屏蔽中间部分地址
            addr = target["address"]
            masked = (addr[:6] + "***" + addr[-6:]) if len(addr) > 12 else addr
            await q.message.reply_text(f"地址 {masked}｜{target['alias']} 已删除成功。")
            address_logger.info("📮 用户 %s 删除地址：%s（%s）", log_user(update.effective_user), target["address"], target["alias"])
        else:
            await q.message.reply_text("删除失败或记录不存在。")
        rows = await list_user_addresses(update.effective_user.id)
        await q.message.reply_text(_list_text(rows), reply_markup=_kb(), parse_mode=ParseMode.MARKDOWN)
        await show_main_menu(q.message.chat_id, context)
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """仅保留添加流程的文本输入；删除旧的“文本删除流程”"""
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
    address_logger.info(f"📮 用户 {log_user(update.effective_user)} 绑定地址：{addr}（{alias}）")
    context.user_data.pop("addrbook_waiting", None)
    rows = await list_user_addresses(update.effective_user.id)
    await update.message.reply_text("地址绑定成功！\n\n" + _list_text(rows), reply_markup=_kb(), parse_mode=ParseMode.MARKDOWN)
    await show_main_menu(update.effective_chat.id, context)

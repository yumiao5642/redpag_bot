<<<<<<< HEAD
from telegram import Update
from telegram.ext import ContextTypes

from ..config import USDT_CONTRACT
from ..services.tron import (
    get_account_resource,
    get_recent_transfers,
    get_trc20_balance,
    get_trx_balance,
    is_valid_address,
)
from .common import fmt_amount, show_main_menu

=======
# -*- coding: utf-8 -*-
from telegram import Update
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .common import fmt_amount, show_main_menu
from ..services.tron import (
    is_valid_address, get_trx_balance, get_usdt_balance,
    get_account_resource, get_recent_transfers
)
from ..config import USDT_CONTRACT
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)

async def addr_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("请发送要校验的 TRON 地址：")
    context.user_data["addr_query_waiting"] = True

<<<<<<< HEAD

async def addr_query_ontext(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("addr_query_waiting", False):
        return
    addr = (update.message.text or "").strip()
    ok = is_valid_address(addr)
    await update.message.reply_text(
        f"地址 {addr} 校验结果：{'✅有效' if ok else '❌无效'}。\n（链上余额查询后续接入）"
    )


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (update.message.text or "").strip()
    addr = text.split()[0]

    if not is_valid_address(addr):
        await update.message.reply_text("当前仅支持 TRC-20 格式地址，请重新输入")
        await show_main_menu(update.effective_chat.id, context)
        return

    trx = await get_trx_balance(addr)
    usdt = await get_trc20_balance(addr, USDT_CONTRACT)
    res = get_account_resource(addr)
=======
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.pop("addr_query_waiting", False):
        return
    addr = (update.message.text or "").strip()

    if not is_valid_address(addr):
        await update.message.reply_text("当前仅支持TRC-20格式地址,请重新输入")
        await show_main_menu(update.effective_chat.id, context)
        return

    trx = get_trx_balance(addr)
    usdt = await get_usdt_balance(addr)  # 从 USDT_CONTRACT 读取
    res = get_account_resource(addr)     # dict: {'bandwidth': int, 'energy': int}
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
    transfers = await get_recent_transfers(addr, limit=10)

    lines = [
        f"📮 地址：`{addr}`",
        f"TRX：{fmt_amount(trx)}",
        f"USDT：{fmt_amount(usdt)}",
<<<<<<< HEAD
        f"带宽：{res.bandwidth} / 能量：{res.energy}",
        "",
    ]
    if transfers:
        lines.append("🧾 最近 10 笔转账（简要）：")
        for t in transfers:
            direction = "↗️ 收" if t["to"].lower() == addr.lower() else "↘️ 付"
            asset = t.get("asset", "USDT")
            amt = fmt_amount(t["amount"])
            lines.append(f"{direction} {asset} {amt}  {t['hash'][:10]}…")
    else:
        lines.append("（无最近转账）")

    await update.message.reply_markdown("\n".join(lines))
=======
        f"带宽：{res['bandwidth']} / 能量：{res['energy']}",
        ""
    ]
    if transfers:
        lines.append("🧾 最近 10 笔转账：")
        for t in transfers:
            dr = "↗️ 收" if t["to"].lower()==addr.lower() else "↘️ 付"
            asset = t.get("asset","USDT")
            amt = fmt_amount(t["amount"])
            lines.append(f"{dr} {asset} {amt}  {t['hash'][:10]}…")
    else:
        lines.append("（无最近转账）")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.MARKDOWN)
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
    await show_main_menu(update.effective_chat.id, context)

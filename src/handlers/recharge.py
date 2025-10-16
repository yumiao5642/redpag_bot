from datetime import datetime, timedelta
from io import BytesIO
<<<<<<< HEAD

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from ..models import (
    create_recharge_order,
    get_ledger_amount_by_ref,
    get_recharge_order,
    get_user_balance,
    get_wallet,
)
from ..services.qrcode_util import make_qr_png_bytes
from .common import fmt_amount, show_main_menu


def _fmt_code(s: str, tail: str = "👈 点击复制") -> str:
    # Telegram CODE 格式 + 两个空格 + 左指小手 + 点击复制
    return f"`{s}`  👈 {tail}"
=======
from datetime import datetime, timedelta, timezone
import math
from ..models import create_recharge_order, get_wallet, get_active_recharge_order, get_recharge_order
from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from .common import fmt_amount, show_main_menu
from ..services.qrcode_util import make_qr_png_bytes
from ..models import (
    create_recharge_order_if_needed,     # 新增：没有就创建，有且未过期就复用（你若已有名字不同，映射一下）
    get_recharge_order_by_user,          # 查询最近未过期订单
    get_user_balance,
    mark_recharge_refreshed,             # 可选：如果你需要记录刷新动作
)
from ..services.tron import short_addr  # 若没有就简单切片实现
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)



def _code(s):  # Telegram CODE 样式
    return f"`{s}`"

def _copy_hint():
    return "  👈 点击复制"

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
<<<<<<< HEAD
    """点击【充值】——直接弹出二维码“图片查看器”+带说明的 caption。"""
=======
    """点【➕ 充值】：弹出二维码+地址/订单号（CODE 样式）+ 刷新按钮"""
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
    u = update.effective_user
    order = await get_recharge_order_by_user(u.id)  # 未过期则返回当前订单
    if not order:
        order = await create_recharge_order_if_needed(u.id)

<<<<<<< HEAD
    # 若已有未过期订单，复用；否则生成新单（有效期 15 分钟）
    order_id = await create_recharge_order(u.id, addr, None, 15)

    # 二维码：缩小 50%，同时把地址写在图片下方（图上可见）
    caption_text = f"TRX/USDT-trc20 ONLY\n\n{addr}"
    png_bytes = make_qr_png_bytes(addr, scale=0.5, caption=caption_text)
    bio = BytesIO(png_bytes)
    bio.name = "recharge_qr.png"

    expire_at = (datetime.now() + timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")
    human = (
        "⚠️ 充值金额 **{minu} USDT** 起；\n"
        "⏱ 订单到期：{exp}（剩余15分钟）；\n"
        "💡 充值后请耐心等待，到账会自动通知。"
    ).format(minu=fmt_amount(MIN_DEPOSIT_USDT), exp=expire_at)

    # 地址/订单号使用 CODE 样式；地址行末显示“👈 点击复制”
    cap = (
        f"🧾 **充值信息**\n"
        f"收款网络：USDT-TRC20\n\n"
        f"收款地址：{_fmt_code(addr)}\n"
        f"订单号：{_fmt_code(str(order_id))}\n\n"
        f"{human}"
    )

    kb = InlineKeyboardMarkup(
        [  # 按钮在文本下
            [
                InlineKeyboardButton(
                    "📋 复制地址", callback_data=f"recharge_copy:{order_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 刷新状态", callback_data=f"recharge_status:{order_id}"
                )
            ],
            [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_menu")],
        ]
    )

    await update.message.reply_photo(
        photo=bio, caption=cap, reply_markup=kb, parse_mode="Markdown"
    )
    recharge_logger.info(f"🧾 用户 {u.id} 使用充值订单 {order_id}，地址 {addr}")

=======
    addr = order["address"]
    odno = order["order_no"]
    expire_ts = order["expire_at"]  # 服务器返回的时间戳/字符串

    # 生成二维码（图片内已叠加地址）
    png = make_qr_png_bytes(addr, scale=0.5, caption=addr)
    kb = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_refresh:{order['id']}"),
            InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_menu")
        ]]
    )

    caption_lines = [
        "🧾 充值订单",
        f"地址：{_code(addr)}{_copy_hint()}",
        f"订单号：{_code(odno)}{_copy_hint()}",
        f"到期时间：{order['expire_text']}（剩余{order['left_min']}分钟）",
        "",
        "充值金额 10U 起，15 分钟内有效，请复制地址或扫描二维码进行充值。"
    ]
    await update.message.reply_photo(
        photo=png,
        caption="\n".join(caption_lines),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)

async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理 刷新状态 / 返回主菜单"""
    q = update.callback_query
    await q.answer()

<<<<<<< HEAD
    if data == "back_to_menu":
        await q.message.reply_text("已返回主菜单。")
        await show_main_menu(q.message.chat_id, context)
        return

    if data.startswith("recharge_copy:"):
        wallet = await get_wallet(u.id)
        addr = wallet.get("tron_address") if wallet else "-"
        # 弹窗显示，用户可长按复制
        await q.answer(text=addr, show_alert=True)
        return

    if data.startswith("recharge_status:"):
        try:
            oid = int(data.split(":")[1])
        except Exception:
            await q.answer("订单号不合法", show_alert=True)
            return

        order = await get_recharge_order(oid)
        if not order:
            await q.answer("订单不存在或已过期", show_alert=True)
            return

        display = {
            "waiting": "等待用户转账",
            "collecting": "待归集",
            "verifying": "验证中",
            "success": "充值成功",
            "expired": "已过期",
            "failed": "失败",
        }
        st = order["status"]
        lines = [
            f"🧾 订单号：`{order['id']}`",
            f"状态：{display.get(st, st)}",
        ]
        if st == "success":
            # 查询本单充值到账金额（从账变里按 ref 找）
            amt = await get_ledger_amount_by_ref(
                user_id=order["user_id"],
                ref_type="recharge",
                ref_table="recharge_orders",
                ref_id=order["id"],
            )
            bal = await get_user_balance(order["user_id"])
            if amt is not None:
                lines.append(f"到账金额：**{fmt_amount(amt)} USDT**")
            lines.append(f"当前余额：**{fmt_amount(bal)} USDT**")
            lines.append("✅ 充值成功，祝您使用愉快！")

            await q.message.reply_markdown("\n".join(lines))
            # 结束后重现主菜单
            await show_main_menu(q.message.chat_id, context)
            return

        # 其他状态，仅展示文案
        await q.message.reply_markdown("\n".join(lines))
        # 给个返回主菜单
=======
    if q.data == "back_to_menu":
        await show_main_menu(q.message.chat_id, context, "已返回主菜单")
        return

    if q.data.startswith("recharge_refresh:"):
        oid = int(q.data.split(":")[1])
        # 查询状态（你已有的订单读取接口，拿到 status/amount等）
        # 伪代码：
        # order = await get_recharge_order(oid)
        order = await context.bot_data["repo"].get_recharge_order(oid) if "repo" in context.bot_data else None
        # 如果你的项目没有 repo 容器，就按你现有的函数改，比如 get_recharge_order_by_id(oid)

        if not order:
            await q.message.reply_text("未找到订单，请重新发起充值。")
            await show_main_menu(q.message.chat_id, context)
            return

        if order["status"] == "success":
            # ✅ 已充值成功：显示到账金额 + 最新余额
            credited = order.get("credited_amount", order.get("amount", 0))
            user_bal = await get_user_balance(order["user_id"], "USDT-trc20")
            text = (
                "✅ 充值成功！\n"
                f"订单号：{_code(order['order_no'])}{_copy_hint()}\n"
                f"到账金额：{fmt_amount(credited)} USDT\n"
                f"当前余额：{fmt_amount(user_bal)} USDT\n"
            )
            await q.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
            await show_main_menu(q.message.chat_id, context)
            return

        # 其它状态：回显剩余时间
        left_min = order.get("left_min", 0)
        await q.message.reply_text(f"当前状态：{order['status']}（剩余 {left_min} 分钟）")
>>>>>>> 441209c (feat(bot): 充值成功回显到账+余额；主菜单回显；功能锁(红包/提现)；地址查询增强；二维码缩放与CODE复制；仅私聊安全)
        await show_main_menu(q.message.chat_id, context)

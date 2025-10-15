from io import BytesIO
from datetime import datetime, timedelta

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes

from ..config import MIN_DEPOSIT_USDT
from ..logger import recharge_logger
from ..services.qrcode_util import make_qr_png_bytes
from ..services.tron import short_addr
from ..models import (
    get_wallet, create_recharge_order, get_recharge_order,
    get_ledger_amount_by_ref, get_user_balance,
)
from .common import fmt_amount, show_main_menu


def _fmt_code(s: str, tail: str = "👈 点击复制") -> str:
    # Telegram CODE 格式 + 两个空格 + 左指小手 + 点击复制
    return f"`{s}`  👈 {tail}"


async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """点击【充值】——直接弹出二维码“图片查看器”+带说明的 caption。"""
    u = update.effective_user
    wallet = await get_wallet(u.id)
    addr = wallet.get("tron_address") if wallet else "-"

    # 若已有未过期订单，复用；否则生成新单（有效期 15 分钟）
    order_id = await create_recharge_order(u.id, addr, None, 15)

    # 二维码：缩小 50%，同时把地址写在图片下方（图上可见）
    caption_text = f"TRX/USDT-trc20 ONLY\n\n{addr}"
    png_bytes = make_qr_png_bytes(addr, scale=0.5, caption=caption_text)
    bio = BytesIO(png_bytes); bio.name = "recharge_qr.png"

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

    kb = InlineKeyboardMarkup([  # 按钮在文本下
        [InlineKeyboardButton("📋 复制地址", callback_data=f"recharge_copy:{order_id}")],
        [InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_status:{order_id}")],
        [InlineKeyboardButton("⬅️ 返回主菜单", callback_data="back_to_menu")]
    ])

    await update.message.reply_photo(photo=bio, caption=cap, reply_markup=kb, parse_mode="Markdown")
    recharge_logger.info(f"🧾 用户 {u.id} 使用充值订单 {order_id}，地址 {addr}")


async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = q.from_user

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
            await q.answer("订单号不合法", show_alert=True); return

        order = await get_recharge_order(oid)
        if not order:
            await q.answer("订单不存在或已过期", show_alert=True); return

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
            amt = await get_ledger_amount_by_ref(user_id=order["user_id"],
                                                ref_type="recharge",
                                                ref_table="recharge_orders",
                                                ref_id=order["id"])
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
        await show_main_menu(q.message.chat_id, context)

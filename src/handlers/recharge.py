# -*- coding: utf-8 -*-
from io import BytesIO
from datetime import datetime
import math
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
from telegram.error import BadRequest

from ..config import MIN_DEPOSIT_USDT
from ..services.qrcode_util import make_qr_png_bytes
from ..services.format import fmt_amount
from ..models import (
    get_active_recharge_order,
    create_recharge_order,
    get_recharge_order,
    get_wallet,
    get_ledger_by_ref,
)
from ..db import fetchone

async def _safe_edit_caption(msg, new_caption: str, kb):
    try:
        # 如果内容完全一致就不再发起编辑（避免 BadRequest）
        if (msg.caption or "").strip() == new_caption.strip():
            return
        await msg.edit_caption(new_caption, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    except BadRequest as e:
        if "Message is not modified" in str(e):
            return
        raise

def _code(s):  # Telegram CODE 样式
    return f"`{s}`"

def _copy_hint():
    return "  👈 点击复制"

def _remain_minutes(expire_at: datetime) -> int:
    now = datetime.now(expire_at.tzinfo) if expire_at and getattr(expire_at, "tzinfo", None) else datetime.now()
    sec = (expire_at - now).total_seconds() if expire_at else 0
    if sec <= 0:
        return 0
    return math.ceil(sec / 60)

def _cn_status(s: str) -> str:
    mapping = {
        "waiting": "等待用户转账",
        "collecting": "归集中",
        "verifying": "待验证",
        "success": "充值成功",
        "expired": "已超时",
        "failed": "失败",
    }
    return mapping.get(s, s or "-")

async def _get_active_order_by_user(user_id: int):
    try:
        row = await get_active_recharge_order(user_id)
        if row:
            return row
    except Exception:
        pass
    return await fetchone(
        "SELECT * FROM recharge_orders WHERE user_id=%s AND status='waiting' AND expire_at>NOW() ORDER BY id DESC LIMIT 1",
        (user_id,)
    )

def _decorate_order_for_view(order: dict) -> dict:
    if not order:
        return order
    expire_at = order.get("expire_at")
    created_at = order.get("created_at")

    def _as_dt(x):
        if isinstance(x, datetime):
            return x
        try:
            # 兼容 MySQL 字符串时间戳
            return datetime.fromisoformat(str(x).replace("Z","").split(".")[0])
        except Exception:
            return None

    expire_at = _as_dt(expire_at)
    created_at = _as_dt(created_at)

    order["left_min"] = _remain_minutes(expire_at) if expire_at else 0
    order["expire_text"] = expire_at.strftime("%Y-%m-%d %H:%M") if expire_at else "—"
    order["created_text"] = created_at.strftime("%Y-%m-%d %H:%M") if created_at else "—"
    order["status_cn"] = _cn_status(order.get("status", ""))
    return order

def _caption_for_order(order: dict, show_success_append: bool = False, user_bal: float = 0.0, credited: float = 0.0) -> str:
    addr = order["address"]
    odno = order["order_no"]
    lines = [
        "🧾 充值订单",
        f"地址：{_code(addr)}{_copy_hint()}",
        f"订单号：{_code(odno)}{_copy_hint()}",
        f"创建时间：{order['created_text']}",
        f"到期时间：{order['expire_text']}（剩余{order['left_min']}分钟）",
        f"当前状态：{order['status_cn']}",
        "",
        f"充值金额 {fmt_amount(MIN_DEPOSIT_USDT)}U 起，15 分钟内有效，请复制地址或扫描二维码进行充值。"
    ]
    if show_success_append:
        lines.append("")
        lines.append(f"✅ 到账金额：{fmt_amount(credited)} USDT")
        lines.append(f"💼 当前余额：{fmt_amount(user_bal)} USDT")
    return "\n".join(lines)

async def show_recharge(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    order = await _get_active_order_by_user(u.id) or await get_recharge_order(
        await create_recharge_order(u.id, (await get_wallet(u.id))["tron_address"], None, 15)
    )
    order = _decorate_order_for_view(order)

    addr = order["address"]
    # 生成二维码（图片内叠加地址）
    png = make_qr_png_bytes(addr, scale=0.5, caption=addr)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_refresh:{order['id']}")]])

    await update.message.reply_photo(
        photo=BytesIO(png),
        caption=_caption_for_order(order),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=kb
    )

# --- src/handlers/recharge.py 中替换 recharge_callback ---
async def recharge_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data.startswith("recharge_refresh:"):
        oid = int(data.split(":")[1])
        order = await get_recharge_order(oid)
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔄 刷新状态", callback_data=f"recharge_refresh:{oid}")]])

        if not order:
            await _safe_edit_caption(q.message, "未找到订单，请重新发起充值。", kb)
            return

        order = _decorate_order_for_view(order)

        if order["status"] == "success":
            lg = await get_ledger_by_ref("recharge", "recharge_orders", oid)
            wallet = await get_wallet(order["user_id"])
            credited = float(lg["amount"]) if lg else 0.0
            user_bal = float((wallet or {}).get("usdt_trc20_balance", 0.0))
            new_caption = _caption_for_order(order, show_success_append=True, user_bal=user_bal, credited=credited)
            await _safe_edit_caption(q.message, new_caption, kb)
            return

        new_caption = _caption_for_order(order)
        await _safe_edit_caption(q.message, new_caption, kb)
        return

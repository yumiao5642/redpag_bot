from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from ..models import (
    list_red_packets, create_red_packet, get_red_packet, save_red_packet_share,
    list_red_packet_shares, claim_share, add_red_packet_claim, count_claimed,
    set_red_packet_status, get_wallet, update_wallet_balance, add_ledger, execute
)
from ..keyboards import redpacket_inline_menu, redpacket_create_menu
from ..services.redalgo import split_random, split_average
from ..logger import redpacket_logger
from ..handlers.common import ensure_user_and_wallet, fmt_amount

def _fmt_rp(r):
    return f"ID:{r['id']} | 类型:{r['type']} | 数量:{r['count']} | 总额:{fmt_amount(r['total_amount'])} | 状态:{r['status']}"

async def show_red_packets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_and_wallet(update, context)
    u = update.effective_user
    recs = await list_red_packets(u.id, 10)
    lines = ["🧧 最近红包记录（最多10条）："]
    if recs:
        lines += [_fmt_rp(r) for r in recs]
    else:
        lines.append("（暂无）")
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("根据ID查看详情", callback_data="rp_query:ask")],
                               [InlineKeyboardButton("➕ 创建红包", callback_data="rp_new")]])
    await update.message.reply_text("\n".join(lines), reply_markup=kb)

async def rp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user

    if data == "rp_new":
        rp_id = await create_red_packet(u.id, "random", 1.0, 1, None, None, None)
        await q.message.reply_text(
            _compose_create_text("random", 1, 1.0, cover=None),
            reply_markup=redpacket_create_menu(rp_id, "random")
        )
        return

    if data.startswith("rp_type:"):
        _, rp_id_str, new_type = data.split(":")
        rp_id = int(rp_id_str)
        await execute("UPDATE red_packets SET type=%s, exclusive_user_id=IF(%s='exclusive',exclusive_user_id,NULL) WHERE id=%s",
                      (new_type, new_type, rp_id))
        r = await get_red_packet(rp_id)
        await q.message.reply_text(
            _compose_create_text(r["type"], r["count"], r["total_amount"], r.get("cover_text")),
            reply_markup=redpacket_create_menu(rp_id, r["type"])
        )
        return

    if data.startswith("rp_query:ask"):
        context.user_data["rp_query_waiting"] = True
        await q.message.reply_text("请输入红包ID：")
        return

    if data.startswith("rp_detail:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        shares = await list_red_packet_shares(rp_id)
        claimed = sum(1 for s in shares if s["claimed_by"]) if shares else 0
        await q.message.reply_text(
            f"🧧 红包详情\nID:{r['id']}\n类型:{r['type']}\n币种:{r['currency']}\n数量:{r['count']}\n金额:{fmt_amount(r['total_amount'])}\n封面:{r.get('cover_text') or '未设置'}\n专属:{r.get('exclusive_user_id') or '无'}\n状态:{r['status']}\n已领:{claimed}/{r['count']}"
        )
        return

    if data.startswith("rp_set_count:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("count", rp_id)
        await q.message.reply_text("请输入红包数量（整数）：")
        return

    if data.startswith("rp_set_amount:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("amount", rp_id)
        await q.message.reply_text("请输入红包总金额（USDT，支持小数）：")
        return

    if data.startswith("rp_set_exclusive:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("exclusive", rp_id)
        await q.message.reply_text(
            "🧧 发送红包\n\n👩‍💻 确认专属红包领取人!\n请使用以下任意一种方式选择目标:\nA、 转发对方任意一条文字消息到这里来.\nB、 发送对方的账户ID，如：588726829\nC、 发送对方的用户名，如：@username"
        )
        return

    if data.startswith("rp_set_cover:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("cover", rp_id)
        await q.message.reply_text("✍️ 设置封面\n👩‍💻 请发送一段文字（≤150字符）或图片作为红包的封面。")
        return

    if data.startswith("rp_pay:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        if r["type"] == "exclusive" and not r.get("exclusive_user_id"):
            await q.message.reply_text("专属红包必须设置专属对象，无法支付！"); return

        wallet = await get_wallet(u.id)
        bal = Decimal(str(wallet["usdt_trc20_balance"])) if wallet else Decimal("0")
        total = Decimal(str(r["total_amount"]))
        if bal < total:
            await q.message.reply_text("余额不足，无法支付！请先充值。"); return

        new_bal = bal - total
        await update_wallet_balance(u.id, float(new_bal))
        await add_ledger(u.id, "redpacket_send", -float(total), float(bal), float(new_bal), "red_packets", rp_id, "发送红包扣款")

        if r["type"] == "random":
            shares = split_random(float(total), int(r["count"]))
        else:
            shares = split_average(float(total), int(r["count"]))
        for i, s in enumerate(shares, 1):
            await save_red_packet_share(rp_id, i, float(s))

        await set_red_packet_status(rp_id, "paid")

        cover = r.get("cover_text") or "封面未设置"
        type_cn = '随机' if r['type']=='random' else ('平均' if r['type']=='average' else '专属')
        await q.message.reply_text(
            f"🧧 发送红包\n\n{cover}\n\n--- ☝️ 红包封面 ☝️ ---\n\n类型：[{type_cn}]（下方可切换）\n币种：USDT-trc20\n数量：{r['count']}\n金额：{fmt_amount(r['total_amount'])}\n\n提示：未领取的将在24小时后退款。",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🧧 立即领取", callback_data=f"rp_claim:{rp_id}")],
                                               [InlineKeyboardButton("查看详情", callback_data=f"rp_detail:{rp_id}")]])
        )
        await set_red_packet_status(rp_id, "sent")
        return

    if data.startswith("rp_claim:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r or r["status"] not in ("sent","paid"):
            await q.message.reply_text("红包不可领取或不存在。"); return
        if r["type"] == "exclusive" and r.get("exclusive_user_id") != update.effective_user.id:
            await q.message.reply_text("你不是我的宝贝,你不能领取!"); return

        share = await claim_share(rp_id, update.effective_user.id)
        if not share:
            await q.message.reply_text("红包已领完。"); return

        amt = Decimal(str(share["amount"]))
        wallet = await get_wallet(update.effective_user.id)
        before = Decimal(str(wallet["usdt_trc20_balance"])) if wallet else Decimal("0")
        after = before + amt
        await update_wallet_balance(update.effective_user.id, float(after))
        await add_ledger(update.effective_user.id, "redpacket_claim", float(amt), float(before), float(after), "red_packets", rp_id, "领取红包入账")
        try:
            await context.bot.send_message(chat_id=update.effective_user.id, text=f"红包到账：+{fmt_amount(amt)} USDT-trc20，已入账余额。")
        except Exception:
            pass
        await q.message.reply_text(f"领取成功，金额：{fmt_amount(amt)} USDT-trc20！")

        claimed = await count_claimed(rp_id)
        if claimed >= int(r["count"]):
            await set_red_packet_status(rp_id, "finished")
        return

async def on_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "await_field" not in context.user_data:
        return
    field, rp_id = context.user_data.pop("await_field")
    text = update.message.text or ""

    r = await get_red_packet(rp_id)
    if not r:
        await update.message.reply_text("红包不存在。"); return

    curr_type = r["type"]
    curr_count = r["count"]
    curr_amount = r["total_amount"]
    cover = r.get("cover_text") or "未设置"

    if field == "count":
        try:
            n = int(text.strip())
            if n <= 0 or n > 1000:
                raise ValueError
            await execute("UPDATE red_packets SET count=%s WHERE id=%s", (n, rp_id))
            curr_count = n
        except Exception:
            await update.message.reply_text("数量无效，请输入正整数（≤1000）。"); return

    elif field == "amount":
        try:
            v = float(text.strip())
            if v <= 0:
                raise ValueError
            await execute("UPDATE red_packets SET total_amount=%s WHERE id=%s", (v, rp_id))
            curr_amount = v
        except Exception:
            await update.message.reply_text("金额无效，请输入正数。"); return

    elif field == "exclusive":
        target_id = None
        if update.message.forward_from:
            target_id = update.message.forward_from.id
        else:
            s = text.strip()
            if s.startswith("@"):
                await update.message.reply_text("已记录用户名（若无法解析 ID，请对方先私聊本机器人以建立映射）。")
                await execute("UPDATE red_packets SET cover_text=CONCAT(COALESCE(cover_text,''),'（专属@', %s, '）') WHERE id=%s", (s[1:], rp_id))
            else:
                try:
                    target_id = int(s)
                except Exception:
                    target_id = None
        if target_id:
            await execute("UPDATE red_packets SET exclusive_user_id=%s, type='exclusive' WHERE id=%s", (target_id, rp_id))
            curr_type = "exclusive"

    elif field == "cover":
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await execute("UPDATE red_packets SET cover_image_file_id=%s WHERE id=%s", (file_id, rp_id))
            cover = "[图片封面]"
        else:
            s = text.strip()
            if len(s) > 150:
                await update.message.reply_text("文字封面最多150字符，请重试。"); return
            await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (s, rp_id))
            cover = s or "未设置"

    await update.message.reply_text(
        _compose_create_text(curr_type, curr_count, curr_amount, cover=cover if cover!='未设置' else None),
        reply_markup=redpacket_create_menu(rp_id, curr_type)
    )

def _compose_create_text(rp_type: str, count: int, amount: float, cover=None) -> str:
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(rp_type, "随机")
    cover_line = cover if cover else "封面未设置"
    return (f"🧧 发送红包\n\n{cover_line}\n\n--- ☝️ 红包封面 ☝️ ---\n\n"
            f"类型：[{type_cn}]（下方可切换：随机｜平均｜专属）\n"
            f"币种：USDT-trc20\n数量：{count}\n金额：{fmt_amount(amount)}\n\n"
            "提示：未领取的将在24小时后退款。")

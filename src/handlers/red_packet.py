from decimal import Decimal
from telegram import InlineQueryResultArticle, InputTextMessageContent
from uuid import uuid4
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from ..keyboards import redpacket_inline_menu, redpacket_create_menu
from ..services.redalgo import split_random, split_average
from ..logger import redpacket_logger
from ..handlers.common import ensure_user_and_wallet
from ..services.format import fmt_amount
from ..models import get_flag
from .common import show_main_menu
from ..services.encryption import verify_password
from datetime import datetime
import random
from typing import Optional
from ..services.format import fmt_amount
from ..models import (
    list_red_packets, create_red_packet, get_red_packet, save_red_packet_share,
    list_red_packet_shares, claim_share, add_red_packet_claim, count_claimed,
    set_red_packet_status, get_wallet, update_wallet_balance, add_ledger, execute,
    get_tx_password_hash, has_tx_password, list_ledger_recent, get_flag
)
from . import wallet as h_wallet
from . import password as h_password


# 全局常量键盘（提升响应）
_RPPWD_KBD = InlineKeyboardMarkup([
    [InlineKeyboardButton("0", callback_data="rppwd:0"),
     InlineKeyboardButton("5", callback_data="rppwd:5"),
     InlineKeyboardButton("4", callback_data="rppwd:4")],
    [InlineKeyboardButton("2", callback_data="rppwd:2"),
     InlineKeyboardButton("8", callback_data="rppwd:8"),
     InlineKeyboardButton("7", callback_data="rppwd:7")],
    [InlineKeyboardButton("9", callback_data="rppwd:9"),
     InlineKeyboardButton("1", callback_data="rppwd:1"),
     InlineKeyboardButton("6", callback_data="rppwd:6")],
    [InlineKeyboardButton("取消", callback_data="rppwd:CANCEL"),
     InlineKeyboardButton("3", callback_data="rppwd:3"),
     InlineKeyboardButton("👁", callback_data="rppwd:TOGGLE")],
    [InlineKeyboardButton("⌫ 退格", callback_data="rppwd:BK")]
])

# --- NEW: 简单的 Markdown 安全化（适配 Telegram Markdown） ---
def _md_safe(s: str) -> str:
    if not s:
        return ""
    # 去掉容易破坏 Markdown 的字符
    for ch in ("`", "*", "_", "[", "]", "(", ")", "~", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
        s = s.replace(ch, "")
    return s

def _safe_name(s: str) -> str:
    return _md_safe(s or "")

# --- REPLACE: 红包支付数字键盘：每日随机布局 ---
from datetime import date
import random

def _pwd_kbd():
    today = date.today().isoformat()
    rnd = random.Random(today)  # 同一天固定，同日不同会话一致
    digits = [str(i) for i in range(10)]
    rnd.shuffle(digits)

    # 9 个数字放 3 行，每行 3 个；第 10 个数字放到第 4 行中间。
    grid = [digits[:3], digits[3:6], digits[6:9]]
    last = digits[9]

    rows = []
    for row in grid:
        rows.append([InlineKeyboardButton(row[0], callback_data=f"rppwd:{row[0]}"),
                     InlineKeyboardButton(row[1], callback_data=f"rppwd:{row[1]}"),
                     InlineKeyboardButton(row[2], callback_data=f"rppwd:{row[2]}")])
    rows.append([
        InlineKeyboardButton("取消", callback_data="rppwd:CANCEL"),
        InlineKeyboardButton(last, callback_data=f"rppwd:{last}"),
        InlineKeyboardButton("👁", callback_data="rppwd:TOGGLE")
    ])
    rows.append([InlineKeyboardButton("⌫ 退格", callback_data="rppwd:BK")])
    return InlineKeyboardMarkup(rows)

def _pwd_mask(s: str, vis: bool) -> str:
    return (s if vis else "•"*len(s)).ljust(4, "_")

def _pwd_render(buf: str, vis: bool) -> str:
    return f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(buf, vis)}"

def _name_code_from_user_row(u: dict, fallback_id: int) -> str:
    # 仅显示“昵称”（优先 display_name，其次 first_name+last_name），不使用 @username，不使用反引号
    if not u:
        return f"ID {fallback_id}"
    disp = (u.get("display_name") or ((u.get("first_name") or "") + (u.get("last_name") or ""))).strip()
    return _safe_name(disp or f"ID {fallback_id}")

async def _build_default_cover(rp_type: str, owner_id: int, exclusive_uid: Optional[int]) -> str:
    from ..models import get_user
    owner = await get_user(owner_id)
    def _name(u, uid):
        disp = (u.get("display_name") or ((u.get("first_name") or "") + (u.get("last_name") or ""))).strip() if u else ""
        return disp or f"ID {uid}"
    owner_link = f"[{_name(owner, owner_id)}](tg://user?id={owner_id})"
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(rp_type, "随机")
    type_blue = f"[【{type_cn}】](https://t.me/)"  # 让类型也呈蓝色
    if rp_type == "exclusive" and exclusive_uid:
        to = await get_user(exclusive_uid)
        to_link = f"[{_name(to, exclusive_uid)}](tg://user?id={exclusive_uid})"
        return f"来自{owner_link}送给{to_link}的{type_blue}红包。"
    return f"来自{owner_link}的{type_blue}红包"

async def rppwd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """红包支付：数字键盘回调"""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("rppwd_flow")
    if not st:
        try:
            await q.message.edit_text("会话已过期，请重新点击“确认支付”。")
        except BadRequest:
            pass
        return

    def _safe_edit(txt: str):
        try:
            if (q.message.text or "").strip() == txt.strip():
                return
            return q.edit_message_text(txt, reply_markup=_RPPWD_KBD)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

    key = q.data.split(":", 1)[1]
    if key == "CANCEL":
        context.user_data.pop("rppwd_flow", None)
        try:
            await q.message.edit_text("已取消。")
        except BadRequest:
            pass
        redpacket_logger.info("🧧 支付取消：用户=%s", update.effective_user.id)
        return
    if key == "TOGGLE":
        st["vis"] = not st["vis"]; await _safe_edit(_pwd_render(st["buf"], st["vis"])); return
    if key == "BK":
        st["buf"] = st["buf"][:-1]; await _safe_edit(_pwd_render(st["buf"], st["vis"])); return

    if key.isdigit() and len(key) == 1:
        if len(st["buf"]) >= 4:
            await _safe_edit(_pwd_render(st["buf"], st["vis"])); return
        st["buf"] += key
        await _safe_edit(_pwd_render(st["buf"], st["vis"]))
        if len(st["buf"]) == 4:
            rp_id = st["rp_id"]
            hp = await get_tx_password_hash(update.effective_user.id)
            if not hp or not verify_password(st["buf"], hp):
                st["buf"] = ""
                await _safe_edit("密码不正确，请重试。\n\n" + _pwd_render(st["buf"], st["vis"]))
                redpacket_logger.info("🧧 支付验密失败：用户=%s，红包ID=%s", update.effective_user.id, rp_id)
                return

            r = await get_red_packet(rp_id)
            if not r:
                context.user_data.pop("rppwd_flow", None)
                try: await q.message.edit_text("红包不存在或已删除。")
                except BadRequest: pass
                redpacket_logger.info("🧧 支付失败：红包不存在，用户=%s，红包ID=%s", update.effective_user.id, rp_id)
                return

            from decimal import Decimal
            wallet = await get_wallet(update.effective_user.id)
            bal = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
            frozen = Decimal(str((wallet or {}).get("usdt_trc20_frozen", 0) or 0))
            avail = bal - frozen
            total = Decimal(str(r["total_amount"]))
            if avail < total:
                context.user_data.pop("rppwd_flow", None)
                try:
                    await q.message.edit_text("余额不足（可用余额不足），无法支付！请先充值或等待提现完成。")
                except BadRequest:
                    pass
                redpacket_logger.info("🧧 支付失败：余额不足，用户=%s，红包ID=%s，总额=%.6f，可用=%.6f",
                                      update.effective_user.id, rp_id, float(total), float(avail))
                return

            # 扣款 & 记账 & 生成 share
            new_bal = bal - total
            await update_wallet_balance(update.effective_user.id, float(new_bal))
            await add_ledger(update.effective_user.id, "redpacket_send", -float(total), float(bal), float(new_bal), "red_packets", rp_id, "发送红包扣款")
            shares = split_random(float(total), int(r["count"])) if r["type"] == "random" else split_average(float(total), int(r["count"]))
            for i, s in enumerate(shares, 1):
                await save_red_packet_share(rp_id, i, float(s))
            await set_red_packet_status(rp_id, "paid")
            redpacket_logger.info("🧧 支付成功：用户=%s，红包ID=%s，类型=%s，份数=%s，总额=%.6f，余额变更：%.6f -> %.6f",
                                  update.effective_user.id, rp_id, r["type"], r["count"], float(total), float(bal), float(new_bal))
            context.user_data.pop("rppwd_flow", None)

            # 展示“成功详情 + 转发按钮”
            type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(r["type"], r["type"])
            exp_text = "-"
            if r.get("expires_at"):
                try:
                    from datetime import datetime
                    exp_text = str(r["expires_at"]).replace("T"," ")[:16]
                except Exception:
                    pass
            detail = (
                "✅ 支付成功！\n"
                f"编号：{rp_id}\n"
                f"类型：{type_cn}\n"
                f"总金额：{fmt_amount(total)} USDT\n"
                f"份数：{r['count']}\n"
                f"有效期至：{exp_text}\n\n"
                "点击下方按钮，选择群或联系人转发领取卡片。"
            )
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{rp_id}")],
                                       [InlineKeyboardButton("查看详情", callback_data=f"rp_detail:{rp_id}")]])
            try:
                await q.message.edit_text(detail, reply_markup=kb)
            except BadRequest as e:
                if "Message is not modified" not in str(e):
                    raise
            return

def _fmt_time(x) -> str:
    if isinstance(x, datetime):
        return x.strftime("%m-%d %H:%M")
    try:
        return datetime.fromisoformat(str(x).replace("Z","").split(".")[0]).strftime("%m-%d %H:%M")
    except Exception:
        return "-"

def _rp_brief_btn_label(r: dict) -> str:
    # 显示按钮文案：ID 12 | 10-20 19:22
    return f"ID {r['id']} | {_fmt_time(r.get('created_at'))}"

async def _guard_redpkt(update, context) -> bool:
    try:
        if (await get_flag("lock_redpkt")) == "1":
            await update.effective_chat.send_message("维护中..请稍候尝试!")
            await show_main_menu(update.effective_chat.id, context)
            return True
    except Exception:
        pass
    return False

def _fmt_rp(r):
    return f"ID:{r['id']} | 类型:{r['type']} | 数量:{r['count']} | 总额:{fmt_amount(r['total_amount'])} | 状态:{r['status']}"

async def show_red_packets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_and_wallet(update, context)
    u = update.effective_user

    from ..models import list_red_packets
    recs = await list_red_packets(u.id, 10)

    lines = ["🧧 最近创建的 10 笔："]
    tbl = ["时间｜类型｜金额｜个数｜状态"]
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}
    if recs:
        for r in recs:
            t = "-"
            if r.get("created_at"):
                try: t = str(r["created_at"])[:16]
                except Exception: pass
            st = r.get("status") or "-"
            run = "使用中" if st in ("created","paid","sent") else "已结束"
            tbl.append(f"{t}｜{type_cn.get(r['type'], r['type'])}｜{fmt_amount(r['total_amount'])}｜{r['count']}｜{run}")
        lines.append("```" + "\n".join(tbl) + "```")
    else:
        lines.append("```无记录```")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("回收使用中红包", callback_data="rp_refund_all")],
        [InlineKeyboardButton("➕ 创建红包", callback_data="rp_new")]
    ])
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")

    redpacket_logger.info("🧧 打开红包页：用户=%s，最近记录数=%s", u.id, len(recs))

async def _render_claim_panel(r: dict) -> tuple[str, InlineKeyboardMarkup]:
    from ..models import list_red_packet_top_claims, count_claimed
    from ..services.format import fmt_amount

    cover = r.get("cover_text") or "封面未设置"
    cover = _md_safe(cover)
    lines = ["🧧 发送红包", "", cover, "", "--- ☝️ 红包封面 ☝️ ---", ""]

    tops = await list_red_packet_top_claims(r["id"], 10)
    if tops:
        tbl = ["ID | 用户 | 金额 | 时间"]
        for i, it in enumerate(tops, 1):
            disp = (it.get("display_name") or ((it.get("first_name") or "") + (it.get("last_name") or ""))).strip()
            who = _safe_name(disp or ('ID ' + str(it.get('claimed_by') or '')))
            tm = "-"
            if it.get("claimed_at"):
                try: tm = str(it["claimed_at"])[11:16]
                except Exception: pass
            tbl.append(f"{i} | {who} | {fmt_amount(it['amount'])} | {tm}")
        lines.append("```" + "\n".join(tbl) + "```")
    else:
        lines.append("```未领取```")

    claimed = await count_claimed(r["id"])
    remain = int(r["count"]) - int(claimed)

    # ⚠️ 这里修复 Markdown 报错：把 @redpag_bot 的下划线转义
    BOT_AT = "@redpag\\_bot"

    if remain <= 0:
        lines.append("\n已抢完")
        lines.append(f"提款👉 {BOT_AT}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("我的钱包", callback_data="rp_go_wallet")]])
    else:
        lines.append(f"\n{remain}/{r['count']}")
        lines.append(f"提款👉 {BOT_AT}")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🧧 立即领取", callback_data=f"rp_claim:{r['id']}")],
                                   [InlineKeyboardButton("我的钱包", callback_data="rp_go_wallet")]])

    return ("\n".join(lines), kb)

async def _update_claim_panel(bot, rp_id: int):
    from ..models import get_red_packet
    r = await get_red_packet(rp_id)
    if not r or not r.get("chat_id") or not r.get("message_id"):
        return
    text, kb = await _render_claim_panel(r)
    try:
        await bot.edit_message_text(
            chat_id=r["chat_id"],
            message_id=r["message_id"],
            text=text,
            reply_markup=kb,
            parse_mode="Markdown"
        )
    except BadRequest as e:
        s = str(e).lower()
        if "message to edit not found" in s or "message is not modified" in s:
            return
        raise

def _compose_create_text(rp_type: str, count: int, amount: float, cover=None) -> str:
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(rp_type, "随机")
    cover_line = cover if cover else "封面未设置"
    return (
        f"🧧 发送红包\n\n{cover_line}\n\n--- ☝️ 红包封面 ☝️ ---\n\n"
        f"类型：【{type_cn}】\n"
        f"币种：USDT-trc20\n数量：{fmt_amount(amount)}\n金额：{fmt_amount(amount)}\n\n"
        "提示：超过24小时未领取，余额将自动退回至余额。"
    )

async def rp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _guard_redpkt(update, context):
        return
    from .common import cancel_kb
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user

    if data == "rp_go_wallet":
        redpacket_logger.info("🧧 跳转我的钱包：用户=%s", u.id)
        await h_wallet.show_wallet(update, context)
        return

    if data == "rp_new":
        cover = await _build_default_cover("random", u.id, None)
        rp_id = await create_red_packet(u.id, "random", 1.0, 1, None, cover, None)
        msg = await q.message.reply_text(
            _compose_create_text("random", 1, 1.0, cover=cover),
            reply_markup=redpacket_create_menu(rp_id, "random")
        )
        context.user_data["rp_create_msg_id"] = msg.message_id
        redpacket_logger.info("🧧 新建红包：用户=%s，红包ID=%s，类型=random，金额=1.0，个数=1", u.id, rp_id)
        return

    if data.startswith("rp_type:"):
        _, rp_id_str, new_type = data.split(":")
        rp_id = int(rp_id_str)
        await execute(
            "UPDATE red_packets SET type=%s, exclusive_user_id=IF(%s='exclusive',exclusive_user_id,NULL) WHERE id=%s",
            (new_type, new_type, rp_id)
        )
        r = await get_red_packet(rp_id)
        import re
        old_cover = r.get("cover_text") or ""
        pat1 = r"^来自.*?的【(随机|平均|专属)】红包。?$"
        pat2 = r"^来自.*?送给.*?的【专属】红包。?$"
        if (not old_cover) or re.match(pat1, old_cover) or re.match(pat2, old_cover):
            new_cover = await _build_default_cover(new_type, r["owner_id"], r.get("exclusive_user_id"))
            await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (new_cover, rp_id))
            r["cover_text"] = new_cover
        try:
            await q.message.edit_text(
                _compose_create_text(r["type"], r["count"], r["total_amount"], r.get("cover_text")),
                reply_markup=redpacket_create_menu(rp_id, r["type"])
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        context.user_data["rp_create_msg_id"] = q.message.message_id
        redpacket_logger.info("🧧 切换类型：用户=%s，红包ID=%s，新类型=%s", u.id, rp_id, new_type)
        return

    if data.startswith("rp_query:ask"):
        context.user_data["rp_query_waiting"] = True
        msg = await q.message.reply_text("请输入红包ID：", reply_markup=cancel_kb("rp_query"))
        context.user_data["rp_prompt_msg_id"] = msg.message_id
        return

    if data.startswith("rp_detail:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        shares = await list_red_packet_shares(rp_id)
        claimed = sum(1 for s in shares if s["claimed_by"]) if shares else 0
        type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(r["type"], r["type"])
        lines = [
            "🧧 红包详情",
            f"编号：{r['id']}",
            f"类型：{type_cn}",
            f"币种：{r.get('currency','USDT-trc20')}",
            f"红包个数：{r['count']}",
            f"总金额：{fmt_amount(r['total_amount'])}",
            f"封面：{r.get('cover_text') or '未设置'}",
            f"专属对象：{r.get('exclusive_user_id') or '无'}",
            f"状态：{r['status']}",
            f"已领取：{claimed}/{r['count']}",
        ]
        await q.message.reply_text("\n".join(lines))
        redpacket_logger.info("🧧 查看详情：用户=%s，红包ID=%s", u.id, rp_id)
        return

    # 设置数量
    if data.startswith("rp_set_count:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("count", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        from telegram import ForceReply
        msg = await q.message.reply_text(
            "请输入红包数量（整数）：",
            reply_markup=ForceReply(selective=True, input_field_placeholder="请输入红包数量（整数）")
        )
        context.user_data["rp_prompt_msg_id"] = msg.message_id
        return

    # 设置金额
    if data.startswith("rp_set_amount:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("amount", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        from telegram import ForceReply
        msg = await q.message.reply_text(
            "请输入红包总金额（USDT，支持小数）：",
            reply_markup=ForceReply(selective=True, input_field_placeholder="请输入红包总金额")
        )
        context.user_data["rp_prompt_msg_id"] = msg.message_id
        return

    # 设置专属对象
    if data.startswith("rp_set_exclusive:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("exclusive", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        from telegram import ForceReply
        msg = await q.message.reply_text(
            "🧧 发送红包\n\n👩‍💻 确认专属红包领取人！\n请使用以下任意方式：\nA、转发对方任意一条文字消息到这里\nB、发送对方的账户 ID（如 588726829）\nC、发送对方的用户名（如 @username）",
            reply_markup=ForceReply(selective=True, input_field_placeholder="转发消息 / 发送ID / @用户名")
        )
        context.user_data["rp_prompt_msg_id"] = msg.message_id
        return

    # 设置封面
    if data.startswith("rp_set_cover:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("cover", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        from telegram import ForceReply
        msg = await q.message.reply_text(
            "✍️ 设置封面\n👩‍💻 发送一段文字（≤150 字）或图片作为红包封面。",
            reply_markup=ForceReply(selective=True, input_field_placeholder="输入封面文字或发送图片")
        )
        context.user_data["rp_prompt_msg_id"] = msg.message_id
        return

    if data.startswith("rp_pay:"):
        # 这里的支付流程已迁移至 rppwd_callback，rp_pay 仅负责拉起键盘
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        if r["type"] == "exclusive" and not r.get("exclusive_user_id"):
            await q.message.reply_text("专属红包必须设置专属对象，无法支付！"); return
        if not await has_tx_password(u.id):
            await q.message.reply_text("⚠️ 资金密码未设置，请先设置。")
            await h_password.set_password(update, context)
            return
        context.user_data["rppwd_flow"] = {"rp_id": rp_id, "buf": "", "vis": False}
        await q.message.reply_text(_pwd_render("", False), reply_markup=_RPPWD_KBD)
        return

    if data.startswith("rp_claim:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r or r["status"] not in ("sent","paid"):
            await q.message.reply_text("红包不可领取或不存在。"); return
        if r["type"] == "exclusive" and r.get("exclusive_user_id") != update.effective_user.id:
            await q.message.reply_text("你不是我的宝贝,不能领取!"); return

        share = await claim_share(rp_id, update.effective_user.id)
        if not share:
            # 已领完
            try:
                await q.answer("已被抢完", show_alert=True)
            except Exception:
                pass
            try:
                await _update_claim_panel(context.bot, rp_id)
            except Exception:
                pass
            return

        # 入账
        from decimal import Decimal
        wallet = await get_wallet(update.effective_user.id)
        before = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
        amt = Decimal(str(share["amount"]))
        after = before + amt
        await update_wallet_balance(update.effective_user.id, float(after))
        await add_ledger(update.effective_user.id, "redpacket_claim", float(amt), float(before), float(after), "red_packets", rp_id, "领取红包入账")

        # 弹窗提示
        try:
            await q.answer(f"领取成功：+{fmt_amount(amt)} USDT", show_alert=True)
        except Exception:
            pass

        # 全部领取完 → finished
        claimed = await count_claimed(rp_id)
        if claimed >= int(r["count"]):
            await set_red_packet_status(rp_id, "finished")

        # 更新主面板（若存在）
        try:
            await _update_claim_panel(context.bot, rp_id)
        except Exception:
            pass
        return

    if data.startswith("rp_send:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        await set_red_packet_status(rp_id, "sent")
        # 不在当前对话发送领取卡片；展示“转发按钮”，点击弹出选择聊天
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{rp_id}")]])
        await q.message.reply_text("请选择要转发的群或联系人：", reply_markup=kb)
        return

    if data == "rp_refund_all":
        # 批量回收：关闭使用中红包（created/paid/sent），并退回未领取余额
        from ..models import list_user_active_red_packets, sum_claimed_amount, get_wallet, update_wallet_balance, add_ledger, set_red_packet_status
        u = update.effective_user
        rps = await list_user_active_red_packets(u.id)
        if not rps:
            await q.message.reply_text("当前没有处于使用中的红包。")
            return

        from decimal import Decimal
        refund_sum = Decimal("0")
        refund_count = 0
        closed_count = 0

        for r in rps:
            await set_red_packet_status(r["id"], "finished")
            closed_count += 1
            claimed = Decimal(str(await sum_claimed_amount(r["id"])))
            total  = Decimal(str(r["total_amount"]))
            remain = total - claimed
            if remain > 0:
                wallet = await get_wallet(u.id)
                before = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
                after  = before + remain
                await update_wallet_balance(u.id, float(after))
                await add_ledger(
                    u.id, "redpacket_refund", float(remain), float(before), float(after),
                    "red_packets", r["id"], "红包退回（批量回收）"
                )
                refund_sum += remain
                refund_count += 1

        w = await get_wallet(u.id)
        cur_bal = fmt_amount((w or {}).get("usdt_trc20_balance", 0.0))
        await q.message.reply_text(
            f"✅ 已关闭 {closed_count} 个红包，"
            f"其中 {refund_count} 个发生退款，合计：{fmt_amount(refund_sum)} USDT。\n"
            f"💼 当前余额：{cur_bal} USDT"
        )
        return


async def on_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "await_field" not in context.user_data:
        return
    field, rp_id = context.user_data.pop("await_field")
    text = update.message.text or ""
    u = update.effective_user
    r = await get_red_packet(rp_id)
    if not r:
        await update.message.reply_text("红包不存在。");
        redpacket_logger.info("🧧 设置失败：红包不存在，用户=%s，字段=%s，输入=%s", u.id, field, text)
        return

    curr_type = r["type"]
    curr_count = r["count"]
    curr_amount = r["total_amount"]
    cover = r.get("cover_text") or "未设置"

    # 做完修改后尝试删除提示消息 & 用户输入
    async def _cleanup_messages():
        pid = context.user_data.pop("rp_prompt_msg_id", None)
        try:
            if pid:
                await context.bot.delete_message(update.effective_chat.id, pid)
        except Exception:
            pass
        try:
            await context.bot.delete_message(update.effective_chat.id, update.message.message_id)
        except Exception:
            pass

    if field == "count":
        try:
            n = int(text.strip())
            if n <= 0 or n > 1000:
                raise ValueError
            await execute("UPDATE red_packets SET count=%s WHERE id=%s", (n, rp_id))
            curr_count = n
            redpacket_logger.info("🧧 设置数量：用户=%s，红包ID=%s，新数量=%s", u.id, rp_id, n)
        except Exception:
            await update.message.reply_text("数量无效，请输入正整数（≤1000）。"); return

    elif field == "amount":
        try:
            v = float(text.strip())
            if v <= 0:
                raise ValueError
            await execute("UPDATE red_packets SET total_amount=%s WHERE id=%s", (v, rp_id))
            curr_amount = v
            redpacket_logger.info("🧧 设置金额：用户=%s，红包ID=%s，新金额=%.6f", u.id, rp_id, v)
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
            else:
                try:
                    target_id = int(s)
                except Exception:
                    target_id = None
        if target_id:
            await execute("UPDATE red_packets SET exclusive_user_id=%s, type='exclusive' WHERE id=%s", (target_id, rp_id))
            curr_type = "exclusive"
            redpacket_logger.info("🧧 设置专属：用户=%s，红包ID=%s，专属对象=%s", u.id, rp_id, target_id)
        new_cover = await _build_default_cover("exclusive", r["owner_id"], target_id or r.get("exclusive_user_id"))
        await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (new_cover, rp_id))
        cover = new_cover

    elif field == "cover":
        if update.message.photo:
            file_id = update.message.photo[-1].file_id
            await execute("UPDATE red_packets SET cover_image_file_id=%s WHERE id=%s", (file_id, rp_id))
            cover = "[图片封面]"
            redpacket_logger.info("🧧 设置封面(图片)：用户=%s，红包ID=%s，file_id=%s", u.id, rp_id, file_id)
        else:
            s = text.strip()
            if len(s) > 150:
                await update.message.reply_text("文字封面最多150字符，请重试。"); return
            await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (s, rp_id))
            cover = s or "未设置"
            redpacket_logger.info("🧧 设置封面(文字)：用户=%s，红包ID=%s，文字长度=%s", u.id, rp_id, len(s))

    await _cleanup_messages()

    panel_mid = context.user_data.get("rp_create_msg_id")
    text_to_show = _compose_create_text(curr_type, curr_count, curr_amount, cover=cover if cover!='未设置' else None)
    if panel_mid:
        try:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=panel_mid,
                text=text_to_show,
                reply_markup=redpacket_create_menu(rp_id, curr_type)
            )
        except Exception:
            await update.message.reply_text(text_to_show, reply_markup=redpacket_create_menu(rp_id, curr_type))
    else:
        await update.message.reply_text(text_to_show, reply_markup=redpacket_create_menu(rp_id, curr_type))

async def inlinequery_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iq = update.inline_query
    q = (iq.query or "").strip()
    results = []

    def _mk_article(r):
        txt, kb = asyncio.get_event_loop().run_until_complete(_render_claim_panel(r))
        return InlineQueryResultArticle(
            id=str(uuid4()),
            title=f"红包 #{r['id']} - 点击插入领取卡片",
            input_message_content=InputTextMessageContent(txt, parse_mode="Markdown"),
            reply_markup=kb,
            description=f"{r['count']} 份，总额 {fmt_amount(r['total_amount'])} USDT"
        )

    if q.startswith("rp:"):
        try:
            rp_id = int(q.split(":",1)[1])
            r = await get_red_packet(rp_id)
            if r and r["status"] in ("paid","sent"):
                results = [_mk_article(r)]
        except Exception:
            results = []

    await iq.answer(results, cache_time=0, is_personal=True,
                    switch_pm_text="创建红包", switch_pm_parameter="start")

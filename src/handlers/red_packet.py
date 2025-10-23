from uuid import uuid4
from telegram import InlineQueryResultArticle, InputTextMessageContent
from decimal import Decimal
from ..utils.logfmt import log_user
from ..consts import LEDGER_TYPE_CN
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
    get_tx_password_hash, has_tx_password, list_ledger_recent, get_flag,
    sum_claimed_amount, list_user_active_red_packets, claim_share_atomic  # ← 补充
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


def _build_pwd_kb():
    import random
    nums = [str(i) for i in range(10)]
    random.shuffle(nums)
    # 三行数字 + 第四行 [显/隐, 删除, 取消]
    rows = [nums[i:i+3] for i in range(0, 9, 3)]
    rows.append([nums[9]])
    kb = []
    for r in rows[:-1]:
        kb.append([InlineKeyboardButton(n, callback_data=f"rppwd:{n}") for n in r])
    kb.append([InlineKeyboardButton(rows[-1][0], callback_data=f"rppwd:{rows[-1][0]}")])
    kb.append([
        InlineKeyboardButton("👁", callback_data="rppwd:TOGGLE"),
        InlineKeyboardButton("⌫", callback_data="rppwd:BK"),
        InlineKeyboardButton("取消", callback_data="rppwd:CANCEL"),
    ])
    return InlineKeyboardMarkup(kb)

def _pwd_render(buf: str, vis: bool) -> str:
    s = buf if vis else "•" * len(buf)
    return f"请输入资金密码：\n\n{s: <4}\n\n提示：连续 4 位数字"


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
    type_text = f"【{type_cn}】"  # 仅纯文本，不做链接
    if rp_type == "exclusive" and exclusive_uid:
        to = await get_user(exclusive_uid)
        to_link = f"[{_name(to, exclusive_uid)}](tg://user?id={exclusive_uid})"
        return f"来自{owner_link}送给{to_link}的{type_text}红包。"
    return f"来自{owner_link}的{type_text}红包"

async def rppwd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("rppwd_flow")
    if not st:
        try: await q.message.edit_text("会话已过期，请重新点击“确认支付”。")
        except BadRequest: pass
        return

    key = q.data.split(":", 1)[1]
    if key == "CANCEL":
        context.user_data.pop("rppwd_flow", None)
        try: await q.message.edit_text("已取消。")
        except BadRequest: pass
        redpacket_logger.info("🧧 支付取消：用户=%s", log_user(update.effective_user))
        return

    def _reshow():
        try:
            return q.edit_message_text(_pwd_render(st["buf"], st["vis"]), reply_markup=_build_pwd_kb())
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise

    if key == "TOGGLE":
        st["vis"] = not st["vis"]; await _reshow(); return
    if key == "BK":
        st["buf"] = st["buf"][:-1]; await _reshow(); return
    if key.isdigit():
        if len(st["buf"]) >= 4:
            await _reshow(); return
        st["buf"] += key
        await _reshow()
        if len(st["buf"]) < 4:
            return

        # 校验密码
        rp_id = st["rp_id"]
        hp = await get_tx_password_hash(update.effective_user.id)
        if not hp or not verify_password(st["buf"], hp):
            st["buf"] = ""
            try:
                await q.edit_message_text("密码不正确，请重试。\n\n" + _pwd_render(st["buf"], st["vis"]), reply_markup=_build_pwd_kb())
            except BadRequest: pass
            redpacket_logger.info("🧧 支付验密失败：用户=%s，红包ID=%s", log_user(update.effective_user), rp_id)
            return

        r = await get_red_packet(rp_id)
        if not r:
            context.user_data.pop("rppwd_flow", None)
            try: await q.message.edit_text("红包不存在或已删除。")
            except BadRequest: pass
            redpacket_logger.info("🧧 支付失败：红包不存在，用户=%s，红包ID=%s", log_user(update.effective_user), rp_id)
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
                await q.message.edit_text("余额不足（可用余额不足），无法支付！")
            except BadRequest: pass
            redpacket_logger.info("🧧 支付失败：余额不足，用户=%s，红包ID=%s，总额=%.6f，可用=%.6f",
                                  log_user(update.effective_user), rp_id, float(total), float(avail))
            return

        # 扣款 + 账变（带唯一订单号）
        new_bal = bal - total
        await update_wallet_balance(update.effective_user.id, float(new_bal))

        # 生成份额
        shares = split_random(float(total), int(r["count"])) if r["type"] == "random" else split_average(float(total), int(r["count"]))
        for i, s in enumerate(shares, 1):
            await save_red_packet_share(rp_id, i, float(s))

        await set_red_packet_status(rp_id, "paid")

        # order_no：red_send_<rp_no>
        rp_info = await get_red_packet(rp_id)
        rp_no = rp_info["rp_no"]
        order_no = f"red_send_{rp_no}"

        await add_ledger(update.effective_user.id, "redpacket_send", -float(total), float(bal), float(new_bal),
                         "red_packets", rp_id, "发送红包扣款", order_no)

        redpacket_logger.info("🧧 支付成功：用户=%s，红包=%s，总额=%.6f，份数=%s，余额变更：%.6f → %.6f",
                              log_user(update.effective_user), rp_no, float(total), r["count"], float(bal), float(new_bal))

        context.user_data.pop("rppwd_flow", None)

        # 成功页：详情 + 两个内联按钮
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
            f"编号：{rp_no}\n"
            f"类型：{type_cn}\n"
            f"总金额：{fmt_amount(total)} USDT\n"
            f"份数：{r['count']}\n"
            f"有效期至：{exp_text}\n\n"
            "请选择如何发送红包领取卡片："
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 在本聊天插入红包", switch_inline_query_current_chat=f"rp:{rp_id}")],
            [InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{rp_id}")],
            [InlineKeyboardButton("查看详情", callback_data=f"rp_detail:{rp_id}")]
        ])
        await q.message.reply_text("请选择要插入或转发的聊天：", reply_markup=kb)
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
    recs = await list_red_packets(u.id, 10)

    from ..services.format import fmt_amount
    lines = ["🧧 最近创建的 10 笔："]
    tbl = ["ID｜金额｜数量｜时间", "----｜----｜----｜----"]
    index_map = {}
    if recs:
        # 按时间倒序
        for i, r in enumerate(recs, 1):
            tm = "-"
            if r.get("created_at"):
                try:
                    tm = str(r["created_at"])[5:16]  # MM-DD HH:MM
                except Exception:
                    pass
            # 金额显示：已领合计 / 总额
            try:
                got = await sum_claimed_amount(r["id"])
            except Exception:
                got = 0.0
            tbl.append(f"{i}｜{fmt_amount(got)} / {fmt_amount(r['total_amount'])}｜{r['count']}｜{tm}")
            index_map[i] = r["id"]
        lines.append("```" + "\n".join(tbl) + "```")
        lines.append("\n点击下方对应的数字编号，查看详情")
    else:
        lines.append("```无记录```")

    # 动态数字按钮（最多 10 个，4 列排布）
    btns = []
    if index_map:
        row = []
        for i in range(1, len(index_map) + 1):
            row.append(InlineKeyboardButton(str(i), callback_data=f"rp_idx:{i}"))
            if len(row) == 4:
                btns.append(row); row = []
        if row:
            btns.append(row)
    btns.append([InlineKeyboardButton("回收使用中红包", callback_data="rp_refund_all")])
    btns.append([InlineKeyboardButton("创建红包", callback_data="rp_new")])
    kb = InlineKeyboardMarkup(btns)

    context.user_data["rp_index_map"] = index_map
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")
    redpacket_logger.info("🧧 打开红包页：用户=%s，最近记录数=%s", log_user(u), len(recs))

async def _render_claim_panel(r: dict, bot_username: str) -> tuple[str, InlineKeyboardMarkup]:
    from ..models import list_red_packet_top_claims, count_claimed
    from ..services.format import fmt_amount

    # 1) 封面：默认封面允许 Markdown mention；自定义文字做转义
    cover_raw = r.get("cover_text") or "封面未设置"

    def _is_default_cover(s: str) -> bool:
        return ("](" in s) and "tg://user?id=" in s

    def _escape_md(text: str) -> str:
        # 仅对自定义文字做最小转义
        for ch in ("`", "*", "_", "[", "]", "(", ")", "~", ">", "#", "+", "-", "=", "|", "{", "}", ".", "!"):
            text = text.replace(ch, "")
        return text

    cover = cover_raw if _is_default_cover(cover_raw) else _escape_md(cover_raw)

    lines = ["🧧 发送红包", "", cover, "", "--- ☝️ 红包封面 ☝️ ---", ""]
    tops = await list_red_packet_top_claims(r["id"], 10)
    if tops:
        tbl = ["ID | 用户 | 金额 | 时间"]
        for i, it in enumerate(tops, 1):
            disp = (it.get("display_name") or ((it.get("first_name") or "") + (it.get("last_name") or ""))).strip()
            who = (disp or ("ID " + str(it.get("claimed_by") or ""))).replace("\n", " ")
            tm = "-"
            if it.get("claimed_at"):
                try:
                    tm = str(it["claimed_at"])[11:16]
                except Exception:
                    pass
            tbl.append(f"{i} | {who} | {fmt_amount(it['amount'])} | {tm}")
        lines.append("```" + "\n".join(tbl) + "```")
    else:
        lines.append("```未领取```")

    claimed = await count_claimed(r["id"])
    remain = max(0, int(r["count"]) - int(claimed))
    # 群聊跳私聊的深链
    url_btn = InlineKeyboardButton("我的钱包", url=f"https://t.me/{bot_username}?start=start")

    if remain <= 0:
        lines.append("\n已抢完")
        lines.append(f"{claimed}/{r['count']} 已抢完")
        kb = InlineKeyboardMarkup([[url_btn]])
    else:
        lines.append(f"\n{claimed}/{r['count']}")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧧 立即领取", callback_data=f"rp_claim:{r['id']}")],
            [url_btn]
        ])
    return ("\n".join(lines), kb)

async def _update_claim_panel(bot, rp_id: int):
    from ..models import get_red_packet
    r = await get_red_packet(rp_id)
    if not r or not r.get("chat_id") or not r.get("message_id"):
        return
    text, kb = await _render_claim_panel(r, bot.username)
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
        f"币种：USDT-trc20\n数量：{count} 个\n金额：{fmt_amount(amount)} USDT\n\n"
        "提示：超过24小时未领取，余额将自动退回至余额。"
    )

async def rp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb, show_main_menu
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user

    # 安全回复工具
    async def _safe_answer(text: str, alert: bool = True):
        try:
            await q.answer(text, show_alert=alert)
        except Exception:
            pass

    async def _safe_reply(text: str, **kwargs):
        try:
            if q.message:
                return await q.message.reply_text(text, **kwargs)
            else:
                return await context.bot.send_message(chat_id=u.id, text=text, **kwargs)
        except Exception:
            return None

    # 直接跳钱包（兼容旧按钮；现在使用 URL 按钮，理论上不会再走到这里）
    if data == "rp_go_wallet":
        await _safe_answer("请在私聊中打开机器人查看钱包与主菜单。", True)
        try:
            from ..keyboards import MAIN_MENU
            await context.bot.send_message(u.id, "👇 请选择功能：", reply_markup=MAIN_MENU)
        except Exception:
            pass
        return

    # 新建
    if data == "rp_new":
        cover = await _build_default_cover("random", u.id, None)
        rp_id = await create_red_packet(u.id, "random", 1.0, 1, None, cover, None)
        msg = await _safe_reply(
            _compose_create_text("random", 1, 1.0, cover=cover),
            reply_markup=redpacket_create_menu(rp_id, "random")
        )
        if msg:
            context.user_data["rp_create_msg_id"] = msg.message_id
        redpacket_logger.info("🧧 新建红包：用户=%s，红包ID=%s，类型=random，金额=1.0，个数=1", log_user(u), rp_id)
        return

    # 列表编号 → 详情
    if data.startswith("rp_idx:"):
        try:
            idx = int(data.split(":")[1])
            rp_map = context.user_data.get("rp_index_map") or {}
            rp_id = int(rp_map.get(idx))
            if not rp_id:
                await _safe_answer("会话已过期", True); return
            data = f"rp_detail:{rp_id}"  # 复用详情逻辑
        except Exception:
            await _safe_answer("会话已过期", True); return

    # 切换类型 / 设置参数 / 详情 / 支付 / 发送 / 领取 / 回收
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
            if q.message:
                await q.message.edit_text(
                    _compose_create_text(r["type"], r["count"], r["total_amount"], r.get("cover_text")),
                    reply_markup=redpacket_create_menu(rp_id, r["type"])
                )
            else:
                await context.bot.send_message(u.id,
                    _compose_create_text(r["type"], r["count"], r["total_amount"], r.get("cover_text")),
                    reply_markup=redpacket_create_menu(rp_id, r["type"])
                )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        context.user_data["rp_create_msg_id"] = (q.message.message_id if q.message else None)
        redpacket_logger.info("🧧 切换类型：用户=%s，红包ID=%s，新类型=%s", log_user(u), rp_id, new_type)
        return

    if data.startswith("rp_query:ask"):
        context.user_data["rp_query_waiting"] = True
        msg = await _safe_reply("请输入红包ID：", reply_markup=cancel_kb("rp_query"))
        context.user_data["rp_prompt_msg_id"] = getattr(msg, "message_id", None)
        return

    if data.startswith("rp_detail:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await _safe_answer("未找到红包", True); return

        from ..consts import STATUS_CN
        type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(r["type"], r["type"])
        status_cn = STATUS_CN.get(r["status"], r["status"])
        shares = await list_red_packet_shares(rp_id)
        claimed = sum(1 for s in shares if s["claimed_by"]) if shares else 0

        head = [
            "🧧 红包详情",
            f"编号：{r['rp_no']}",
            f"类型：{type_cn}",
            f"币种：{r.get('currency','USDT-trc20')}",
            f"红包个数：{r['count']}",
            f"总金额：{fmt_amount(r['total_amount'])}",
            f"封面：{r.get('cover_text') or '未设置'}",
            f"专属对象：{r.get('exclusive_user_id') or '无'}",
            f"状态：{status_cn}",
            f"已领取：{claimed}/{r['count']}",
            ""
        ]

        from ..models import list_red_packet_claims
        claims = await list_red_packet_claims(rp_id)
        if claims:
            rows = ["序号｜时间｜领取人｜金额"]
            for c in claims:
                nick = (c.get("display_name") or ((c.get("first_name") or "") + (c.get("last_name") or ""))).strip()
                nick = nick or (c.get("username") or f"id{c.get('claimed_by')}")
                tm = str(c["claimed_at"])[11:16] if c.get("claimed_at") else "-"
                rows.append(f"{c['seq']}｜{tm}｜{nick}｜{fmt_amount(c['amount'])}")
            detail_block = "```" + "\n".join(rows) + "```"
        else:
            detail_block = "_暂无领取记录_"

        await _safe_reply("\n".join(head) + detail_block, parse_mode="Markdown")
        redpacket_logger.info("🧧 查看详情：用户=%s，红包ID=%s", log_user(u), rp_id)
        return

    # 设置数量/金额/专属/封面（略，保持你现有逻辑，已具备安全性）
    # ...

    if data.startswith("rp_pay:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await _safe_answer("会话已过期", True); return
        if r["status"] != "created":
            await _safe_answer("会话已过期，请重新创建新红包！", True); return
        if r["type"] == "exclusive" and not r.get("exclusive_user_id"):
            await _safe_answer("专属红包必须设置专属对象，无法支付！", True); return
        if not await has_tx_password(u.id):
            await _safe_reply("⚠️ 资金密码未设置，请先设置。")
            await h_password.set_password(update, context)
            return
        context.user_data["rppwd_flow"] = {"rp_id": rp_id, "buf": "", "vis": False}
        await _safe_reply(_pwd_render("", False), reply_markup=_build_pwd_kb())
        return

    if data.startswith("rp_claim:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r or r["status"] not in ("sent","paid"):
            await _safe_answer("红包不可领取或不存在。", True); return
        if r["type"] == "exclusive" and r.get("exclusive_user_id") != u.id:
            await _safe_answer("你不是我的宝贝,不能领取!", True); return

        ret = await claim_share_atomic(rp_id, u.id)
        if not ret:
            await _safe_answer("已被抢完", True)
            try:
                await _update_claim_panel(context.bot, rp_id)
            except Exception:
                pass
            redpacket_logger.info("🧧 领取失败（已抢完）：用户=%s，红包ID=%s", log_user(u), rp_id)
            return

        share_id, amt = ret
        await _safe_answer(f"领取成功：+{fmt_amount(amt)} USDT", True)

        # 份额清零后改状态
        claimed = await count_claimed(rp_id)
        if claimed >= int(r["count"]):
            await set_red_packet_status(rp_id, "finished")

        try:
            await _update_claim_panel(context.bot, rp_id)
        except Exception:
            pass

        redpacket_logger.info("🧧 领取成功：用户=%s，红包ID=%s，份额#%s，金额=%.6f",
                              log_user(u), rp_id, share_id, float(amt))
        return

    if data.startswith("rp_send:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await _safe_answer("未找到红包", True); return
        await set_red_packet_status(rp_id, "sent")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{rp_id}")]])
        await _safe_reply("请选择要转发的群或联系人：", reply_markup=kb)
        return

    if data == "rp_refund_all":
        from ..models import list_user_active_red_packets, sum_claimed_amount, get_wallet, update_wallet_balance, add_ledger, set_red_packet_status
        rps = await list_user_active_red_packets(u.id)  # 只包含 paid/sent（见 models 改动）
        if not rps:
            await _safe_reply("当前没有处于使用中的红包。")
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
                rp_no = r["rp_no"]
                order_no = f"red_refund_{rp_no}"
                await update_wallet_balance(u.id, float(after))
                await add_ledger(
                    u.id, "redpacket_refund", float(remain), float(before), float(after),
                    "red_packets", r["id"], "红包退回（批量回收）", order_no
                )
                redpacket_logger.info("🧧 回收退款：用户=%s，红包=%s，退款=%.6f，余额：%.6f → %.6f",
                                      log_user(u), rp_no, float(remain), float(before), float(after))
                refund_sum += remain
                refund_count += 1
        w = await get_wallet(u.id)
        from ..services.format import fmt_amount
        cur_bal = fmt_amount((w or {}).get("usdt_trc20_balance", 0.0))
        await _safe_reply(
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

    if q.startswith("rp:"):
        try:
            rp_id = int(q.split(":",1)[1])
            r = await get_red_packet(rp_id)
            if r and r["status"] in ("paid","sent"):
                txt, kb = await _render_claim_panel(r, context.bot.username)
                results = [InlineQueryResultArticle(
                    id=str(uuid4()),
                    title=f"红包 #{r['id']} - 点击插入领取卡片",
                    input_message_content=InputTextMessageContent(txt, parse_mode="Markdown"),
                    reply_markup=kb,
                    description=f"{r['count']} 份，总额 {fmt_amount(r['total_amount'])} USDT"
                )]
        except Exception:
            results = []
    await iq.answer(results, cache_time=0, is_personal=True)

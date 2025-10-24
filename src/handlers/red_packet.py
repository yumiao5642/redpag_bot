from telegram.constants import ParseMode
from uuid import uuid4
from telegram import InlineQueryResultArticle, InputTextMessageContent
from decimal import Decimal
from ..utils.logfmt import log_user
from ..consts import LEDGER_TYPE_CN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from ..keyboards import redpacket_create_menu, redpacket_draft_menu
from ..services.redalgo import split_random, split_average
from ..logger import redpacket_logger
from ..handlers.common import ensure_user_and_wallet, gc_track, gc_delete
from .common import safe_reply as _safe_reply
from ..models import get_flag
from .common import show_main_menu
from ..services.encryption import verify_password
from datetime import datetime, timedelta
from typing import Optional
from ..services.format import fmt_amount as fmt
from ..models import (
    list_red_packets, create_red_packet, get_red_packet, save_red_packet_share,
    list_red_packet_shares, count_claimed,
    set_red_packet_status, get_wallet, update_wallet_balance, add_ledger, execute,
    get_tx_password_hash, has_tx_password, list_ledger_recent, get_flag,
    sum_claimed_amount, list_user_active_red_packets, claim_share_atomic,
    list_red_packet_claims, get_red_packet_by_no, get_red_packet_mvp  # 新增
)
from . import wallet as h_wallet
from . import password as h_password
import random


def _human_dur(start) -> str:
    try:
        if isinstance(start, str):
            start = datetime.fromisoformat(start.replace("Z","").split(".")[0])
    except Exception:
        return "--"
    delta = datetime.now() - (start or datetime.now())
    s = int(delta.total_seconds())
    if s < 60:
        return f"{s}秒"
    if s < 3600:
        m, r = divmod(s, 60)
        return f"{m}分{r}秒"
    h, r = divmod(s, 3600)
    m, sec = divmod(r, 60)
    return f"{h}时{m}分{sec}秒"

def _safe_name_row(u: dict, uid: int) -> str:
    disp = (u.get("display_name") or ((u.get("first_name") or "") + (u.get("last_name") or ""))).strip() if u else ""
    return disp or f"ID {uid}"


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
    # 每次渲染都随机，满足“输入一位即打乱”
    rnd = random.SystemRandom()
    digits = [str(i) for i in range(10)]
    rnd.shuffle(digits)
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

    def _name(u, uid):
        if not u:
            return f"ID {uid}"
        disp = (u.get("display_name") or ((u.get("first_name") or "") + (u.get("last_name") or ""))).strip()
        return disp or f"ID {uid}"

    owner = await get_user(owner_id)
    owner_link = f"[{_name(owner, owner_id)}](tg://user?id={owner_id})"
    type_cn = {"random": "随机", "average": "平均", "exclusive": "专属"}.get(rp_type, "随机")
    # 将“红包类型”也做成一个可复制的蓝色文字（链接到发送者主页）
    type_link = f"[【{type_cn}】](tg://user?id={owner_id})"

    if rp_type == "exclusive" and exclusive_uid:
        to = await get_user(exclusive_uid)
        to_link = f"[{_name(to, exclusive_uid)}](tg://user?id={exclusive_uid})"
        return f"来自{owner_link}送给{to_link}的{type_link}红包。"
    return f"来自{owner_link}的{type_link}红包"


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

async def show_red_packets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await ensure_user_and_wallet(update, context)
    u = update.effective_user
    from ..models import list_red_packets, sum_claimed_amount, count_claimed
    from ..models import get_wallet
    from ..utils.monofmt import pad as mpad

    wallet = await get_wallet(u.id)
    bal = fmt((wallet or {}).get("usdt_trc20_balance", 0.0))
    recs = await list_red_packets(u.id, 10)

    header = f"💼 当前余额：{bal} USDT-TRC20"
    col_idx = 3
    col_amt = 20   # 金额(已领/总)
    col_cnt = 12   # 个数(已领/总)
    col_time = 11  # MM-DD HH:MM
    col_st = 10

    if recs:
        tbl = ["最近创建的 10 个红包：",
               f"{mpad('序号', col_idx)}｜{mpad('金额(已领/总额)', col_amt)}｜{mpad('个数(已领/总)', col_cnt)}｜{mpad('时间', col_time)}｜{mpad('状态', col_st)}"]
        for i, r in enumerate(recs, 1):
            tm = "-"
            if r.get("created_at"):
                try:
                    tm = str(r["created_at"])[5:16]  # MM-DD HH:MM
                except Exception:
                    pass
            total_amt = float(r["total_amount"])
            total_cnt = int(r["count"])
            got_amt = float(await sum_claimed_amount(r["id"]))
            got_cnt = int(await count_claimed(r["id"]))

            st = r.get("status")
            if st in ("paid", "sent"):
                status_text = "已抢完" if got_cnt >= total_cnt else "使用中"
            elif st == "finished":
                if got_cnt >= total_cnt:
                    status_text = "已抢完"
                else:
                    refund = max(0.0, total_amt - got_amt)
                    status_text = f"已回收（+{fmt(refund)}）"
            elif st == "created":
                status_text = "未支付"
            else:
                status_text = st or "-"

            tbl.append(
                f"{mpad(str(i), col_idx)}｜"
                f"{mpad(f'{fmt(got_amt)} / {fmt(total_amt)}', col_amt)}｜"
                f"{mpad(f'{got_cnt}/{total_cnt}', col_cnt)}｜"
                f"{mpad(tm, col_time)}｜"
                f"{mpad(status_text, col_st)}"
            )
        body = "```" + "\n".join(tbl) + "```"
    else:
        body = "```最近创建的 10 个红包：\n无记录```"

    # 仅保留两枚按钮
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("回收使用中的红包", callback_data="rp_refund_all")],
        [InlineKeyboardButton("创建红包", callback_data="rp_new")]
    ])
    await update.message.reply_text(header + "\n\n" + body, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
    redpacket_logger.info("🧧 打开红包页（无序号按钮）：用户=%s，最近记录数=%s", log_user(u), len(recs))


async def _render_claim_panel(r: dict, bot_username: str) -> tuple[str, InlineKeyboardMarkup]:
    from ..models import list_red_packet_claims, count_claimed, sum_claimed_amount, get_user

    owner_id = r["owner_id"]
    owner = await get_user(owner_id)
    owner_link = f"[{_safe_name_row(owner, owner_id)}](tg://user?id={owner_id})"
    type_cn = {"random": "随机", "average": "平均", "exclusive": "专属"}.get(r["type"], "随机")
    type_link = f"[](tg://user?id={owner_id})"

    total_amt = float(r["total_amount"])
    total_cnt = int(r["count"])
    claimed_amt = await sum_claimed_amount(r["id"])
    claimed_cnt = await count_claimed(r["id"])
    remain_cnt = max(0, total_cnt - claimed_cnt)

    expire_text = "-"
    if r.get("expires_at"):
        try:
            expire_text = str(r["expires_at"]).replace("T", " ")[:19]
        except Exception:
            pass

    # 顶部行
    lines = [f"🧧 来自{owner_link}的{type_link}红包！", "", "🧧 红包币种：USDT-trc20"]
    lines.append(f"🧧 红包金额：{fmt(claimed_amt)} / {fmt(total_amt)}")
    lines.append(f"🧧 领取数量：{claimed_cnt} / {total_cnt} 个")
    lines.append(f"到期时间：{expire_text}")
    lines.append("")

    # 动态区
    claims = await list_red_packet_claims(r["id"])
    if not claims:
        lines.append("`未领取`")
    else:
        rows = ["ID  用户  金额  时间"]
        for it in claims[:10]:
            disp = (it.get("display_name") or ((it.get("first_name") or "") + (it.get("last_name") or ""))).strip()
            who = disp or (it.get("username") or f"id{it.get('claimed_by')}")
            tm = str(it["claimed_at"])[11:16] if it.get("claimed_at") else "-"
            rows.append(f"{it['seq']:>2}  {who}  {fmt(it['amount'])}  {tm}")
        lines.append("```" + "\n".join(rows) + "```")

    # 剩余/用时
    used = _human_dur(r.get("created_at"))
    if remain_cnt > 0:
        lines.append(f"\n剩余：{remain_cnt}个")
    else:
        lines.append(f"\n剩余：0个，已抢完，用时：{used}")

    # MVP
    mvp = await get_red_packet_mvp(r["id"])
    if mvp:
        name = _safe_name_row(mvp, int(mvp.get("claimed_by") or 0))
        mvp_link = f"[{name}](tg://user?id={int(mvp.get('claimed_by') or 0)})"
        lines.append(f"MVP：《{mvp_link}》")

    # 尾部引导
    lines.append(f"\n提现 👉 @{bot_username}")

    # 键盘：有剩余才显示领取按钮；专属红包仅专属对象可见按钮（在回调里再二次校验）
    from ..models import count_claimed
    claimed = await count_claimed(r["id"])
    remain = max(0, total_cnt - int(claimed))
    if remain <= 0:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("我的钱包", url=f"https://t.me/{bot_username}?start=start")]])
    else:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧧 立即领取", callback_data=f"rp_claim:{r['id']}")],
            [InlineKeyboardButton("我的钱包", url=f"https://t.me/{bot_username}?start=start")]
        ])

    return ("\n".join(lines), kb)

async def _update_claim_panel(bot, rp_id: int, inline_message_id: Optional[str] = None):
    from ..models import get_red_packet
    r = await get_red_packet(rp_id)
    if not r:
        return
    text, kb = await _render_claim_panel(r, bot.username)
    try:
        if inline_message_id:
            await bot.edit_message_text(
                inline_message_id=inline_message_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
            return
        if r.get("chat_id") and r.get("message_id"):
            await bot.edit_message_text(
                chat_id=r["chat_id"],
                message_id=r["message_id"],
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.MARKDOWN
            )
    except BadRequest as e:
        s = str(e).lower()
        if "message to edit not found" in s or "message is not modified" in s:
            return
        raise

def _compose_create_text(rp_type: str, count: int, amount: float, cover=None) -> str:
    type_cn = {"random": "随机", "average": "平均", "exclusive": "专属"}.get(rp_type, "随机")
    cover_line = cover if cover else "封面未设置"
    return (
        f"🧧 发送红包\n\n{cover_line}\n\n--- ☝️ 红包封面 ☝️ ---\n\n"
        f"类型：【{type_cn}】\n"
        f"币种：USDT-trc20\n数量：{count} 个\n金额：{fmt(amount)} USDT\n\n"
        "提示：超过24小时未领取，余额将自动退回至余额。"
    )

async def rp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb, show_main_menu
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user

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

    async def _send_detail(rp_id: int):
        r = await get_red_packet(rp_id)
        if not r:
            await _safe_answer("未找到红包", True)
            return
        from ..consts import STATUS_CN
        shares = await list_red_packet_shares(rp_id)
        claimed = sum(1 for s in shares if s["claimed_by"]) if shares else 0
        type_cn = {"random": "随机", "average": "平均", "exclusive": "专属"}.get(r["type"], r["type"])
        head = [
            "🧧 红包详情",
            f"编号：{r['rp_no']}",
            f"类型：{type_cn}",
            f"币种：{r.get('currency','USDT-trc20')}",
            f"红包个数：{r['count']}",
            f"总金额：{fmt(r['total_amount'])}",
            f"封面：{r.get('cover_text') or '未设置'}",
            f"专属对象：{r.get('exclusive_user_id') or '无'}",
            f"状态：{STATUS_CN.get(r['status'], r['status'])}",
            f"已领取：{claimed}/{r['count']}",
            ""
        ]
        claims = await list_red_packet_claims(rp_id)
        if claims:
            rows = ["序号｜时间｜领取人｜金额"]
            for c in claims:
                nick = (c.get("display_name") or ((c.get("first_name") or "") + (c.get("last_name") or ""))).strip()
                if not nick:
                    nick = (c.get("username") or f"id{c.get('claimed_by')}")
                tm = str(c["claimed_at"])[11:16] if c.get("claimed_at") else "-"
                rows.append(f"{c['seq']}｜{tm}｜{nick}｜{fmt(c['amount'])}")
            detail_block = "```" + "\n".join(rows) + "```"
        else:
            detail_block = "_暂无领取记录_"
        await _safe_reply("\n".join(head) + detail_block, parse_mode=ParseMode.MARKDOWN)
        redpacket_logger.info("🧧 查看详情：用户=%s，红包ID=%s", log_user(u), rp_id)

    # ========= 新建草稿 =========
    if data == "rp_new":
        cover = await _build_default_cover("random", u.id, None)
        context.user_data["rp_draft"] = {"type": "random", "total_amount": 1.0, "count": 1,
                                         "exclusive_user_id": None, "cover_text": cover}
        msg = await _safe_reply(
            _compose_create_text("random", 1, 1.0, cover=cover),
            reply_markup=redpacket_draft_menu("random"),
            parse_mode=ParseMode.MARKDOWN
        )
        if msg:
            context.user_data["rp_create_msg_id"] = msg.message_id
            await gc_track(context, msg.chat_id, msg.message_id, "rp_panel")
        redpacket_logger.info("🧧 新建草稿：用户=%s，类型=random，金额=1.0，个数=1", log_user(u))
        return

    # ========= 草稿：切换类型 =========
    if data.startswith("rpd_type:"):
        new_type = data.split(":", 1)[1]
        d = context.user_data.get("rp_draft")
        if not d:
            await _safe_answer("会话已过期", True)
            return
        d["type"] = new_type
        d["cover_text"] = await _build_default_cover(new_type, u.id, d.get("exclusive_user_id"))
        txt = _compose_create_text(d["type"], d["count"], d["total_amount"], d["cover_text"])
        try:
            await q.message.edit_text(txt, reply_markup=redpacket_draft_menu(d["type"]), parse_mode=ParseMode.MARKDOWN)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                raise
        return

    # ========= 草稿：设置数量/金额/专属/封面 =========
    if data == "rpd_set_count":
        context.user_data["await_field"] = ("draft_count", None)
        from telegram import ForceReply
        msg = await _safe_reply("请输入红包数量（整数）：", reply_markup=ForceReply(selective=True, input_field_placeholder="请输入红包数量（整数）"))
        context.user_data["rp_prompt_msg_id"] = getattr(msg, "message_id", None)
        return

    if data == "rpd_set_amount":
        context.user_data["await_field"] = ("draft_amount", None)
        from telegram import ForceReply
        msg = await _safe_reply("请输入红包总金额（USDT，支持小数）：", reply_markup=ForceReply(selective=True, input_field_placeholder="请输入红包总金额"))
        context.user_data["rp_prompt_msg_id"] = getattr(msg, "message_id", None)
        return

    if data == "rpd_set_exclusive":
        context.user_data["await_field"] = ("draft_exclusive", None)
        from telegram import ForceReply
        msg = await _safe_reply(
            "🧧 发送红包\n\n👩‍💻 确认专属红包领取人！\nA、转发对方任意一条文字消息到这里\nB、发送对方的账户 ID（如 588726829）\nC、发送对方的用户名（如 @username）",
            reply_markup=ForceReply(selective=True, input_field_placeholder="转发消息 / 发送ID / @用户名")
        )
        context.user_data["rp_prompt_msg_id"] = getattr(msg, "message_id", None)
        return

    if data == "rpd_set_cover":
        context.user_data["await_field"] = ("draft_cover", None)
        from telegram import ForceReply
        msg = await _safe_reply("✍️ 设置封面\n👩‍💻 发送一段文字（≤150 字）作为红包封面。", reply_markup=ForceReply(selective=True, input_field_placeholder="输入封面文字"))
        context.user_data["rp_prompt_msg_id"] = getattr(msg, "message_id", None)
        return

    # ========= 草稿：确认支付（先检查是否已设置密码） =========
    if data == "rpd_pay":
        d = context.user_data.get("rp_draft")
        if not d:
            await _safe_answer("会话已过期", True)
            return
        if not await has_tx_password(u.id):
            await _safe_reply("⚠️ 资金密码未设置，请先设置。")
            await h_password.set_password(update, context)
            return
        context.user_data["rppwd_flow"] = {"draft": True, "buf": "", "vis": False}
        msg = await _safe_reply(_pwd_render("", False), reply_markup=_pwd_kbd())
        if msg:
            await gc_track(context, msg.chat_id, msg.message_id, "rppwd")
        return

    # ========= 详情 =========
    if data.startswith("rp_detail:"):
        rp_id = int(data.split(":")[1])
        await _send_detail(rp_id)
        return

    # ========= 以下保留原逻辑：设置数量/金额/专属/封面（入库红包）、支付、领取、转发、回收 =========
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

    # ========= 入库红包：确认支付 =========
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
        msg = await _safe_reply(_pwd_render("", False), reply_markup=_pwd_kbd())
        if msg:
            await gc_track(context, msg.chat_id, msg.message_id, "rppwd")
        return

    # ========= 领取 =========
    if data.startswith("rp_claim:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r or r["status"] not in ("sent", "paid"):
            await _safe_answer("红包不可领取或不存在。", True)
            return
        # 领取前：确保注册 + 钱包存在
        try:
            await ensure_user_and_wallet(update, context)
        except Exception as e:
            redpacket_logger.exception("🧧 ensure_user_and_wallet 失败：%s", e)

        if r["type"] == "exclusive" and r.get("exclusive_user_id") != u.id:
            await _safe_answer("你不是我的宝贝,不能领取!", True)
            return

        ret = await claim_share_atomic(rp_id, u.id)
        if not ret:
            await _safe_answer("已被抢完", True)
            try:
                await _update_claim_panel(context.bot, rp_id, inline_message_id=q.inline_message_id)
            except Exception:
                pass
            redpacket_logger.info("🧧 领取失败（已抢完）：用户=%s，红包ID=%s", log_user(u), rp_id)
            return

        share_id, amt = ret
        await _safe_answer(f"领取成功：+{fmt(amt)} USDT", True)
        claimed = await count_claimed(rp_id)
        if claimed >= int(r["count"]):
            await set_red_packet_status(rp_id, "finished")
        try:
            await _update_claim_panel(context.bot, rp_id, inline_message_id=q.inline_message_id)
        except Exception:
            pass
        redpacket_logger.info("🧧 领取成功：用户=%s，红包ID=%s，份额#%s，金额=%.6f",
                              log_user(u), rp_id, share_id, float(amt))
        return

    # ========= 转发（保持） =========
    if data.startswith("rp_send:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await _safe_answer("未找到红包", True)
            return
        await set_red_packet_status(rp_id, "sent")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{r['rp_no']}")]])
        await _safe_reply("请选择要转发的群或联系人：", reply_markup=kb)
        return

    if data == "rp_refund_all":
        rps = await list_user_active_red_packets(u.id)
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
            total = Decimal(str(r["total_amount"]))
            remain = total - claimed
            if remain > 0:
                wallet = await get_wallet(u.id)
                before = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
                after = before + remain
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
        cur_bal = fmt((w or {}).get("usdt_trc20_balance", 0.0))
        await _safe_reply(
            f"✅ 已关闭 {closed_count} 个红包，"
            f"其中 {refund_count} 个发生退款，合计：{fmt(refund_sum)} USDT。\n"
            f"💼 当前余额：{cur_bal} USDT"
        )
        return


async def on_user_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """处理草稿与入库红包的设置项输入（数量/金额/专属/封面）"""

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

    async def _edit_or_send_panel(text_to_show: str, kb):
        panel_mid = context.user_data.get("rp_create_msg_id")
        if panel_mid:
            try:
                await context.bot.edit_message_text(
                    chat_id=update.effective_chat.id,
                    message_id=panel_mid,
                    text=text_to_show,
                    reply_markup=kb,
                    parse_mode=ParseMode.MARKDOWN
                )
                redpacket_logger.info("🧧 更新创建面板成功：chat=%s, mid=%s", update.effective_chat.id, panel_mid)
                return
            except BadRequest as e:
                msg = str(e)
                if "Message is not modified" in msg:
                    redpacket_logger.info("🧧 创建面板未变更（忽略）：mid=%s", panel_mid)
                    return
                redpacket_logger.exception("🧧 更新创建面板失败，将降级为新消息：mid=%s，err=%s", panel_mid, msg)
            except Exception as e:
                redpacket_logger.exception("🧧 更新创建面板异常（将降级为新消息）：mid=%s，err=%s", panel_mid, e)

        # 发送新消息并登记清理
        try:
            msg = await update.message.reply_text(text_to_show, reply_markup=kb, parse_mode=ParseMode.MARKDOWN)
            context.user_data["rp_create_msg_id"] = getattr(msg, "message_id", None)
            await gc_track(context, msg.chat_id, msg.message_id, "rp_panel")
            redpacket_logger.info("🧧 发送新的创建面板：chat=%s, new_mid=%s", update.effective_chat.id, context.user_data.get("rp_create_msg_id"))
        except Exception as e:
            redpacket_logger.exception("🧧 发送新的创建面板失败：%s", e)

    # 处理“草稿模式”的字段
    if "await_field" in context.user_data:
        field, rp_id_or_none = context.user_data.pop("await_field")
        # 草稿流程
        if field.startswith("draft_"):
            d = context.user_data.get("rp_draft")
            if not d:
                await update.message.reply_text("会话已过期，请重新创建红包。")
                return
            txt = (update.message.text or "").strip()
            await _cleanup_messages()
            changed = False
            if field == "draft_count":
                try:
                    n = int(txt)
                    if n <= 0 or n > 1000: raise ValueError
                    d["count"] = n; changed = True
                    redpacket_logger.info("🧧 草稿-设置数量：%s", n)
                except Exception:
                    await update.message.reply_text("数量无效，请输入正整数（≤1000）。"); return
            elif field == "draft_amount":
                try:
                    v = float(txt)
                    if v <= 0: raise ValueError
                    d["total_amount"] = v; changed = True
                    redpacket_logger.info("🧧 草稿-设置金额：%.6f", v)
                except Exception:
                    await update.message.reply_text("金额无效，请输入正数。"); return
            elif field == "draft_exclusive":
                target_id = None
                if update.message.forward_from:
                    target_id = update.message.forward_from.id
                else:
                    if txt.startswith("@"):
                        await update.message.reply_text("已记录用户名（若无法解析 ID，请对方先私聊本机器人以建立映射）。")
                    else:
                        try:
                            target_id = int(txt)
                        except Exception:
                            target_id = None
                d["exclusive_user_id"] = target_id
                d["type"] = "exclusive" if target_id else d["type"]
                d["cover_text"] = await _build_default_cover(d["type"], update.effective_user.id, target_id)
                changed = True
                redpacket_logger.info("🧧 草稿-设置专属：%s", target_id or "-")
            elif field == "draft_cover":
                if len(txt) > 150:
                    await update.message.reply_text("文字封面最多150字符，请重试。"); return
                d["cover_text"] = txt or "未设置"
                changed = True
                redpacket_logger.info("🧧 草稿-设置封面长度：%s", len(txt))
            if changed:
                await _edit_or_send_panel(
                    _compose_create_text(d["type"], d["count"], d["total_amount"], d["cover_text"]),
                    redpacket_draft_menu(d["type"])
                )
            return

        # 入库红包流程
        rp_id = rp_id_or_none
        text = update.message.text or ""
        u = update.effective_user
        r = await get_red_packet(rp_id)
        if not r:
            await update.message.reply_text("红包不存在。")
            redpacket_logger.info("🧧 设置失败：红包不存在，用户=%s，字段=%s，输入=%s", u.id, field, text)
            return

        curr_type = r["type"]
        curr_count = r["count"]
        curr_amount = r["total_amount"]
        cover = r.get("cover_text") or "未设置"

        # 清理提示与用户输入
        await _cleanup_messages()

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

        await _edit_or_send_panel(
            _compose_create_text(curr_type, curr_count, curr_amount, cover=cover if cover != '未设置' else None),
            redpacket_create_menu(rp_id, curr_type)
        )

# 支付密码键盘：成功后清除 rppwd + rp_panel
async def rppwd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("rppwd_flow")
    if not st:
        try:
            await q.message.edit_text("会话已过期，请重新点击“确认支付”。")
        except BadRequest:
            pass
        return

    def _reshow(buf: str = "", vis: bool = False, stage_text: str = None):
        txt = _pwd_render(buf, vis)
        if stage_text:
            txt = stage_text + "\n\n" + txt
        try:
            return q.edit_message_text(txt, reply_markup=_pwd_kbd())
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
        await gc_delete(context, q.message.chat_id, "rppwd")
        redpacket_logger.info("🧧 支付取消：用户=%s", log_user(update.effective_user))
        return
    if key == "TOGGLE":
        st["vis"] = not st.get("vis", False)
        await _reshow(st.get("buf", ""), st["vis"])
        return
    if key == "BK":
        st["buf"] = st.get("buf", "")[:-1]
        await _reshow(st["buf"], st.get("vis", False))
        return

    if key.isdigit():
        if len(st.get("buf", "")) >= 4:
            await _reshow(st["buf"], st.get("vis", False))
            return
        st["buf"] = st.get("buf", "") + key
        await _reshow(st["buf"], st.get("vis", False))
        if len(st["buf"]) < 4:
            return

        hp = await get_tx_password_hash(update.effective_user.id)
        if not hp or not verify_password(st["buf"], hp):
            st["buf"] = ""
            try:
                await q.edit_message_text("密码不正确，请重试。\n\n" + _pwd_render(st["buf"], st.get("vis", False)), reply_markup=_pwd_kbd())
            except BadRequest:
                pass
            redpacket_logger.info("🧧 支付验密失败：用户=%s", log_user(update.effective_user))
            return

        u = update.effective_user

        # 草稿创建 or 直接支付（保持你原有逻辑）……
        if st.get("draft"):
            d = context.user_data.get("rp_draft")
            if not d:
                context.user_data.pop("rppwd_flow", None)
                try:
                    await q.message.edit_text("会话已过期，请重新创建红包。")
                except BadRequest:
                    pass
                await gc_delete(context, q.message.chat_id, "rppwd")
                return
            rp_id = await create_red_packet(
                owner_id=u.id,
                rp_type=d["type"],
                currency="USDT-trc20",
                total_amount=float(d["total_amount"]),
                count=int(d["count"]),
                cover_text=d.get("cover_text"),
                cover_image_file_id=None,
                exclusive_user_id=d.get("exclusive_user_id"),
                expire_minutes=24 * 60,
            )
            r = await get_red_packet(rp_id)
        else:
            rp_id = st["rp_id"]
            r = await get_red_packet(rp_id)
            if not r:
                context.user_data.pop("rppwd_flow", None)
                try:
                    await q.message.edit_text("红包不存在或已删除。")
                except BadRequest:
                    pass
                await gc_delete(context, q.message.chat_id, "rppwd")
                return

        # 资金校验与扣款、拆份、记账（与原逻辑一致）……
        from decimal import Decimal
        wallet = await get_wallet(u.id)
        bal = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
        frozen = Decimal(str((wallet or {}).get("usdt_trc20_frozen", 0) or 0))
        avail = bal - frozen
        total = Decimal(str(r["total_amount"]))

        if avail < total:
            context.user_data.pop("rppwd_flow", None)
            try:
                await q.message.edit_text("余额不足（可用余额不足），无法支付！")
            except BadRequest:
                pass
            redpacket_logger.info("🧧 支付失败：余额不足，用户=%s，红包ID=%s，总额=%.6f，可用=%.6f",
                                  log_user(u), r["id"], float(total), float(avail))
            await gc_delete(context, q.message.chat_id, "rppwd")
            return

        # 扣款 + 拆份 + 记账
        new_bal = bal - total
        await update_wallet_balance(u.id, float(new_bal))
        shares = split_random(float(total), int(r["count"])) if r["type"] == "random" else split_average(float(total), int(r["count"]))
        for i, s in enumerate(shares, 1):
            await save_red_packet_share(r["id"], i, float(s))
        await set_red_packet_status(r["id"], "paid")
        rp_info = await get_red_packet(r["id"])
        rp_no = rp_info["rp_no"]
        order_no = f"red_send_{rp_no}"
        await add_ledger(
            u.id, "redpacket_send", -float(total), float(bal), float(new_bal),
            "red_packets", r["id"], "发送红包扣款", order_no
        )

        # 清理状态
        context.user_data.pop("rppwd_flow", None)
        context.user_data.pop("rp_draft", None)
        context.user_data.pop("rp_create_msg_id", None)

        # 构造成功信息
        type_cn = {"random": "随机", "average": "平均", "exclusive": "专属"}.get(r["type"], r["type"])
        exp_text = "-"
        if r.get("expires_at"):
            try:
                exp_text = str(r["expires_at"]).replace("T", " ")[:16]
            except Exception:
                pass
        detail = (
            "✅ 支付成功！\n"
            f"编号：{rp_no}\n"
            f"类型：{type_cn}\n"
            f"总金额：{fmt(total)} USDT\n"
            f"份数：{r['count']}\n"
            f"有效期至：{exp_text}\n\n"
            "请选择如何发送红包领取卡片："
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 在本聊天插入红包", switch_inline_query_current_chat=f"rp:{rp_no}")],
            [InlineKeyboardButton("📤 转发红包…", switch_inline_query=f"rp:{rp_no}")]
        ])

        # 关键：先展示成功信息，再清理旧 UI；编辑失败则降级为新消息
        edited = False
        try:
            await q.message.edit_text(detail, reply_markup=kb)
            edited = True
            redpacket_logger.info("🧧 支付完成（已编辑原消息）：用户=%s，红包ID=%s，rp_no=%s", log_user(u), r["id"], rp_no)
        except BadRequest as e:
            msg = str(e).lower()
            if "message to edit not found" in msg or "message is not modified" in msg:
                await context.bot.send_message(chat_id=q.message.chat_id, text=detail, reply_markup=kb)
                redpacket_logger.info("🧧 支付完成（原消息不存在，已降级为新消息发送）：用户=%s，红包ID=%s，rp_no=%s", log_user(u), r["id"], rp_no)
            else:
                redpacket_logger.exception("🧧 支付完成后编辑消息异常：%s", e)
                raise

        # 只在未“编辑成功”时清理密码键盘（避免把成功信息删掉）
        if not edited:
            await gc_delete(context, q.message.chat_id, "rppwd")
        # 始终清理“创建面板”
        await gc_delete(context, q.message.chat_id, "rp_panel")

        # 成功后返回主菜单
        await show_main_menu(q.message.chat_id, context)
        return

async def inlinequery_handle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    iq = update.inline_query
    q = (iq.query or "").strip()
    u = update.effective_user

    token = ""
    low = q.lower()
    if low.startswith("rp:") or low.startswith("rp："):
        token = q[3:].strip()
    elif low.startswith("rp "):
        token = q[3:].strip()
    elif low.startswith("red_"):
        token = q.strip()
    elif q.isdigit():
        token = q.strip()

    if not token:
        await iq.answer([], cache_time=0, is_personal=True)
        redpacket_logger.info("🧧 [inline] 空查询：user=%s text=%r", log_user(u), q)
        return

    r = None
    try:
        if token.isdigit():
            r = await get_red_packet(int(token))
        if r is None:
            r = await get_red_packet_by_no(token)
    except Exception as e:
        redpacket_logger.exception("🧧 [inline] 查询红包异常：token=%s err=%s", token, e)
        await iq.answer([], cache_time=0, is_personal=True)
        return

    if not r or r.get("status") not in ("paid", "sent"):
        await iq.answer([], cache_time=0, is_personal=True)
        redpacket_logger.info("🧧 [inline] 未找到或不可用：token=%s status=%s", token, r.get("status") if r else None)
        return

    txt, kb = await _render_claim_panel(r, context.bot.username)
    title = f"红包：{fmt(r['total_amount'])} U / {r['count']}"
    desc = f"红包金额：{fmt(await sum_claimed_amount(r['id']))}/{fmt(r['total_amount'])} U，已领数量：{await count_claimed(r['id'])}/{r['count']}"

    res = InlineQueryResultArticle(
        id=str(uuid4()),
        title=title,
        input_message_content=InputTextMessageContent(txt, parse_mode="Markdown"),
        reply_markup=kb,
        description=desc
    )
    await iq.answer([res], cache_time=0, is_personal=True)
    redpacket_logger.info("🧧 [inline] 生成预览：user=%s rp_id=%s rp_no=%s", log_user(u), r["id"], r.get("rp_no"))

async def on_chosen_inline_result(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cir = update.chosen_inline_result
    q = (cir.query or "").strip().lower()
    token = ""
    if q.startswith("rp:") or q.startswith("rp："):
        token = q[3:].strip()
    elif q.startswith("rp "):
        token = q[3:].strip()
    elif q.startswith("red_"):
        token = q.strip()

    try:
        r = await get_red_packet_by_no(token) if token else None
        if r:
            await set_red_packet_status(r["id"], "sent")
            redpacket_logger.info("🧧 [inline] 发送到聊天：user=%s rp_id=%s rp_no=%s inline_msg=%s",
                                  log_user(update.effective_user), r["id"], r["rp_no"], cir.inline_message_id)
    except Exception as e:
        redpacket_logger.exception("🧧 [inline] chosen 处理异常：%s", e)

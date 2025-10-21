from decimal import Decimal
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.error import BadRequest
from ..keyboards import redpacket_inline_menu, redpacket_create_menu
from ..services.redalgo import split_random, split_average
from ..logger import redpacket_logger
from ..handlers.common import ensure_user_and_wallet, fmt_amount
from ..models import get_flag
from .common import show_main_menu
from ..services.encryption import verify_password
from datetime import datetime
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
def _pwd_kbd():  # 兼容原调用
    return _RPPWD_KBD

def _pwd_mask(s: str, vis: bool) -> str:
    return (s if vis else "•"*len(s)).ljust(4, "_")

def _pwd_render(buf: str, vis: bool) -> str:
    return f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(buf, vis)}"

def _name_code_from_user_row(u: dict, fallback_id: int) -> str:
    # 仅显示“昵称”（优先 display_name，其次 first_name+last_name），不使用 @username
    if not u:
        return f"`ID {fallback_id}`"
    disp = (u.get("display_name") or ((u.get("first_name") or "") + (u.get("last_name") or ""))).strip()
    return f"`{disp or ('ID ' + str(fallback_id))}`"

async def _build_default_cover(rp_type: str, owner_id: int, exclusive_uid: Optional[int]) -> str:
    from ..models import get_user
    owner = await get_user(owner_id)
    owner_txt = _name_code_from_user_row(owner, owner_id)
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(rp_type, "随机")
    if rp_type == "exclusive" and exclusive_uid:
        to = await get_user(exclusive_uid)
        to_txt = _name_code_from_user_row(to, exclusive_uid)
        return f"来自{owner_txt}送给{to_txt}的【专属】红包."
    return f"来自{owner_txt}的红包"

async def rppwd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """红包支付：数字键盘回调"""
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("rppwd_flow")
    if not st:
        # 过期或未开始
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
            # 校验密码
            from ..models import get_tx_password_hash, get_wallet, update_wallet_balance, add_ledger, get_red_packet, save_red_packet_share, set_red_packet_status
            from ..services.encryption import verify_password
            from ..services.redalgo import split_random, split_average
            from ..services.format import fmt_amount
            rp_id = st["rp_id"]
            hp = await get_tx_password_hash(update.effective_user.id)
            if not hp or not verify_password(st["buf"], hp):
                st["buf"] = ""
                await _safe_edit("密码不正确，请重试。\n\n" + _pwd_render(st["buf"], st["vis"]))
                return

            # 扣款 + 生成 shares（不直接生成“可转发消息”，见需求#4）
            r = await get_red_packet(rp_id)
            if not r:
                context.user_data.pop("rppwd_flow", None)
                try: await q.message.edit_text("红包不存在或已删除。")
                except BadRequest: pass
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
                return
            new_bal = bal - total
            await update_wallet_balance(update.effective_user.id, float(new_bal))
            await add_ledger(update.effective_user.id, "redpacket_send", -float(total), float(bal), float(new_bal), "red_packets", rp_id, "发送红包扣款")

            # 生成份额
            shares = split_random(float(total), int(r["count"])) if r["type"] == "random" else split_average(float(total), int(r["count"]))
            for i, s in enumerate(shares, 1):
                await save_red_packet_share(rp_id, i, float(s))
            await set_red_packet_status(rp_id, "paid")

            context.user_data.pop("rppwd_flow", None)
            # 支付成功 → 给出“📤 发送”按钮（不直接生成转发消息）
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("📤 发送", callback_data=f"rp_send:{rp_id}")],
                                       [InlineKeyboardButton("查看详情", callback_data=f"rp_detail:{rp_id}")]])
            try:
                await q.message.edit_text("✅ 支付成功！\n现在可以点击下方“📤 发送”，把领取消息转发到群或好友。", reply_markup=kb)
            except BadRequest:
                pass
            # 直接生成“可领取面板”，发到当前会话（用户可直接长按→转发）
            from ..models import set_red_packet_message
            text, kb = await _render_claim_panel(r)
            msg = await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
            await set_red_packet_message(rp_id, msg.chat_id, msg.message_id)
            await set_red_packet_status(rp_id, "sent")
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
    from ..models import list_recent_claims_with_creator
    recs = await list_recent_claims_with_creator(u.id, 10)

    lines = ["🧧 最近领取的 10 笔："]
    if recs:
        tbl = ["时间 | 金额 | 创建人"]
        for r in recs:
            # 时间
            t = "-"
            if r.get("claimed_at"):
                try:
                    t = str(r["claimed_at"])[:19]
                except Exception:
                    pass
            # 创建人“昵称”
            nick = (r.get("display_name") or "").strip()
            if not nick:
                nick = ((r.get("first_name") or "") + (r.get("last_name") or "")).strip() or f"ID {r.get('owner_id')}"
            from ..services.format import fmt_amount
            tbl.append(f"{t} | {fmt_amount(r['amount'])} | {nick}")
        lines.append("🧧 最近领取的 10 笔：")
        lines.append("```" + "\n".join(tbl) + "```")
    else:
        lines.append("🧧 最近领取的 10 笔：")
        lines.append("```无记录```")

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("➕ 创建红包", callback_data="rp_new")]])
    await update.message.reply_text("\n".join(lines), reply_markup=kb, parse_mode="Markdown")


async def _render_claim_panel(r: dict) -> tuple[str, InlineKeyboardMarkup]:
    """
    返回 (text, kb)
    文本包含：封面 + Top10 排行（code），以及余量/总数或“已抢完”
    """
    from ..models import list_red_packet_top_claims, count_claimed
    from ..services.format import fmt_amount
    # 封面
    cover = r.get("cover_text") or "封面未设置"
    lines = ["🧧 发送红包", "", cover, "", "--- ☝️ 红包封面 ☝️ ---", ""]

    # 排行榜（全部显示“昵称/备注”（display_name），不再用 username）
    tops = await list_red_packet_top_claims(r["id"], 10)
    if tops:
        tbl = ["ID | 用户 | 金额 | 时间"]
        for i, it in enumerate(tops, 1):
            # 仅显示昵称（display_name 或 first_name+last_name），不显示 @username
            disp = (it.get("display_name") or ((it.get("first_name") or "") + (it.get("last_name") or ""))).strip()
            who = f"`{disp or ('ID ' + str(it.get('claimed_by') or ''))}`"
            tm = "-"
            if it.get("claimed_at"):
                try:
                    tm = str(it["claimed_at"])[11:16]  # HH:MM
                except Exception:
                    pass
            tbl.append(f"{i} | {who} | {fmt_amount(it['amount'])} | {tm}")
        lines.append("```" + "\n".join(tbl) + "```")
    else:
        lines.append("```未领取```")

    # 余量显示 + “提款👉 @redpag_bot”
    claimed = await count_claimed(r["id"])
    remain = int(r["count"]) - int(claimed)

    if remain <= 0:
        lines.append("\n已抢完")
        # 新增一行客服提款入口
        lines.append("提款👉 @redpag_bot")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("我的钱包", callback_data="rp_go_wallet")]])
    else:
        lines.append(f"\n{remain}/{r['count']}")
        # 新增一行客服提款入口
        lines.append("提款👉 @redpag_bot")
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
        await bot.edit_message_text(chat_id=r["chat_id"], message_id=r["message_id"], text=text, reply_markup=kb, parse_mode="Markdown")
    except BadRequest as e:
        # 消息可能被删除/不可编辑，忽略
        if "message to edit not found" in str(e).lower():
            return
        raise

async def rp_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _guard_redpkt(update, context):
        return
    from .common import cancel_kb
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user

    if data == "rp_go_wallet":
        # 跳到我的钱包
        await h_wallet.show_wallet(update, context)
        return

    if data == "rp_new":
        # 默认：1 个、1U、类型 random；封面=来自<我>的随机红包
        cover = await _build_default_cover("random", u.id, None)
        rp_id = await create_red_packet(u.id, "random", 1.0, 1, None, cover, None)
        msg = await q.message.reply_text(
            _compose_create_text("random", 1, 1.0, cover=cover),
            reply_markup=redpacket_create_menu(rp_id, "random")
        )
        context.user_data["rp_create_msg_id"] = msg.message_id
        return

    if data.startswith("rp_type:"):
        _, rp_id_str, new_type = data.split(":")
        rp_id = int(rp_id_str)
        await execute("UPDATE red_packets SET type=%s, exclusive_user_id=IF(%s='exclusive',exclusive_user_id,NULL) WHERE id=%s",
                      (new_type, new_type, rp_id))
        r = await get_red_packet(rp_id)

        # 如果封面是“默认模式”（匹配默认模板）或为空，则自动替换类型词
        import re
        old_cover = r.get("cover_text") or ""
        pat1 = r"^来自`.*?`的【(随机|平均|专属)】红包$"
        pat2 = r"^来自`.*?`送给`.*?`的【专属】红包\.$"

        if (not old_cover) or re.match(pat1, old_cover) or re.match(pat2, old_cover):
            new_cover = await _build_default_cover(new_type, r["owner_id"], r.get("exclusive_user_id"))
            await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (new_cover, rp_id))
            r["cover_text"] = new_cover

        await q.message.edit_text(
            _compose_create_text(r["type"], r["count"], r["total_amount"], r.get("cover_text")),
            reply_markup=redpacket_create_menu(rp_id, r["type"])
        )
        context.user_data["rp_create_msg_id"] = q.message.message_id
        return

    if data.startswith("rp_query:ask"):
        context.user_data["rp_query_waiting"] = True
        await q.message.reply_text("请输入红包ID：", reply_markup=cancel_kb("rp_query"))
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
        return

    if data.startswith("rp_set_count:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("count", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        await q.message.reply_text("请输入红包数量（整数）：", reply_markup=cancel_kb("rp_count"))
        return

    if data.startswith("rp_set_amount:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("amount", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        await q.message.reply_text("请输入红包总金额（USDT，支持小数）：", reply_markup=cancel_kb("rp_amount"))
        return

    if data.startswith("rp_set_exclusive:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("exclusive", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        await q.message.reply_text(
            "🧧 发送红包\n\n👩‍💻 确认专属红包领取人!\n请使用以下任意一种方式选择目标:\nA、 转发对方任意一条文字消息到这里来.\nB、 发送对方的账户ID，如：588726829\nC、 发送对方的用户名，如：@username",
            reply_markup=cancel_kb("rp_exclusive")
        )
        return

    if data.startswith("rp_set_cover:"):
        rp_id = int(data.split(":")[1])
        context.user_data["await_field"] = ("cover", rp_id)
        context.user_data["rp_create_msg_id"] = q.message.message_id
        await q.message.reply_text("✍️ 设置封面\n👩‍💻 请发送一段文字（≤150字符）或图片作为红包的封面。", reply_markup=cancel_kb("rp_cover"))
        return

    if data.startswith("rp_pay:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return
        if r["type"] == "exclusive" and not r.get("exclusive_user_id"):
            await q.message.reply_text("专属红包必须设置专属对象，无法支付！"); return

        # 资金密码是否已设置
        if not await has_tx_password(u.id):
            await q.message.reply_text("⚠️ 资金密码未设置，请先设置。")
            await h_password.set_password(update, context)
            return

        # 启动“数字键盘输入密码”流程（键盘内已自带取消）
        context.user_data["rppwd_flow"] = {"rp_id": rp_id, "buf": "", "vis": False}
        await q.message.reply_text(_pwd_render("", False), reply_markup=_RPPWD_KBD)
        return

    if data.startswith("rp_claim:"):
        # ...（保持你现有逻辑，不变）...
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r or r["status"] not in ("sent","paid"):
            await q.message.reply_text("红包不可领取或不存在。"); return
        if r["type"] == "exclusive" and r.get("exclusive_user_id") != update.effective_user.id:
            await q.message.reply_text("你不是我的宝贝,不能领取!"); return

        share = await claim_share(rp_id, update.effective_user.id)
        if not share:
            # 编辑主面板即可；必要时提示一下
            await _update_claim_panel(context.bot, rp_id)
            return

        # 入账
        from decimal import Decimal
        wallet = await get_wallet(update.effective_user.id)
        before = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
        amt = Decimal(str(share["amount"]))
        after = before + amt
        await update_wallet_balance(update.effective_user.id, float(after))
        await add_ledger(update.effective_user.id, "redpacket_claim", float(amt), float(before), float(after), "red_packets", rp_id, "领取红包入账")

        # 私聊通知
        try:
            note = (
                "🧧 领取成功！\n"
                f"红包到账：+{fmt_amount(amt)} USDT-trc20，已入账余额。\n\n"
                f"账户ID：{update.effective_user.id}\n"
                "当前余额：\n"
                f"• USDT-TRC20：{fmt_amount(after)}\n"
            )
            await context.bot.send_message(chat_id=update.effective_user.id, text=note)
        except Exception:
            pass

        # 如果全部领取完 → 设置 finished
        claimed = await count_claimed(rp_id)
        if claimed >= int(r["count"]):
            await set_red_packet_status(rp_id, "finished")

        # 更新同一条“抢红包面板”
        await _update_claim_panel(context.bot, rp_id)
        return

    if data.startswith("rp_send:"):
        rp_id = int(data.split(":")[1])
        r = await get_red_packet(rp_id)
        if not r:
            await q.message.reply_text("未找到红包。"); return

        # 生成“抢红包面板”文本 + 按钮
        text, kb = await _render_claim_panel(r)
        msg = await q.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

        # 记录这条 “可被领取”的消息 id
        from ..models import set_red_packet_message
        await set_red_packet_message(rp_id, msg.chat_id, msg.message_id)
        await set_red_packet_status(rp_id, "sent")
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
                # 如果只给了 @，先把文案加上（无法解析 ID 时，仍保持默认）
                await update.message.reply_text("已记录用户名（若无法解析 ID，请对方先私聊本机器人以建立映射）。")
            else:
                try:
                    target_id = int(s)
                except Exception:
                    target_id = None
        if target_id:
            await execute("UPDATE red_packets SET exclusive_user_id=%s, type='exclusive' WHERE id=%s", (target_id, rp_id))
            curr_type = "exclusive"
        # 自动生成“专属封面”
        new_cover = await _build_default_cover("exclusive", r["owner_id"], target_id or r.get("exclusive_user_id"))
        await execute("UPDATE red_packets SET cover_text=%s WHERE id=%s", (new_cover, rp_id))
        cover = new_cover

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

    # 回填创建面板
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

def _compose_create_text(rp_type: str, count: int, amount: float, cover=None) -> str:
    type_cn = {"random":"随机","average":"平均","exclusive":"专属"}.get(rp_type, "随机")
    cover_line = cover if cover else "封面未设置"
    return (f"🧧 发送红包\n\n{cover_line}\n\n--- ☝️ 红包封面 ☝️ ---\n\n"
            f"类型：[{type_cn}]（下方可切换：随机｜平均｜专属）\n"
            f"币种：USDT-trc20\n数量：{count}\n金额：{fmt_amount(amount)}\n\n"
            "提示：未领取的将在24小时后退款。")

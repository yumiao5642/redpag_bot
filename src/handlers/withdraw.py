# -*- coding: utf-8 -*-
from ..utils.logfmt import log_user
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from ..models import get_wallet, list_user_addresses, add_user_address, adjust_frozen, deduct_balance_and_unfreeze, add_ledger, get_available_usdt
from ..config import MIN_WITHDRAW_USDT, WITHDRAW_FEE_FIXED, AGGREGATE_ADDRESS, AGGREGATE_PRIVKEY_ENC
from ..logger import withdraw_logger
from .common import fmt_amount, show_main_menu, gc_track, gc_delete
from ..models import get_flag
from ..services.tron import is_valid_address, get_account_resource, get_trx_balance, get_usdt_balance, usdt_transfer_all
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text
import os, time, asyncio
from decimal import Decimal
from datetime import date
import random
from ..models import make_order_no
from ..utils.monofmt import pad as mpad  # ← 新增

def _wdpwd_kbd():
    # ... 原实现保持不变 ...
    import random
    from telegram import InlineKeyboardButton
    rnd = random.SystemRandom()
    digits = [str(i) for i in range(10)]
    rnd.shuffle(digits)
    grid = [digits[:3], digits[3:6], digits[6:9]]
    last = digits[9]
    rows = []
    for row in grid:
        rows.append([InlineKeyboardButton(row[0], callback_data=f"wdpwd:{row[0]}"),
                     InlineKeyboardButton(row[1], callback_data=f"wdpwd:{row[1]}"),
                     InlineKeyboardButton(row[2], callback_data=f"wdpwd:{row[2]}")])
    rows.append([
        InlineKeyboardButton("取消", callback_data="wdpwd:CANCEL"),
        InlineKeyboardButton(last, callback_data=f"wdpwd:{last}"),
        InlineKeyboardButton("👁", callback_data="wdpwd:TOGGLE")
    ])
    rows.append([InlineKeyboardButton("⌫ 退格", callback_data="wdpwd:BK")])
    return InlineKeyboardMarkup(rows)

def _pwd_mask(s: str, vis: bool) -> str:
    return (s if vis else "•"*len(s)).ljust(4, "_")

async def _guard_withdraw(update, context) -> bool:
    try:
        if (await get_flag("lock_withdraw")) == "1":
            await update.effective_chat.send_message("维护中..请稍候尝试!")
            await show_main_menu(update.effective_chat.id, context)
            return True
    except Exception:
        pass
    return False

def _addr_kb(addrs):
    if not addrs:
        return InlineKeyboardMarkup([[InlineKeyboardButton("➕ 添加地址", callback_data="withdraw_addr_add_start")]])
    btns = [[InlineKeyboardButton("➕ 添加地址", callback_data="withdraw_addr_add_start")]]
    for a in addrs:
        btns.append([InlineKeyboardButton(f"提到 {a['alias']}", callback_data=f"withdraw_to:{a['id']}")])
    return InlineKeyboardMarkup(btns)

async def show_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if await _guard_withdraw(update, context):
        return

    u = update.effective_user
    wallet = await get_wallet(u.id)
    bal = wallet["usdt_trc20_balance"] if wallet else 0.0
    frz = (wallet or {}).get("usdt_trc20_frozen", 0.0) or 0.0
    avail = float(Decimal(str(bal)) - Decimal(str(frz)))

    base = (f"账户ID：{u.id}\n\nUSDT-trc20 -- 当前余额: {fmt_amount(bal)} U（可用 {fmt_amount(avail)} U）\n"
            f"提示: 最小提款金额: {fmt_amount(MIN_WITHDRAW_USDT)} U\n手续费: 0% + {fmt_amount(WITHDRAW_FEE_FIXED)} U\n")

    addrs = await list_user_addresses(u.id)

    if avail < MIN_WITHDRAW_USDT + WITHDRAW_FEE_FIXED:
        await update.message.reply_text(base + "\n可用余额不足提现最低要求!", reply_markup=_addr_kb(addrs))
        withdraw_logger.info("💸 打开提现页：用户=%s，可用不足（可用=%.6f）", log_user(u), avail)
        return

    if not addrs:
        await update.message.reply_text(base + "\n当前无常用地址。", reply_markup=_addr_kb(addrs))
        withdraw_logger.info("💸 打开提现页：用户=%s，暂无常用地址", log_user(u))
        return

    # 统一 code block：第一行“已添加常用地址：”，第二行表头
    col_addr = 34
    col_alias = 15
    lines = ["已添加常用地址：", f"{mpad('地址', col_addr)}  {mpad('别名', col_alias)}"]
    for a in addrs:
        lines.append(f"{mpad(a['address'], col_addr)}  {mpad(a['alias'], col_alias)}")
    code = "```" + "\n".join(lines) + "```"

    txt = base + "\n" + code
    await update.message.reply_text(txt, reply_markup=_addr_kb(addrs), parse_mode=ParseMode.MARKDOWN)
    withdraw_logger.info("💸 打开提现页：用户=%s，地址数=%s，可用=%.6f", log_user(u), len(addrs), avail)

async def withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb
    q = update.callback_query
    await q.answer()
    data = q.data or ""
    u = update.effective_user
    if data == "withdraw_addr_add_start":
        context.user_data["withdraw_add_waiting"] = True
        msg = await q.message.reply_text(
            "添加地址格式：  `地址 别名`  （空格分隔）\n例如：\n`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t IM-个人`\n\n（点击上面蓝色文字可复制）",
            parse_mode="Markdown",
            reply_markup=cancel_kb("withdraw_add")
        )
        return

    if data.startswith("withdraw_to:"):
        addr_id = int(data.split(":")[1])
        addrs = await list_user_addresses(update.effective_user.id)
        target = next((a for a in addrs if a["id"] == addr_id), None)
        if not target:
            await q.message.reply_text("地址不存在或已被删除。"); return
        context.user_data["wd_target"] = target
        context.user_data["wd_wait_amount"] = True
        msg = await q.message.reply_text(
            f"已选择地址：{target['alias']}  {target['address']}\n\n请输入提现金额（USDT）：",
            reply_markup=cancel_kb("withdraw_amount")
        )
        return


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import show_main_menu
    u = update.effective_user
    # 添加地址
    if context.user_data.get("withdraw_add_waiting"):
        txt = (update.message.text or "").strip()
        if txt in ("取消","cancel","退出"):
            context.user_data.pop("withdraw_add_waiting", None)
            await update.message.reply_text("已取消添加。")
            await show_main_menu(update.effective_chat.id, context)
            return
        parts = txt.split()
        if len(parts) < 2:
            await update.message.reply_text("格式不正确，请按 “地址 别名” 发送。"); return
        addr, alias = parts[0], " ".join(parts[1:])
        if not is_valid_address(addr):
            await update.message.reply_text("TRX 地址格式不正确，请检查后重试。"); return
        if len(alias) > 15:
            await update.message.reply_text("别名最长 15 个字符，请重新输入。"); return
        await add_user_address(update.effective_user.id, addr, alias)
        context.user_data.pop("withdraw_add_waiting", None)
        await update.message.reply_text("地址添加成功！请重新进入提现选择。")
        await show_main_menu(update.effective_chat.id, context)
        return

    # 输入金额 → 弹出密码键盘
    if context.user_data.get("wd_wait_amount"):
        amt_s = (update.message.text or "").strip()
        try:
            amt = float(Decimal(amt_s))
        except Exception:
            await update.message.reply_text("金额格式不正确，请输入数字。"); return
        if amt < MIN_WITHDRAW_USDT:
            await update.message.reply_text(f"金额不能低于最小提现额度：{fmt_amount(MIN_WITHDRAW_USDT)} U"); return
        target = context.user_data.get("wd_target")
        if not target:
            await update.message.reply_text("会话已过期，请重新选择地址。"); return
        total = float(Decimal(str(amt)) + Decimal(str(WITHDRAW_FEE_FIXED)))
        avail = await get_available_usdt(u.id)
        if avail < total:
            await update.message.reply_text(f"可用余额不足（需要 {fmt_amount(total)} U，含手续费 {fmt_amount(WITHDRAW_FEE_FIXED)} U）。")
            withdraw_logger.info("💸 提现金额校验失败：用户=%s，输入=%.6f，可用=%.6f，总需=%.6f", u.id, amt, avail, total)
            return
        context.user_data["wd_confirm"] = {"amt": amt, "target": target}
        context.user_data["wd_pwd_flow"] = {"buf":"", "vis": False}
        msg = await update.message.reply_text("🔒 请输入资金密码\n----------------------------\n🔑 ____", reply_markup=_wdpwd_kbd())
        await gc_track(context, update.effective_chat.id, msg.message_id, "wdpwd")
        withdraw_logger.info("💸 进入验密：用户=%s，金额=%.6f，目标=%s(%s)", u.id, amt, target['alias'], target['address'])
        return

async def wdpwd_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    st = context.user_data.get("wd_pwd_flow")
    if not st:
        try:
            await q.message.edit_text("会话已过期，请重新输入提现金额。")
        except Exception:
            pass
        return

    def _safe_edit(txt: str):
        try:
            if (q.message.text or "").strip() == txt.strip():
                return
            return q.edit_message_text(txt, reply_markup=_wdpwd_kbd())
        except Exception:
            pass

    key = q.data.split(":",1)[1]
    if key == "CANCEL":
        context.user_data.pop("wd_pwd_flow", None)
        await _safe_edit("已取消。")
        await gc_delete(context, q.message.chat_id, "wdpwd")
        return
    if key == "TOGGLE":
        st["vis"] = not st["vis"]; await _safe_edit(f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(st['buf'], st['vis'])}")
        return
    if key == "BK":
        st["buf"] = st["buf"][:-1]; await _safe_edit(f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(st['buf'], st['vis'])}")
        return

    if key.isdigit() and len(key) == 1:
        if len(st["buf"]) >= 4:
            await _safe_edit(f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(st['buf'], st['vis'])}")
            return
        st["buf"] += key
        await _safe_edit(f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(st['buf'], st['vis'])}")
        if len(st["buf"]) == 4:
            from ..models import get_tx_password_hash
            from ..services.encryption import verify_password
            hp = await get_tx_password_hash(update.effective_user.id)
            if not hp or not verify_password(st["buf"], hp):
                st["buf"] = ""
                await _safe_edit("密码不正确，请重试。\n\n" + f"🔒 请输入资金密码\n----------------------------\n🔑 {_pwd_mask(st['buf'], st['vis'])}")
                return

            # 验证成功，开始执行提现
            context.user_data.pop("wd_pwd_flow", None)
            await gc_delete(context, q.message.chat_id, "wdpwd")
            info = context.user_data.pop("wd_confirm", None) or {}
            amt = info.get("amt"); target = info.get("target")
            if not amt or not target:
                await q.message.edit_text("参数缺失，请重新发起提现。")
                return

            order_no = make_order_no(prefix="with_")
            await q.message.edit_text(f"⏳ 提现处理中...\n订单号：{order_no}\n金额：{fmt_amount(amt)} U\n地址：{target['address']}")

            u = update.effective_user
            total = float(Decimal(str(amt)) + Decimal(str(WITHDRAW_FEE_FIXED)))

            # 1) 冻结
            await adjust_frozen(u.id, total)

            # 2) 资源准备
            try:
                need_energy = int(os.getenv("WITHDRAW_ENERGY_REQUIRE", "90000"))
                res0 = get_account_resource(AGGREGATE_ADDRESS)
                if res0["energy"] < need_energy:
                    gap = max(need_energy - res0["energy"], int(os.getenv("TRONGAS_MIN_RENT","32000")))
                    await rent_energy(receive_address=AGGREGATE_ADDRESS, pay_nums=gap, rent_time=1, order_notes=f"wd-{u.id}")
                    t_end = time.time() + int(os.getenv("TRONGAS_ACTIVATION_DELAY","30"))
                    while time.time() < t_end:
                        res1 = get_account_resource(AGGREGATE_ADDRESS)
                        if res1["energy"] >= need_energy:
                            break
                        await asyncio.sleep(2)
            except Exception as e:
                await adjust_frozen(u.id, -total)
                await q.message.reply_text(f"准备资源失败：{e}")
                return

            # 3) 转账
            try:
                priv = decrypt_text(AGGREGATE_PRIVKEY_ENC)
                txid = await usdt_transfer_all(priv, AGGREGATE_ADDRESS, target["address"], amt)
            except Exception as e:
                await adjust_frozen(u.id, -total)
                await q.message.reply_text(f"链上转账失败：{e}")
                return

            # 4) 成功：扣除余额与冻结 + 记账
            try:
                await deduct_balance_and_unfreeze(u.id, total)
                wallet = await get_wallet(u.id)
                after = float(wallet["usdt_trc20_balance"] or 0.0)
                before = float(Decimal(str(after)) + Decimal(str(total)))
                await add_ledger(u.id, "withdraw", -float(total), float(before), float(after),
                                 "user_withdraw", 0, f"提现到 {target['alias']}（含手续费 {fmt_amount(WITHDRAW_FEE_FIXED)} U），订单号={order_no}，txid={txid}")
                await q.message.reply_text(f"✅ 提现成功：{fmt_amount(amt)} U（手续费 {fmt_amount(WITHDRAW_FEE_FIXED)} U）\n当前余额：{fmt_amount(after)} U")
            except Exception as e:
                withdraw_logger.exception(f"提现记账异常：{e}")
                await q.message.reply_text("提现已发送，但记账异常，请联系管理员人工核对。")
            return

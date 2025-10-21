# -*- coding: utf-8 -*-
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from ..models import get_wallet, list_user_addresses, add_user_address, adjust_frozen, deduct_balance_and_unfreeze, add_ledger, get_available_usdt
from ..config import MIN_WITHDRAW_USDT, WITHDRAW_FEE_FIXED, AGGREGATE_ADDRESS, AGGREGATE_PRIVKEY_ENC
from ..logger import withdraw_logger
from .common import fmt_amount, show_main_menu
from ..models import get_flag
from ..services.tron import is_valid_address, get_account_resource, get_trx_balance, get_usdt_balance, usdt_transfer_all
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text
import os, time, asyncio
from decimal import Decimal

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
        return InlineKeyboardMarkup([[InlineKeyboardButton("➕ 添加地址", callback_data="addr_add_start")]])
    btns = [[InlineKeyboardButton("➕ 添加地址", callback_data="addr_add_start")]]
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
        return

    if not addrs:
        await update.message.reply_text(base + "\n当前无常用地址。", reply_markup=_addr_kb(addrs))
        return

    lines = [base, "\n已添加常用地址："]
    for a in addrs:
        lines.append(f"- {a['alias']}  {a['address']}")
    await update.message.reply_text("\n".join(lines), reply_markup=_addr_kb(addrs))

async def withdraw_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    from .common import cancel_kb
    q = update.callback_query
    await q.answer()
    data = q.data or ""

    if data == "addr_add_start":
        context.user_data["withdraw_add_waiting"] = True
        await q.message.reply_text(
            "添加地址格式：  `地址 别名`  （空格分隔）\n例如：\n`TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t IM-个人`\n\n（点击上面蓝色文字可复制）",
            parse_mode="Markdown",
            reply_markup=cancel_kb("withdraw_add")
        )
        return

    if data.startswith("withdraw_to:"):
        addr_id = int(data.split(":")[1])
        # 读出目标地址
        addrs = await list_user_addresses(update.effective_user.id)
        target = next((a for a in addrs if a["id"] == addr_id), None)
        if not target:
            await q.message.reply_text("地址不存在或已被删除。"); return
        context.user_data["wd_target"] = target
        context.user_data["wd_wait_amount"] = True
        await q.message.reply_text(
            f"已选择地址：{target['alias']}  {target['address']}\n\n请输入提现金额（USDT）：",
            reply_markup=cancel_kb("withdraw_amount")
        )
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
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

    # 输入金额 → 执行提现
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
            return

        # 1) 冻结
        await adjust_frozen(u.id, total)

        # 2) 确保归集地址能量/带宽充足
        try:
            need_energy = int(os.getenv("WITHDRAW_ENERGY_REQUIRE", "90000"))
            need_bw = int(os.getenv("WITHDRAW_BW_REQUIRE", "800"))
            # 快照
            res0 = get_account_resource(AGGREGATE_ADDRESS)
            if res0["energy"] < need_energy:
                gap = max(need_energy - res0["energy"], int(os.getenv("TRONGAS_MIN_RENT","32000")))
                await rent_energy(receive_address=AGGREGATE_ADDRESS, pay_nums=gap, rent_time=1, order_notes=f"wd-{u.id}")
                # 等待生效
                t_end = time.time() + int(os.getenv("TRONGAS_ACTIVATION_DELAY","30"))
                while time.time() < t_end:
                    res1 = get_account_resource(AGGREGATE_ADDRESS)
                    if res1["energy"] >= need_energy:
                        break
                    await asyncio.sleep(2)
        except Exception as e:
            # 回滚冻结
            await adjust_frozen(u.id, -total)
            await update.message.reply_text(f"准备资源失败：{e}")
            return

        # 3) 转账
        try:
            priv = decrypt_text(AGGREGATE_PRIVKEY_ENC)
            txid = await usdt_transfer_all(priv, AGGREGATE_ADDRESS, target["address"], amt)
        except Exception as e:
            # 回滚冻结
            await adjust_frozen(u.id, -total)
            await update.message.reply_text(f"链上转账失败：{e}")
            return

        # 4) 成功：扣除余额与冻结 + 记账
        try:
            await deduct_balance_and_unfreeze(u.id, total)
            # 账变
            from ..models import get_wallet
            wallet = await get_wallet(u.id)
            after = float(wallet["usdt_trc20_balance"] or 0.0)
            before = float(Decimal(str(after)) + Decimal(str(total)))
            await add_ledger(u.id, "withdraw", -float(total), float(before), float(after),
                             "user_withdraw", 0, f"提现到 {target['alias']}（含手续费 {fmt_amount(WITHDRAW_FEE_FIXED)} U），txid={txid}")
            await update.message.reply_text(f"✅ 提现已提交：{fmt_amount(amt)} U\n手续费：{fmt_amount(WITHDRAW_FEE_FIXED)} U\n交易哈希：{txid}")
        except Exception as e:
            withdraw_logger.exception(f"提现记账异常：{e}")
            await update.message.reply_text("提现已发送，但记账异常，请联系管理员人工核对。")

        context.user_data.pop("wd_wait_amount", None)
        context.user_data.pop("wd_target", None)
        await show_main_menu(update.effective_chat.id, context)

import asyncio, re, time, os, requests
from decimal import Decimal
from typing import Optional, Tuple
from ..db import init_pool, close_pool, execute, execute_rowcount
from ..models import (
    list_recharge_waiting, list_recharge_collecting, list_recharge_verifying,
    set_recharge_status, get_wallet, update_wallet_balance, add_ledger,
    ledger_exists_for_ref, has_active_energy_rent, add_energy_rent_log, last_energy_rent_seconds_ago,
    get_total_user_balance, get_ledger_by_ref, set_flag
)
from ..config import MIN_DEPOSIT_USDT, AGGREGATE_ADDRESS, BOT_TOKEN
from ..logger import collect_logger, redpacket_logger
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text
from ..services.tron import (
    get_usdt_balance,
    usdt_transfer_all,
    get_account_resource,
    get_trx_balance,
    send_trx,
)


async def _auto_refund_expired_red_packets(counters: dict):
    """
    查找超过 24 小时（expires_at 已到）仍非 finished 的红包：
    - 计算未领取余额 = total - 已领取之和
    - 退回创建人余额、记账 ledger(redpacket_refund)
    - 状态置为 finished
    """
    from decimal import Decimal
    from ..models import (
        list_expired_red_packets, sum_claimed_amount, get_wallet,
        update_wallet_balance, add_ledger, set_red_packet_status
    )

    recs = await list_expired_red_packets(limit=200)
    n = 0
    total_refund = Decimal("0")

    for r in recs:
        rp_id = r["id"]; owner = r["owner_id"]
        total = Decimal(str(r["total_amount"]))
        claimed = Decimal(str(await sum_claimed_amount(rp_id)))
        remain = total - claimed
        if remain > 0:
            wallet = await get_wallet(owner)
            before = Decimal(str((wallet or {}).get("usdt_trc20_balance", 0)))
            after = before + remain
            await update_wallet_balance(owner, float(after))
            await add_ledger(owner, "redpacket_refund", float(remain), float(before), float(after),
                             "red_packets", rp_id, "红包超过24小时未领取自动退款")
            total_refund += remain

        await set_red_packet_status(rp_id, "finished")
        n += 1
        redpacket_logger.info(
            "🧧[自动回收] 红包ID=%s 创建人=%s 类型=%s 总额=%.6f 已领=%.6f 退款=%.6f -> 设为 finished",
            rp_id, owner, r.get("type"), float(total), float(claimed), float(max(remain, Decimal('0')))
        )

    counters["rp_auto_refunded"] = n
    counters["rp_auto_refunded_sum"] = float(total_refund)

# ✅ 与表结构一致：waiting 过期后置为 expired（不是 timeout）
EXPIRE_SQL = "UPDATE recharge_orders SET status='expired' WHERE status='waiting' AND expire_at <= NOW()"

def _safe_notes(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_-]", "", s)

def _notify_user(uid: int, text: str):
    try:
        if not BOT_TOKEN:
            collect_logger.warning("⚠️ BOT_TOKEN 未配置，无法向用户发送通知")
            return
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": uid, "text": text}, timeout=10)
    except Exception as e:
        collect_logger.error(f"❌ 发送用户通知失败：{e}")

async def _wait_energy_ready(addr: str, need: int, timeout: int = 30):
    end = time.time() + timeout
    while time.time() < end:
        res = get_account_resource(addr)
        if res['energy'] >= need:
            return True
        await asyncio.sleep(2)
    return False

def _log_resource_snapshot(addr: str, usdt_bal: float, res: dict, need_energy: int, need_bw: int, trx_bal: float, prefix: str="🔎 资源快照"):
    collect_logger.info(
        f"{prefix}：\n"
        f"  • 地址：{addr}\n"
        f"  • USDT余额：{usdt_bal:.6f}\n"
        f"  • 能量：{res['energy']} / 需要 {need_energy}\n"
        f"  • 带宽：{res['bandwidth']} / 建议 {need_bw}\n"
        f"  • TRX余额：{trx_bal:.6f}"
    )

async def _precheck_and_prepare(uid: int, addr: str, oid: int, order_no: str) -> Tuple[bool, float]:
    need_energy = int(os.getenv("USDT_ENERGY_REQUIRE", "90000"))
    need_bw = int(os.getenv("MIN_BANDWIDTH", "800"))
    min_deposit = float(os.getenv("MIN_DEPOSIT_USDT", "10"))
    rent_retry_sec = int(os.getenv("ENERGY_RENT_RETRY_SECONDS", "120"))

    usdt_bal = await get_usdt_balance(addr)
    res0 = get_account_resource(addr)
    trx_bal0 = get_trx_balance(addr)
    _log_resource_snapshot(addr, usdt_bal, res0, need_energy, need_bw, trx_bal0, prefix="🔎 资源快照（预检前）")

    if usdt_bal < min_deposit:
        collect_logger.info(f"⏸ USDT不足：{usdt_bal:.6f} < {min_deposit:.2f}，本轮不归集")
        return False, usdt_bal

    if res0['energy'] < need_energy:
        can_rent = True
        ago = await last_energy_rent_seconds_ago(addr)
        if ago < rent_retry_sec:
            can_rent = False
            collect_logger.info(f"⏳ 距离上次租能量 {ago}s < {rent_retry_sec}s，暂不重复下单")

        if can_rent:
            try:
                min_rent = int(os.getenv("TRONGAS_MIN_RENT", "32000"))
                step = max(int(os.getenv("TRONGAS_RENT_STEP", "1000")), 1)
                gap = max(need_energy - res0['energy'], min_rent)
                gap = ((gap + step - 1) // step) * step
                collect_logger.info(f"⚡ 计划租能量：缺口≈{need_energy - res0['energy']}，下单量={gap}（min={min_rent}, step={step}）")
                resp = await rent_energy(receive_address=addr, pay_nums=gap, rent_time=1, order_notes=f"order-{order_no}")

                rid = (resp or {}).get("orderId") or (resp or {}).get("order_id")
                await add_energy_rent_log(addr, oid, order_no, rent_order_id=str(rid), ttl_seconds=3600)
                collect_logger.info(f"⚡ 已租能量 gap≈{gap}：order_id={rid}，等待生效…")
            except Exception as e:
                collect_logger.error(f"❌ 租能量失败：{e}；先不归集")
                return False, usdt_bal

        ok = await _wait_energy_ready(addr, need_energy, timeout=int(os.getenv("TRONGAS_ACTIVATION_DELAY", "30")))
        res1 = get_account_resource(addr)
        trx_bal1 = get_trx_balance(addr)
        _log_resource_snapshot(addr, usdt_bal, res1, need_energy, need_bw, trx_bal1, prefix="🔎 资源快照（租能量后）")
        if res1['energy'] < need_energy:
            collect_logger.info(f"⏸ 能量仍不足：{res1['energy']} < {need_energy}，本轮不归集")
            return False, usdt_bal

    return True, usdt_bal

async def _ensure_resources(addr: str, oid: int, order_no: str) -> None:
    res = get_account_resource(addr)
    need_energy = int(os.getenv("USDT_ENERGY_REQUIRE", "30000"))
    need_bw = int(os.getenv("MIN_BANDWIDTH", "500"))

    if res['energy'] < need_energy and not await has_active_energy_rent(addr):
        try:
            resp = await rent_energy(
                receive_address=addr,
                pay_nums=max(need_energy - res['energy'], 20000),
                rent_time=1,
                order_notes=f"order-{order_no}"
            )
            order_id = (resp or {}).get("orderId") or (resp or {}).get("order_id")
            await add_energy_rent_log(addr, oid, order_no, rent_order_id=str(order_id), ttl_seconds=3600)
            collect_logger.info(f"⚡ 能量下单成功：订单 {oid}（{order_no}） id={order_id}")
            await asyncio.sleep(int(os.getenv("TRONGAS_ACTIVATION_DELAY", "8")))
        except Exception as e:
            collect_logger.error(f"❌ 能量下单失败：{e}；稍后重试")

    # 带宽不足时，可按需代付 TRX（省略，与你现有逻辑一致）
    # ...

async def _collect_and_book(uid: int, addr: str, oid: int, order_no: str):
    ok, bal = await _precheck_and_prepare(uid, addr, oid, order_no)
    if not ok:
        collect_logger.info(f"⏸ 订单 {oid}（{order_no}）预检未通过，跳过本轮归集")
        return None

    wallet = await get_wallet(uid)
    from ..services.encryption import decrypt_text
    priv_enc = wallet.get("tron_privkey_enc") if wallet else None
    if not priv_enc:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）用户 {uid} 无私钥记录，无法归集")
        return None
    priv_hex = decrypt_text(priv_enc)

    bal = await get_usdt_balance(addr)
    if bal <= 0:
        collect_logger.warning(f"⚠️ 订单 {oid}（{order_no}）准备归集时余额为 0，跳过")
        return None

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        collect_logger.error(f"❌ 归集失败：{e}")
        return None

    await set_recharge_status(oid, "verifying", txid)
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        from decimal import Decimal
        before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
        after = before + Decimal(str(bal))
        await update_wallet_balance(uid, float(after))
        await add_ledger(uid, "recharge", float(bal), float(before), float(after),
                         "recharge_orders", oid, "充值成功")
    return txid, float(bal)

async def step_verifying(uid: int, addr: str, oid: int, order_no: str) -> bool:
    # 已记账 → 直接 success 并通知
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await set_recharge_status(oid, "success", None)
        try:
            lg = await get_ledger_by_ref("recharge", "recharge_orders", oid)
            wallet = await get_wallet(uid)
            if lg and wallet:
                _notify_user(uid, f"✅ 充值成功\n订单号：{order_no}\n到账金额：+{lg['amount']:.2f} USDT\n当前余额：{wallet['usdt_trc20_balance']:.2f} USDT")
        except Exception as e:
            collect_logger.error(f"❌ 通知用户失败：{e}")
        return True
    # 简化验证：余额为 0 视为成功
    bal_after = await get_usdt_balance(addr)
    if bal_after <= 1e-6:
        await set_recharge_status(oid, "success", None)
        try:
            lg = await get_ledger_by_ref("recharge", "recharge_orders", oid)
            wallet = await get_wallet(uid)
            if lg and wallet:
                _notify_user(uid, f"✅ 充值成功\n订单号：{order_no}\n到账金额：+{lg['amount']:.2f} USDT\n当前余额：{wallet['usdt_trc20_balance']:.2f} USDT")
        except Exception as e:
            collect_logger.error(f"❌ 通知用户失败：{e}")
        return True
    return False

async def process_waiting(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    bal = await get_usdt_balance(addr)
    if float(bal) < float(MIN_DEPOSIT_USDT):
        counters["waiting_skip"] += 1; return
    await set_recharge_status(oid, "collecting", None)
    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1

async def process_collecting(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1

async def process_verifying(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    ok = await step_verifying(uid, addr, oid, order_no)
    if ok:
        counters["verifying_to_success"] += 1

async def main_once():
    t0 = time.time()
    counters = {"timeout_marked": 0, "waiting_total": 0, "waiting_skip": 0,
                "collecting_total": 0, "collecting_to_verifying": 0,
                "verifying_total": 0, "verifying_to_success": 0, "ledger_add": 0,
                "rp_auto_refunded": 0, "rp_auto_refunded_sum": 0.0}

    await init_pool()
    try:
        n = await execute_rowcount(EXPIRE_SQL) or 0
        counters["timeout_marked"] = n

        waitings = await list_recharge_waiting(); counters["waiting_total"] = len(waitings)
        for o in waitings:
            try: await process_waiting(o, counters)
            except Exception as e: collect_logger.exception(f"waiting {o.get('id')} 异常：{e}")

        coll = await list_recharge_collecting(); counters["collecting_total"] = len(coll)
        for o in coll:
            try: await process_collecting(o, counters)
            except Exception as e: collect_logger.exception(f"collecting {o.get('id')} 异常：{e}")

        ver = await list_recharge_verifying(); counters["verifying_total"] = len(ver)
        for o in ver:
            try: await process_verifying(o, counters)
            except Exception as e: collect_logger.exception(f"verifying {o.get('id')} 异常：{e}")

        # 🔁 自动回收过期红包（超 24 小时）
        try:
            await _auto_refund_expired_red_packets(counters)
        except Exception as e:
            collect_logger.exception(f"自动回收红包异常：{e}")

        # 对账（异常上锁）
        try:
            user_total = await get_total_user_balance("USDT-trc20")
            agg_bal = await get_usdt_balance(AGGREGATE_ADDRESS)
            if user_total > agg_bal + 1e-6:
                await set_flag("lock_redpkt", "1"); await set_flag("lock_withdraw", "1")
            else:
                await set_flag("lock_redpkt", "0"); await set_flag("lock_withdraw", "0")
        except Exception as e:
            collect_logger.exception(f"对账检查异常：{e}")

        dur = time.time() - t0
        collect_logger.info(
            "📊 本轮统计：expired标记=%s 等待=%s 收集中=%s 待验证=%s "
            "自动回收红包=%s (合计退款=%.6f) 用时%.2fs",
            counters['timeout_marked'], counters['waiting_total'], counters['collecting_total'],
            counters['verifying_total'], counters['rp_auto_refunded'], counters['rp_auto_refunded_sum'], dur
        )
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main_once())

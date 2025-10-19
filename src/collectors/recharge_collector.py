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
from ..logger import collect_logger
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text
from ..services.tron import (
    get_usdt_balance,
    usdt_transfer_all,
    get_account_resource,
    get_trx_balance,
    send_trx,
)

# 将 waiting 且已过期的订单状态置为 timeout（超时），按你要求更直观
EXPIRE_SQL = "UPDATE recharge_orders SET status='timeout' WHERE status='waiting' AND expire_at <= NOW()"

def _safe_notes(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_-]", "", s)

def _notify_user(uid: int, text: str):
    """
    简单通知：直接调用 Telegram Bot API。
    生产上可考虑加入队列/告警系统，这里满足你的“归集成功后提醒用户”的需求。
    """
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
    min_trx_for_bw = float(os.getenv("MIN_TRX_FOR_BANDWIDTH", "1.0"))
    trx_topup_target = float(os.getenv("TRX_TOPUP_TARGET", "2.0"))
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
        res0 = res1
        trx_bal0 = trx_bal1

    if res0['bandwidth'] < need_bw and trx_bal0 < float(os.getenv("MIN_TRX_FOR_BANDWIDTH", "1.0")):
        fee_from = os.getenv("FEE_PAYER_ADDRESS")
        fee_priv = os.getenv("FEE_PAYER_PRIVKEY_HEX")
        if not (fee_from and fee_priv):
            collect_logger.warning(f"⚠️ 带宽不足且 TRX 余额({trx_bal0:.6f})不足，且未配置代付账号")
            return False, usdt_bal

        need_topup = max(0.0, float(os.getenv("TRX_TOPUP_TARGET", "2.0")) - trx_bal0 + 0.1)
        try:
            txid = send_trx(fee_priv, fee_from, addr, need_topup)
            collect_logger.info(f"🪙 代付 TRX {need_topup:.6f} → {addr} 成功，txid={txid}")
            await asyncio.sleep(3)
        except Exception as e:
            collect_logger.error(f"❌ 代付失败：{e}；本轮不归集")
            return False, usdt_bal

        res2 = get_account_resource(addr)
        trx_bal2 = get_trx_balance(addr)
        _log_resource_snapshot(addr, usdt_bal, res2, need_energy, need_bw, trx_bal2, prefix="🔎 资源快照（代付后）")
        if trx_bal2 < float(os.getenv("MIN_TRX_FOR_BANDWIDTH", "1.0")):
            collect_logger.info(f"⏸ 代付后 TRX 余额仍不足：{trx_bal2:.6f}，本轮不归集")
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
                order_notes=_safe_notes(f"order-{order_no}")
            )
            order_id = (resp or {}).get("orderId") or (resp or {}).get("order_id")
            await add_energy_rent_log(addr, oid, order_no, rent_order_id=str(order_id), ttl_seconds=3600)
            collect_logger.info(f"⚡ 能量下单成功：订单 {oid}（{order_no}） id={order_id}")
            await asyncio.sleep(int(os.getenv("TRONGAS_ACTIVATION_DELAY", "8")))
            ok = await _wait_energy_ready(addr, need_energy, timeout=int(os.getenv("TRONGAS_ACTIVATION_DELAY", "30")))
            if not ok:
                collect_logger.warning(f"⚠️ 能量租用已下单但未及时生效，当前 energy={get_account_resource(addr)['energy']}")
        except Exception as e:
            collect_logger.error(f"❌ 能量下单失败：{e}；稍后重试")
    else:
        collect_logger.info(f"⚡ 能量充足或已有有效租单，跳过租能量（剩余 {res['energy']}）")

    res = get_account_resource(addr)
    if res['bandwidth'] < need_bw:
        fee_from = os.getenv("FEE_PAYER_ADDRESS")
        fee_priv = os.getenv("FEE_PAYER_PRIVKEY_HEX")
        topup = float(os.getenv("TOPUP_TRX", "1.2"))
        if fee_from and fee_priv and topup > 0:
            try:
                txid = send_trx(fee_priv, fee_from, addr, topup)
                collect_logger.info(f"🪙 带宽不足，已代付 {topup} TRX → {addr}，txid={txid}")
                await asyncio.sleep(3)
            except Exception as e:
                collect_logger.error(f"❌ TRX 代付失败：{e}；稍后重试")
        else:
            collect_logger.warning(f"⚠️ 带宽不足（{res['bandwidth']} < {need_bw}），且未配置代付账号")
    res2 = get_account_resource(addr)
    collect_logger.info(f"🪙 代付后资源：带宽 {res2['bandwidth']}、能量 {res2['energy']}")

async def _collect_and_book(uid: int, addr: str, oid: int, order_no: str):
    ok, bal = await _precheck_and_prepare(uid, addr, oid, order_no)
    if not ok:
        collect_logger.info(f"⏸ 订单 {oid}（{order_no}）预检未通过，跳过本轮归集")
        return None
    bal = await get_usdt_balance(addr)
    if bal <= 0:
        collect_logger.warning(f"⚠️ 订单 {oid}（{order_no}）准备归集时余额为 0，跳过")
        return None

    await _ensure_resources(addr, oid, order_no)

    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc") if wallet else None
    if not priv_enc:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）用户 {uid} 无私钥记录，无法归集")
        return None
    priv_hex = decrypt_text(priv_enc)

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        emsg = str(e).upper()
        if "BAND" in emsg or "BANDWITH_ERROR" in emsg or "BANDWIDTH" in emsg:
            collect_logger.warning(f"⛽ 首次归集带宽报错，尝试TRX代付后重试：{e}")
            await _ensure_resources(addr, oid, order_no)
            txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
        else:
            collect_logger.error(f"❌ 订单 {oid}（{order_no}）归集转账失败：{e}；保留当前状态待重试")
            return None

    await set_recharge_status(oid, "verifying", txid)
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
        after = before + Decimal(str(bal))
        await update_wallet_balance(uid, float(after))
        await add_ledger(uid, "recharge", float(bal), float(before), float(after),
                         "recharge_orders", oid, "充值成功")
    return txid, float(bal)

async def step_verifying(uid: int, addr: str, oid: int, order_no: str) -> bool:
    # 已记账 → 直接成功（幂等）并通知
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await set_recharge_status(oid, "success", None)
        collect_logger.info(f"✅ 订单 {oid} 已在 ledger 记账：verifying → success")
        # 通知
        try:
            lg = await get_ledger_by_ref("recharge", "recharge_orders", oid)
            wallet = await get_wallet(uid)
            if lg and wallet:
                _notify_user(uid, f"✅ 充值成功\n订单号：{order_no}\n到账金额：+{lg['amount']:.2f} USDT\n当前余额：{wallet['usdt_trc20_balance']:.2f} USDT")
        except Exception as e:
            collect_logger.error(f"❌ 通知用户失败：{e}")
        return True

    after_bal = await get_usdt_balance(addr)

    if after_bal <= 1e-6:
        await set_recharge_status(oid, "success", None)
        collect_logger.info(f"✅ 订单 {oid} 验证通过：verifying → success（余额≈0）")
        # 通知
        try:
            lg = await get_ledger_by_ref("recharge", "recharge_orders", oid)
            wallet = await get_wallet(uid)
            if lg and wallet:
                _notify_user(uid, f"✅ 充值成功\n订单号：{order_no}\n到账金额：+{lg['amount']:.2f} USDT\n当前余额：{wallet['usdt_trc20_balance']:.2f} USDT")
        except Exception as e:
            collect_logger.error(f"❌ 通知用户失败：{e}")
        return True

    if float(after_bal) >= float(MIN_DEPOSIT_USDT):
        collect_logger.info(f"🔄 订单 {oid}（{order_no}）验证期余额仍 {after_bal:.6f} ≥ 阈值 {MIN_DEPOSIT_USDT:.2f}，回退 collecting 并重试归集")
        await set_recharge_status(oid, "collecting", None)
        await _collect_and_book(uid, addr, oid, order_no)
        return False

    collect_logger.warning(f"⚠️ 订单 {oid} 验证仍见余额 {after_bal:.6f}（未达阈值），保持 verifying")
    return False

async def process_waiting(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔎 扫描 waiting 订单：id={oid} no={order_no} user={uid} addr={addr}")

    bal = await get_usdt_balance(addr)
    collect_logger.info(f"📈 地址余额：{addr} = {bal:.6f} USDT（阈值 {MIN_DEPOSIT_USDT:.2f}）")

    if float(bal) < float(MIN_DEPOSIT_USDT):
        collect_logger.info(f"⏳ 订单 {oid} 仍未达最小金额，保持 waiting")
        counters["waiting_skip"] += 1
        return

    await set_recharge_status(oid, "collecting", None)
    collect_logger.info(f"🚚 订单 {oid}（{order_no}）：waiting → collecting")
    counters["to_collecting"] += 1

    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1

async def process_collecting(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔧 续跑 collecting 订单：id={oid} no={order_no} user={uid}")

    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1

async def process_verifying(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔍 续跑 verifying 订单：id={oid} no={order_no} user={uid}")
    ok = await step_verifying(uid, addr, oid, order_no)
    if ok:
        counters["verifying_to_success"] += 1

async def main_once():
    t0 = time.time()
    counters = {
        "waiting_total": 0, "waiting_skip": 0, "to_collecting": 0,
        "collecting_total": 0, "collecting_to_verifying": 0,
        "verifying_total": 0, "verifying_to_success": 0,
        "timeout_marked": 0, "ledger_add": 0
    }

    await init_pool()
    try:
        # 过期订单置为 timeout（精确计数）
        n = await execute_rowcount(EXPIRE_SQL) or 0
        counters["timeout_marked"] = n
        collect_logger.info(f"⌛ 已标记超时订单：waiting→timeout，共 {n} 条")

        # waiting
        waitings = await list_recharge_waiting()
        counters["waiting_total"] = len(waitings)
        for o in waitings:
            try:
                await process_waiting(o, counters)
            except Exception as e:
                collect_logger.exception(f"处理 waiting 订单 {o.get('id')} 异常：{e}")

        # collecting
        collings = await list_recharge_collecting()
        counters["collecting_total"] = len(collings)
        for o in collings:
            try:
                await process_collecting(o, counters)
            except Exception as e:
                collect_logger.exception(f"处理 collecting 订单 {o.get('id')} 异常：{e}")

        # verifying
        verifs = await list_recharge_verifying()
        counters["verifying_total"] = len(verifs)
        for o in verifs:
            try:
                await process_verifying(o, counters)
            except Exception as e:
                collect_logger.exception(f"处理 verifying 订单 {o.get('id')} 异常：{e}")

        # —— 对账检查：用户总余额 vs 归集地址余额 —— #
        try:
            user_total = await get_total_user_balance("USDT-trc20")
            agg_bal = await get_usdt_balance(AGGREGATE_ADDRESS)
            if user_total > agg_bal + 1e-6:
                await set_flag("lock_redpkt", "1")
                await set_flag("lock_withdraw", "1")
                collect_logger.error(f"🚨 对账异常：用户总余额 {user_total:.6f} > 归集地址余额 {agg_bal:.6f}；已锁定 红包/提现")
            else:
                # 正常解锁
                await set_flag("lock_redpkt", "0")
                await set_flag("lock_withdraw", "0")
                collect_logger.info(f"✅ 对账正常：用户总余额 {user_total:.6f} ≤ 归集地址余额 {agg_bal:.6f}")
        except Exception as e:
            collect_logger.exception(f"对账检查异常：{e}")

        dur = time.time() - t0
        collect_logger.info(
            "📊 本轮归集扫描统计：\n"
            f"  • waiting：{counters['waiting_total']}（推进→collecting：{counters['to_collecting']}，未达阈值：{counters['waiting_skip']}）\n"
            f"  • collecting：{counters['collecting_total']}（推进→verifying：{counters['collecting_to_verifying']}）\n"
            f"  • verifying：{counters['verifying_total']}（推进→success：{counters['verifying_to_success']}）\n"
            f"  • 新增账变：{counters['ledger_add']}，标记超时：{counters['timeout_marked']}，用时：{dur:.2f}s"
        )

    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main_once())

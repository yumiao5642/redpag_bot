import asyncio, re, time, os
from decimal import Decimal
from typing import Optional, Tuple
from ..db import init_pool, close_pool
from ..models import (
    list_recharge_waiting, list_recharge_collecting, list_recharge_verifying,
    set_recharge_status, get_wallet, update_wallet_balance, add_ledger, execute,
    ledger_exists_for_ref
)
from ..config import MIN_DEPOSIT_USDT, AGGREGATE_ADDRESS
from ..logger import collect_logger
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text
from ..services.tron import (
    get_usdt_balance,
    usdt_transfer_all,
    get_account_resource,   # ✅ 新增
    send_trx,               # ✅ 新增（带宽不足时代付 TRX 会用到）
)

EXPIRE_SQL = "UPDATE recharge_orders SET status='expired' WHERE status='waiting' AND expire_at <= NOW()"

def _safe_notes(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_-]", "", s)


async def _ensure_resources(addr: str, oid: int, order_no: str) -> None:
    """确保该地址本次归集的 能量+带宽 足够；1小时内不重复租能量；带宽不足自动TRX代付"""
    res = get_account_resource(addr)
    need_energy = int(os.getenv("USDT_ENERGY_REQUIRE", "30000"))
    need_bw = int(os.getenv("MIN_BANDWIDTH", "500"))

    # —— 能量：若不足且 1h 内无有效租单则下单 —— #
    if res['energy'] < need_energy and not await has_active_energy_rent(addr):
        try:
            resp = await rent_energy(
                receive_address=addr,
                pay_nums=max(need_energy - res['energy'], 20000),  # 至少租 20k
                rent_time=1,
                order_notes=_safe_notes(f"order-{order_no}")
            )
            order_id = (resp or {}).get("order_id")
            await add_energy_rent_log(addr, oid, order_no, rent_order_id=str(order_id), ttl_seconds=3600)
            collect_logger.info(f"⚡ 能量下单成功：订单 {oid}（{order_no}） id={order_id}")
            await asyncio.sleep(int(os.getenv("TRONGAS_ACTIVATION_DELAY", "8")))
            ok = await _wait_energy_ready(addr, need_energy, timeout=int(os.getenv("TRONGAS_ACTIVATION_DELAY", "30")))
            if not ok:
                collect_logger.warning(f"⚠️ 能量租用已下单但未及时生效，当前 energy={get_account_resource(addr)['energy']}")

        except Exception as e:
            collect_logger.error(f"❌ 能量下单失败：{e}；稍后重试")
            # 不抛出，继续检查带宽，下一轮会再试
    else:
        collect_logger.info(f"⚡ 能量充足或已有有效租单，跳过租能量（剩余 {res['energy']}）")

    # —— 带宽：若不足，尝试 TRX 代付 —— #
    res = get_account_resource(addr)  # 再查一次
    if res['bandwidth'] < need_bw:
        fee_from = os.getenv("FEE_PAYER_ADDRESS")
        fee_priv = os.getenv("FEE_PAYER_PRIVKEY_HEX")
        topup = float(os.getenv("TOPUP_TRX", "1.2"))
        if fee_from and fee_priv and topup > 0:
            try:
                txid = send_trx(fee_priv, fee_from, addr, topup)
                collect_logger.info(f"🪙 带宽不足，已从 {fee_from} 代付 {topup} TRX → {addr}，txid={txid}")
                await asyncio.sleep(3)  # 让余额可见
            except Exception as e:
                collect_logger.error(f"❌ TRX 代付失败：{e}；稍后重试")
        else:
            collect_logger.warning(f"⚠️ 带宽不足（{res['bandwidth']} < {need_bw}），且未配置代付账号，可能导致 BANDWIDTH_ERROR")
    # 代付之后
    res2 = get_account_resource(addr)
    collect_logger.info(f"🪙 代付后资源：带宽 {res2['bandwidth']}、能量 {res2['energy']}")


async def _wait_energy_ready(addr: str, need: int, timeout: int = 30):
    end = time.time() + timeout
    while time.time() < end:
        res = get_account_resource(addr)
        if res['energy'] >= need:
            return True
        await asyncio.sleep(2)
    return False

async def _collect_and_book(uid: int, addr: str, oid: int, order_no: str):
    """
    1) 先确保资源（能量+带宽）
    2) 发起 USDT 全额转账到归集地址
    3) 置 verifying；记账（含幂等）
    """
    bal = await get_usdt_balance(addr)
    if bal <= 0:
        collect_logger.warning(f"⚠️ 订单 {oid}（{order_no}）准备归集时余额为 0，跳过")
        return None

    # 先确保资源
    await _ensure_resources(addr, oid, order_no)

    # 私钥
    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc")
    if not priv_enc:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）用户 {uid} 无私钥记录，无法归集")
        return None
    priv_hex = decrypt_text(priv_enc)

    # 尝试归集；如因带宽报错，进行一次“代付后重试”
    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        emsg = str(e).upper()
        if "BAND" in emsg or "BANDWITH_ERROR" in emsg or "BANDWIDTH" in emsg:
            collect_logger.warning(f"⛽ 首次归集带宽报错，尝试TRX代付后重试：{e}")
            await _ensure_resources(addr, oid, order_no)  # 里面会做代付
            txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
        else:
            collect_logger.error(f"❌ 订单 {oid}（{order_no}）归集转账失败：{e}；保留当前状态待重试")
            return None

    # —— 推进状态 & 记账（与你现有逻辑一致，略） —— #
    await set_recharge_status(oid, "verifying", txid)
    # 幂等记账
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
        after = before + Decimal(str(bal))
        await update_wallet_balance(uid, float(after))
        await add_ledger(uid, "recharge", float(bal), float(before), float(after),
                         "recharge_orders", oid, "充值成功")
    return txid, float(bal)

async def step_verifying(uid: int, addr: str, oid: int, order_no: str) -> bool:
    """
    verifying 步骤策略：
    - 若 ledger 已存在 → 直接 success（幂等）
    - 否则读取余额：
        * 余额≈0 → 标记 success
        * 余额 >= MIN_DEPOSIT_USDT → 回退到 collecting 并立即触发归集（租能量+转账+记账），仍保持 verifying 等下一轮确认
        * 余额 > 0 但 < 阈值 → 保持 verifying（下轮继续看）
    返回：是否已经 success
    """
    # 已记账 → 直接成功（幂等）
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await set_recharge_status(oid, "success", None)
        collect_logger.info(f"✅ 订单 {oid} 已在 ledger 记账：verifying → success")
        return True

    after_bal = await get_usdt_balance(addr)

    # 清零 → 成功
    if after_bal <= 0.000001:
        await set_recharge_status(oid, "success", None)
        collect_logger.info(f"✅ 订单 {oid} 验证通过：verifying → success（余额≈0）")
        return True

    # 未清零，但达到阈值 → 回退并再次归集
    if float(after_bal) >= float(MIN_DEPOSIT_USDT):
        collect_logger.info(f"🔄 订单 {oid}（{order_no}）验证期余额仍 {after_bal:.6f} ≥ 阈值 {MIN_DEPOSIT_USDT:.2f}，回退 collecting 并重试归集")
        await set_recharge_status(oid, "collecting", None)
        await _collect_and_book(uid, addr, oid, order_no)
        # 归集后仍保持 verifying，等待下一轮确认清零
        return False

    # 小额残留（< 阈值），先保持 verifying
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

    # 统一归集 + 记账
    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1  # 记账在 _collect_and_book 内做了幂等，这里统计一下

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
        "expired_to_closed": 0, "ledger_add": 0
    }

    await init_pool()
    try:
        # 过期订单置为 expired
        n = await execute(EXPIRE_SQL) or 0
        counters["expired_to_closed"] = n
        collect_logger.info(f"⌛ 已处理超时订单：waiting→expired，共 {n} 条")

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

        # 汇总
        dur = time.time() - t0
        collect_logger.info(
            "📊 本轮归集扫描统计：\n"
            f"  • waiting：{counters['waiting_total']}（推进→collecting：{counters['to_collecting']}，未达阈值：{counters['waiting_skip']}）\n"
            f"  • collecting：{counters['collecting_total']}（推进→verifying：{counters['collecting_to_verifying']}）\n"
            f"  • verifying：{counters['verifying_total']}（推进→success：{counters['verifying_to_success']}）\n"
            f"  • 新增账变：{counters['ledger_add']}，本轮过期关闭：{counters['expired_to_closed']}，用时：{dur:.2f}s"
        )

    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main_once())

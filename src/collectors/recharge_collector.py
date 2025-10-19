import os
import re
import asyncio
import time
from decimal import Decimal
from typing import Tuple

from telegram import Bot

from ..config import AGGREGATE_ADDRESS, MIN_DEPOSIT_USDT, USDT_CONTRACT, BOT_TOKEN
from ..db import close_pool, init_pool
from ..models import (
    add_ledger,
    ledger_exists_for_ref,
    set_flag,
    set_recharge_status,
    sum_user_usdt_balance,
    get_wallet,
    update_wallet_balance,
    list_recharge_waiting,
    list_recharge_collecting,
    list_recharge_verifying,
    get_ledger_amount_by_ref,
)
from ..db import execute
from ..services.energy import rent_energy
from ..services.tron import (
    get_account_resource,
    get_trc20_balance,
    get_usdt_balance,
    get_trx_balance,
    send_trx,
    usdt_transfer_all,
)
from ..services.encryption import decrypt_text
from ..logger import collect_logger

bot = Bot(BOT_TOKEN)


async def _notify_success(user_id: int, order_no: str, amt: float, new_bal: float):
    txt = (
        f"✅ 充值成功\n"
        f"订单号：`{order_no}`\n"
        f"到账金额：**{amt:.2f} USDT**\n"
        f"当前余额：**{new_bal:.2f} USDT**"
    )
    await bot.send_message(chat_id=user_id, text=txt, parse_mode="Markdown")


async def _reconcile_and_lock():
    # 聚合地址余额 vs 用户总余额
    agg = get_trc20_balance(AGGREGATE_ADDRESS, USDT_CONTRACT)
    total = await sum_user_usdt_balance()
    # 规则：总余额 <= 聚合余额 为正常，否则锁功能
    need_lock = total > agg + 1e-8
    await set_flag("lock_withdraw", need_lock)
    await set_flag("lock_redpacket", need_lock)


EXPIRE_SQL = "UPDATE recharge_orders SET status='expired' WHERE status='waiting' AND expire_at <= NOW()"


def _safe_notes(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_-]", "", s)


async def _wait_energy_ready(
    addr: str, need_energy: int, timeout: int = None, poll_interval: int = None
) -> bool:
    """
    轮询等待能量生效：直到能量 >= need_energy 或等待达到 timeout。
    - timeout 从环境变量 TRONGAS_ACTIVATION_DELAY 读（默认 30s）
    - poll_interval 从环境变量 TRONGAS_POLL_INTERVAL 读（默认 3s）
    """
    timeout = (
        int(os.getenv("TRONGAS_ACTIVATION_DELAY", "30"))
        if timeout is None
        else int(timeout)
    )
    poll_interval = (
        int(os.getenv("TRONGAS_POLL_INTERVAL", "3"))
        if poll_interval is None
        else int(poll_interval)
    )

    start = time.monotonic()
    # 先打一次快照
    res = get_account_resource(addr)
    if res.get("energy", 0) >= need_energy:
        return True

    while True:
        elapsed = time.monotonic() - start
        if elapsed >= timeout:
            return False

        left = min(poll_interval, max(1, timeout - int(elapsed)))
        await asyncio.sleep(left)

        # 重查资源
        res = get_account_resource(addr)
        if res.get("energy", 0) >= need_energy:
            return True


def _log_resource_snapshot(
    addr: str,
    usdt_bal: float,
    res: dict,
    need_energy: int,
    need_bw: int,
    trx_bal: float,
    prefix: str = "🔎 资源快照",
):
    collect_logger.info(
        f"{prefix}：\n"
        f"  • 地址：{addr}\n"
        f"  • USDT余额：{usdt_bal:.6f}\n"
        f"  • 能量：{res['energy']} / 需要 {need_energy}\n"
        f"  • 带宽：{res['bandwidth']} / 建议 {need_bw}\n"
        f"  • TRX余额：{trx_bal:.6f}"
    )


async def _precheck_and_prepare(
    uid: int, addr: str, oid: int, order_no: str
) -> Tuple[bool, float]:
    need_energy = int(os.getenv("USDT_ENERGY_REQUIRE", "90000"))
    need_bw = int(os.getenv("MIN_BANDWIDTH", "800"))
    min_deposit = float(os.getenv("MIN_DEPOSIT_USDT", "10"))
    min_trx_for_bw = float(os.getenv("MIN_TRX_FOR_BANDWIDTH", "1.0"))
    trx_topup_target = float(os.getenv("TRX_TOPUP_TARGET", "2.0"))
    rent_retry_sec = int(os.getenv("ENERGY_RENT_RETRY_SECONDS", "120"))

    # 余额
    usdt_bal = await get_usdt_balance(addr)
    res0 = get_account_resource(addr)
    trx_bal0 = get_trx_balance(addr)
    _log_resource_snapshot(
        addr,
        usdt_bal,
        res0,
        need_energy,
        need_bw,
        trx_bal0,
        prefix="🔎 资源快照（预检前）",
    )

    if usdt_bal < min_deposit:
        collect_logger.info(
            f"⏸ USDT不足：{usdt_bal:.6f} < {min_deposit:.2f}，本轮不归集"
        )
        return False, usdt_bal

    # —— 能量保障：不足就租 —— #
    # （略：保留你原来的逻辑，可接在这里）
    return True, usdt_bal


async def _ensure_resources(addr: str, oid: int, order_no: str) -> None:
    """确保该地址本次归集的 能量+带宽 足够；带宽不足自动TRX代付（省略重试细节）"""
    res = get_account_resource(addr)
    need_energy = int(os.getenv("USDT_ENERGY_REQUIRE", "30000"))
    need_bw = int(os.getenv("MIN_BANDWIDTH", "500"))

    if res["energy"] < need_energy:
        try:
            await rent_energy(receive_address=addr, pay_nums=max(need_energy - res["energy"], 20000), rent_time=1, order_notes=f"order-{order_no}")
            await _wait_energy_ready(addr, need_energy)
        except Exception as e:
            collect_logger.error(f"❌ 能量下单失败：{e}；稍后重试")

    res = get_account_resource(addr)
    if res["bandwidth"] < need_bw:
        fee_from = os.getenv("FEE_PAYER_ADDRESS")
        fee_priv = os.getenv("FEE_PAYER_PRIVKEY_HEX")
        topup = float(os.getenv("TOPUP_TRX", "1.2"))
        if fee_from and fee_priv and topup > 0:
            try:
                txid = send_trx(fee_priv, fee_from, addr, topup)
                collect_logger.info(f"🪙 代付 {topup} TRX → {addr} 成功，txid={txid}")
                await asyncio.sleep(3)
            except Exception as e:
                collect_logger.error(f"❌ TRX 代付失败：{e}")


async def _collect_and_book(uid: int, addr: str, oid: int, order_no: str):
    ok, bal = await _precheck_and_prepare(uid, addr, oid, order_no)
    if not ok:
        return None
    bal = await get_usdt_balance(addr)
    if bal <= 0:
        return None

    await _ensure_resources(addr, oid, order_no)

    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc") if wallet else None
    if not priv_enc:
        collect_logger.error(f"❌ 用户 {uid} 无私钥记录，无法归集")
        return None
    priv_hex = decrypt_text(priv_enc)

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        collect_logger.error(f"❌ 归集转账失败：{e}")
        return None

    await set_recharge_status(oid, "verifying", txid)

    # 幂等记账
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        before = Decimal(str(wallet["usdt_trc20_balance"] or 0)) if wallet else Decimal("0")
        after = before + Decimal(str(bal))
        await update_wallet_balance(uid, float(after))
        # 兼容老调用：ref_type 留空则用 change_type
        await add_ledger(
            uid,
            "recharge",
            float(bal),
            float(before),
            float(after),
            "recharge_orders",
            oid,
            "充值成功",
        )
    return txid, float(bal)


async def step_verifying(uid: int, addr: str, oid: int, order_no: str) -> bool:
    """
    verifying 步骤策略：
    - 若 ledger 已存在 → 直接 success（幂等）
    - 否则读取余额判断是否需要回退/重试
    """
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await set_recharge_status(oid, "success", None)
        # 通知到账 + 对账
        credited_amt = await get_ledger_amount_by_ref("recharge", "recharge_orders", oid)
        w = await get_wallet(uid)
        new_balance = float((w or {}).get("usdt_trc20_balance") or 0)
        await _notify_success(uid, order_no, credited_amt, new_balance)
        await _reconcile_and_lock()
        return True

    after_bal = await get_usdt_balance(addr)
    if after_bal <= 0.000001:
        await set_recharge_status(oid, "success", None)
        return True

    if float(after_bal) >= float(MIN_DEPOSIT_USDT):
        await set_recharge_status(oid, "collecting", None)
        await _collect_and_book(uid, addr, oid, order_no)
        return False

    return False


async def process_waiting(order, counters):
    oid = order["id"]
    uid = order["user_id"]
    addr = order["address"]
    order_no = order.get("order_no") or str(oid)

    bal = await get_usdt_balance(addr)
    if float(bal) < float(MIN_DEPOSIT_USDT):
        counters["waiting_skip"] += 1
        return

    await set_recharge_status(oid, "collecting", None)
    counters["to_collecting"] += 1

    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1


async def process_collecting(order, counters):
    oid = order["id"]
    uid = order["user_id"]
    addr = order["address"]
    order_no = order.get("order_no") or str(oid)

    ret = await _collect_and_book(uid, addr, oid, order_no)
    if ret is not None:
        counters["collecting_to_verifying"] += 1
        counters["ledger_add"] += 1


async def process_verifying(order, counters):
    oid = order["id"]
    uid = order["user_id"]
    addr = order["address"]
    order_no = order.get("order_no") or str(oid)

    ok = await step_verifying(uid, addr, oid, order_no)
    if ok:
        counters["verifying_to_success"] += 1


async def main_once():
    t0 = time.time()
    counters = {
        "waiting_total": 0,
        "waiting_skip": 0,
        "to_collecting": 0,
        "collecting_total": 0,
        "collecting_to_verifying": 0,
        "verifying_total": 0,
        "verifying_to_success": 0,
        "expired_to_closed": 0,
        "ledger_add": 0,
    }

    await init_pool()
    try:
        # 过期订单置为 expired
        n = await execute(EXPIRE_SQL) or 0
        counters["expired_to_closed"] = n

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

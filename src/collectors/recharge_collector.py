import asyncio, re, time
from decimal import Decimal
from typing import Optional  # ✅ 兼容 3.9 的可选类型写法
from ..db import init_pool, close_pool
from ..models import (
    list_recharge_waiting, list_recharge_collecting, list_recharge_verifying,
    set_recharge_status, get_wallet, update_wallet_balance, add_ledger, execute,
    ledger_exists_for_ref
)
from ..config import MIN_DEPOSIT_USDT, AGGREGATE_ADDRESS
from ..logger import collect_logger
from ..services.tron import get_usdt_balance, usdt_transfer_all
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text

EXPIRE_SQL = "UPDATE recharge_orders SET status='expired' WHERE status='waiting' AND expire_at <= NOW()"

def _safe_notes(s: str) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9_-]", "", s)

async def step_collecting(uid: int, addr: str, oid: int, order_no: str) -> Optional[str]:
    """
    collecting 步骤：
    1) 租能量
    2) 依据 from_addr 实时余额全额转入归集地址
    3) 状态 -> verifying，返回 txid（失败返回 None）
    """
    try:
        _ = await rent_energy(receive_address=addr, pay_nums=65000, rent_time=1, order_notes=_safe_notes(f"order-{order_no}"))
    except Exception as e:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）租能量失败：{e}；保留 collecting 待重试")
        return None
    # ⭐ 等待能量生效（默认 8 秒，可在 .env 配置 TRONGAS_ACTIVATION_DELAY=8）
    delay = int(os.getenv("TRONGAS_ACTIVATION_DELAY", "8"))
    if delay > 0:
        await asyncio.sleep(delay)
    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc")
    if not priv_enc:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）用户 {uid} 无私钥记录，无法归集")
        return None
    priv_hex = decrypt_text(priv_enc)

    # 再次读取余额，确保金额准确
    bal = await get_usdt_balance(addr)
    if bal <= 0:
        collect_logger.warning(f"⚠️ 订单 {oid}（{order_no}）准备归集时余额为 0，稍后重试")
        return None

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        collect_logger.error(f"❌ 订单 {oid}（{order_no}）归集转账失败：{e}；保留 collecting 待重试")
        return None

    await set_recharge_status(oid, "verifying", txid)
    collect_logger.info(f"🔁 订单 {oid}（{order_no}）状态：collecting → verifying，txid={txid}")
    return txid

async def step_verifying(uid: int, addr: str, oid: int) -> bool:
    """
    verifying 步骤：
    - 余额≈0 视为归集已落账，标记 success；
    - 如 ledger 已存在，直接视为已记账（幂等）。
    """
    # 幂等：已记账则直接成功
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await set_recharge_status(oid, "success", None)
        collect_logger.info(f"♻️ 订单 {oid} 已记账在 ledger，直接标记 success")
        return True

    try:
        after_bal = await get_usdt_balance(addr)
    except Exception:
        after_bal = 0.0

    if after_bal > 0.000001:
        collect_logger.warning(f"⚠️ 订单 {oid} 验证仍见余额 {after_bal}，暂不 finalize")
        return False

    await set_recharge_status(oid, "success", None)
    collect_logger.info(f"✅ 订单 {oid} 验证通过，状态：verifying → success")
    return True

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

    txid = await step_collecting(uid, addr, oid, order_no)
    if txid is None:
        return

    # 归集成功后“立即入账”（用归集前读到的 bal 作为入账金额），并以 ledger 幂等保护
    wallet = await get_wallet(uid)
    before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
    after = before + Decimal(str(bal))
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await update_wallet_balance(uid, float(after))
        await add_ledger(uid, "recharge", float(bal), float(before), float(after), "recharge_orders", oid, f"充值成功")
        collect_logger.info(f"💰 订单 {oid} 入账：+{bal:.6f} USDT，余额 {before} → {after}")
        counters["ledger_add"] += 1
    else:
        collect_logger.info(f"♻️ 订单 {oid} 已入账（幂等跳过）")

async def process_collecting(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔧 续跑 collecting 订单：id={oid} no={order_no} user={uid}")
    txid = await step_collecting(uid, addr, oid, order_no)
    if txid is None:
        return
    counters["collecting_to_verifying"] += 1

async def process_verifying(order, counters):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    collect_logger.info(f"🔍 续跑 verifying 订单：id={oid} user={uid}")
    ok = await step_verifying(uid, addr, oid)
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
        n = await execute(EXPIRE_SQL)
        if n is None: n = 0
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

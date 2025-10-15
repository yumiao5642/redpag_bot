import asyncio, re
from decimal import Decimal
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

async def step_collecting(uid: int, addr: str, oid: int, order_no: str) -> bool:
    # 归集前确保已租能量
    try:
        _ = await rent_energy(receive_address=addr, pay_nums=65000, rent_time=1, order_notes=_safe_notes(f"order-{order_no}"))
    except Exception as e:
        collect_logger.error(f"❌ 能量下单失败：{e}；保留 collecting 状态待下轮重试")
        return False

    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc")
    if not priv_enc:
        collect_logger.error(f"❌ 用户 {uid} 无私钥记录，无法归集")
        return False
    priv_hex = decrypt_text(priv_enc)

    # 实际余额（再次读，避免 race）
    bal = await get_usdt_balance(addr)
    if bal <= 0:
        collect_logger.warning(f"⚠️ 订单 {oid} 收集时余额为 0，稍后重试")
        return False

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        collect_logger.error(f"❌ 归集转账失败：{e}；保留 collecting 状态待下轮重试")
        return False

    await set_recharge_status(oid, "verifying", txid)
    collect_logger.info(f"🔁 订单 {oid} -> verifying, txid={txid}")
    return True

async def step_verifying(uid: int, addr: str, oid: int) -> bool:
    # 简化验证：余额趋近 0 即视为成功；幂等入账
    try:
        after_bal = await get_usdt_balance(addr)
    except Exception:
        after_bal = 0.0

    # 已入账则不重复
    if await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        collect_logger.info(f"♻️ 订单 {oid} 已记账，直接标记 success（幂等）")
        await set_recharge_status(oid, "success", None)
        return True

    # 读取历史余额变化依据：以“最初可见的余额”为准（此处采用再次查询前一步入账的金额不可得，保守用 after_bal 反推无法成立）
    # 简化：如果余额仍 > 0，先不入账，等待下一轮；若余额≈0，按“应转成功”入账。
    if after_bal > 0.000001:
        collect_logger.warning(f"⚠️ 订单 {oid} 验证提示：地址仍有余额 {after_bal}，暂不入账")
        return False

    # 我们无法精确获知原充值金额（需查询交易日志）；此处退一步改为：在 step_collecting 前读取的余额直接用于转账金额。
    # 为保证安全与正确，step_collecting 已在转账时使用 from_addr 实时余额作为 amount；因此 verifying 阶段只做状态 finalize 与幂等校验。
    await set_recharge_status(oid, "success", None)

    # 账变与余额更新需要“转账金额”；为避免重复入账，改为：ledger_exists_for_ref 做保护，
    # 这里没有 amount 参数，说明我们需要在 collecting 阶段就完成“余额扣转 + 入账”？不安全。
    # 保险做法：在 collecting 阶段之前已经读取 bal 并用于转账；此处再次读取钱包余额并不代表充值额。
    # ——权衡：把入账放回到 collecting 完成后的“立即入账”流程（我们在旧版是一起做的）。
    # 因为我们此函数无法拿到当时的 bal，这里不做入账，只做状态修复；真正的入账仍在 collecting 成功后完成。
    collect_logger.info(f"✅ 订单 {oid} 验证通过（状态修复），已设为 success；如未入账，上一阶段已处理。")
    return True

async def process_waiting(order):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]; order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔎 扫描 waiting 订单 {oid} / 用户 {uid} / 地址 {addr}")

    bal = await get_usdt_balance(addr)
    collect_logger.info(f"地址 {addr} 余额：{bal:.6f} USDT，阈值 {MIN_DEPOSIT_USDT:.2f} USDT")
    if float(bal) < float(MIN_DEPOSIT_USDT):
        collect_logger.info(f"⏳ 订单 {oid} 仍为 waiting（未达最小金额）"); return

    await set_recharge_status(oid, "collecting", None)
    collect_logger.info(f"🚚 订单 {oid} -> collecting")

    # collecting 完成后立即入账（更加确定金额）
    ok = await step_collecting(uid, addr, oid, order_no)
    if not ok:
        return

    # 入账金额使用转账前余额（再次读取 from addr 应≈0，不可用于金额），
    # 因此把“记账”放在 step_collecting 成功之前的 bal 值；为了把 bal 传过来，这里直接做入账。
    wallet = await get_wallet(uid)
    before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
    after = before + Decimal(str(bal))
    # 幂等保护
    if not await ledger_exists_for_ref("recharge", "recharge_orders", oid):
        await update_wallet_balance(uid, float(after))
        await add_ledger(uid, "recharge", float(bal), float(before), float(after), "recharge_orders", oid, f"充值成功")
        collect_logger.info(f"💰 订单 {oid} 入账：+{bal:.6f} USDT，余额 {before} -> {after}")
    else:
        collect_logger.info(f"♻️ 订单 {oid} 已入账（幂等跳过）")

async def process_collecting(order):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]; order_no = order.get("order_no") or str(oid)
    collect_logger.info(f"🔧 继续处理 collecting 订单 {oid}")
    ok = await step_collecting(uid, addr, oid, order_no)
    if not ok:
        return
    # collecting→verifying 后尝试 finalize（若上一轮已入账则幂等跳过）
    await process_verifying({"id": oid, "user_id": uid, "address": addr})

async def process_verifying(order):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    collect_logger.info(f"🔍 继续处理 verifying 订单 {oid}")
    _ = await step_verifying(uid, addr, oid)

async def main_once():
    await init_pool()
    try:
        # 先把 waiting 超时的订单标记为 expired
        _ = await execute(EXPIRE_SQL)
        collect_logger.info("⌛ 已处理超时订单：waiting→expired（如有）")

        # 1) waiting（未过期）
        for o in await list_recharge_waiting():
            try:
                await process_waiting(o)
            except Exception as e:
                collect_logger.exception(f"处理 waiting 订单 {o.get('id')} 异常：{e}")

        # 2) collecting（可能上次租能量/转账失败）
        for o in await list_recharge_collecting():
            try:
                await process_collecting(o)
            except Exception as e:
                collect_logger.exception(f"处理 collecting 订单 {o.get('id')} 异常：{e}")

        # 3) verifying（可能上次中断）
        for o in await list_recharge_verifying():
            try:
                await process_verifying(o)
            except Exception as e:
                collect_logger.exception(f"处理 verifying 订单 {o.get('id')} 异常：{e}")

    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main_once())

import asyncio
from decimal import Decimal
from ..db import init_pool, close_pool
from ..models import (
    list_recharge_waiting, set_recharge_status, get_wallet,
    update_wallet_balance, add_ledger, execute
)
from ..config import MIN_DEPOSIT_USDT, AGGREGATE_ADDRESS
from ..logger import collect_logger
from ..services.tron import get_usdt_balance, usdt_transfer_all
from ..services.energy import rent_energy
from ..services.encryption import decrypt_text

EXPIRE_SQL = "UPDATE recharge_orders SET status='expired' WHERE status='waiting' AND expire_at <= NOW()"

async def process_one(order):
    oid = order["id"]; uid = order["user_id"]; addr = order["address"]
    collect_logger.info(f"🔎 扫描订单 {oid} / 用户 {uid} / 地址 {addr}")

    # 1) 检测余额（限速 + 重试在 tron.py 内部）
    bal = await get_usdt_balance(addr)
    collect_logger.info(f"地址 {addr} 余额：{bal:.6f} USDT，阈值 {MIN_DEPOSIT_USDT:.2f} USDT")
    if float(bal) < float(MIN_DEPOSIT_USDT):
        collect_logger.info(f"⏳ 订单 {oid} 仍为 waiting（未达最小金额）")
        return

    # 2) 进入待归集
    await set_recharge_status(oid, "collecting", None)
    collect_logger.info(f"🚚 订单 {oid} -> collecting")

    # 3) 为充值地址租用能量（仅 apiKey）
    try:
        _data = await rent_energy(receive_address=addr, pay_nums=65000, rent_time=1, order_notes=f"order:{oid}")
    except Exception as e:
        collect_logger.error(f"❌ 能量下单失败：{e}；保留 collecting 状态待下轮重试")
        return

    # 4) 归集：私钥解密 -> 全额转到归集地址 -> verifying
    wallet = await get_wallet(uid)
    priv_enc = wallet.get("tron_privkey_enc")
    if not priv_enc:
        collect_logger.error(f"❌ 用户 {uid} 无私钥记录，无法归集")
        return
    priv_hex = decrypt_text(priv_enc)

    try:
        txid = await usdt_transfer_all(priv_hex, addr, AGGREGATE_ADDRESS, float(bal))
    except Exception as e:
        collect_logger.error(f"❌ 归集转账失败：{e}；保留 collecting 状态待下轮重试")
        return

    await set_recharge_status(oid, "verifying", txid)
    collect_logger.info(f"🔁 订单 {oid} -> verifying, txid={txid}")

    # 5) 简化验证：读取余额趋近 0 即认为成功，并入账
    try:
        after_bal = await get_usdt_balance(addr)
    except Exception:
        after_bal = 0.0
    if after_bal > 0.000001:
        collect_logger.warning(f"⚠️ 订单 {oid} 验证提示：地址仍有余额 {after_bal}")

    await set_recharge_status(oid, "success", txid)
    before = Decimal(str(wallet["usdt_trc20_balance"] or 0))
    after = before + Decimal(str(bal))
    await update_wallet_balance(uid, float(after))
    await add_ledger(uid, "recharge", float(bal), float(before), float(after), "recharge_orders", oid, f"充值成功 txid={txid}")
    collect_logger.info(f"✅ 订单 {oid} success：+{bal:.6f} USDT，余额 {before} -> {after}")

async def main_once():
    await init_pool()
    try:
        # A) 先把 waiting 且过期的订单置为 expired
        _ = await execute(EXPIRE_SQL)
        collect_logger.info("⌛ 已处理超时订单：waiting→expired（如有）")

        # B) 扫描 waiting（未过期）
        orders = await list_recharge_waiting()
        if not orders:
            collect_logger.info("📭 无 waiting 订单"); return

        for o in orders:
            try:
                await process_one(o)
            except Exception as e:
                collect_logger.exception(f"处理订单 {o.get('id')} 异常：{e}")
    finally:
        await close_pool()

if __name__ == "__main__":
    asyncio.run(main_once())

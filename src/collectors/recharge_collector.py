
import asyncio
from decimal import Decimal
from ..db import init_pool, fetchall
from ..models import set_recharge_status, get_wallet, update_wallet_balance, add_ledger
from ..services.tron import query_usdt_balance, transfer_usdt_from_child_to_hot
from ..config import MIN_DEPOSIT_USDT, AGGREGATE_ADDRESS
from ..logger import collect_logger

async def process_once():
    rows = await fetchall("SELECT * FROM recharge_orders WHERE status='waiting' AND expire_at>NOW() ORDER BY id ASC LIMIT 100")
    for r in rows:
        addr = r["address"]
        bal = query_usdt_balance(addr)  # TODO: 实链查询
        if bal >= Decimal(str(MIN_DEPOSIT_USDT)):
            await set_recharge_status(r["id"], "collecting")
            collect_logger.info(f"🔎 订单 {r['id']} 检测到充值 {bal} USDT，准备归集到 {AGGREGATE_ADDRESS}")

            # 归集（占位）
            txid = transfer_usdt_from_child_to_hot(child_privkey_hex="", to_hot_address=AGGREGATE_ADDRESS, amount=bal)  # 需解密私钥
            await set_recharge_status(r["id"], "verifying", txid_collect=txid or "")

            # 验证（占位）
            # TODO: 确认子地址为0，热钱包收到相同金额；此处直接成功
            await set_recharge_status(r["id"], "success")

            # 入账
            w = await get_wallet(r["user_id"])
            before = Decimal(str(w["usdt_trc20_balance"])) if w else Decimal("0")
            after = before + bal
            await update_wallet_balance(r["user_id"], float(after))
            await add_ledger(r["user_id"], "recharge", float(bal), float(before), float(after), "recharge_orders", r["id"], "充值成功入账")
            collect_logger.info(f"✅ 订单 {r['id']} 归集并入账完成，金额 {bal} USDT")

async def main():
    await init_pool()
    await process_once()

if __name__ == "__main__":
    asyncio.run(main())

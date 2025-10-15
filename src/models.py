from typing import List, Optional, Dict, Any, Tuple
from .db import fetchone, fetchall, execute
from datetime import datetime, timedelta
import random, string

# === 充值订单 ===

def _rand_letters(n=4) -> str:
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(n))

def make_order_no(dt: Optional[datetime] = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime('%Y%m%d%H%M') + _rand_letters(4)  # 形如 202510151945abcd

async def get_active_recharge_order(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM recharge_orders WHERE user_id=%s AND status='waiting' AND expire_at>NOW() ORDER BY id DESC LIMIT 1",
        (user_id,)
    )

async def create_recharge_order(user_id: int, address: str, expected_amount: Optional[float], expire_minutes: int) -> int:
    order_no = make_order_no()
    # created_at=NOW(), expire_at=NOW()+INTERVAL %s MINUTE
    sql = ("INSERT INTO recharge_orders(order_no, user_id, address, expected_amount, status, created_at, expire_at) "
           "VALUES(%s,%s,%s,%s,'waiting',NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE))")
    new_id = await execute(sql, (order_no, user_id, address, expected_amount, expire_minutes))
    return new_id

async def get_recharge_order(order_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM recharge_orders WHERE id=%s", (order_id,))

async def list_recharge_waiting() -> List[Dict[str, Any]]:
    return await fetchall("SELECT * FROM recharge_orders WHERE status='waiting' AND expire_at>NOW() ORDER BY id ASC LIMIT 100", ())

async def set_recharge_status(order_id: int, status: str, txid: Optional[str]):
    await execute("UPDATE recharge_orders SET status=%s, txid=%s, updated_at=NOW() WHERE id=%s", (status, txid, order_id))

# === 用户/钱包/账变（已存在的接口，留存给调用方） ===
async def ensure_user(user_id: int, username: str, first_name: str, last_name: str):
    await execute("INSERT IGNORE INTO users(id, username, first_name, last_name, created_at) VALUES(%s,%s,%s,%s,NOW())",
                  (user_id, username, first_name, last_name))

async def get_wallet(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM user_wallets WHERE user_id=%s", (user_id,))

async def set_tron_wallet(user_id: int, address: str, privkey_enc: str):
    await execute("INSERT INTO user_wallets(user_id, tron_address, tron_privkey_enc, usdt_trc20_balance) "
                  "VALUES(%s,%s,%s,0) ON DUPLICATE KEY UPDATE tron_address=VALUES(tron_address), tron_privkey_enc=VALUES(tron_privkey_enc)",
                  (user_id, address, privkey_enc))

async def update_wallet_balance(user_id: int, new_bal: float):
    await execute("UPDATE user_wallets SET usdt_trc20_balance=%s WHERE user_id=%s", (new_bal, user_id))

async def add_ledger(user_id: int, change_type: str, amount: float, bal_before: float, bal_after: float,
                     ref_table: str, ref_id: int, remark: str):
    await execute(
        "INSERT INTO ledger(user_id, change_type, amount, balance_before, balance_after, ref_table, ref_id, remark, created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        (user_id, change_type, amount, bal_before, bal_after, ref_table, ref_id, remark)
    )

# === 红包相关/地址簿等接口（此处略） ===
async def list_ledger_recent(user_id: int, limit: int=10) -> List[Dict[str, Any]]:
    return await fetchall("SELECT * FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, limit))

async def list_user_addresses(user_id: int) -> List[Dict[str, Any]]:
    return await fetchall("SELECT * FROM user_addresses WHERE user_id=%s ORDER BY id DESC", (user_id,))

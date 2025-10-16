from typing import List, Optional, Dict, Any
from datetime import datetime
import random, string

from .db import fetchone, fetchall, execute  # 导出 execute 供其他模块使用



async def get_flag(k: str) -> Optional[str]:
    row = await fetchone("SELECT v FROM sys_flags WHERE k=%s", (k,))
    return row["v"] if row else None

async def set_flag(k: str, v: str):
    await execute("INSERT INTO sys_flags(k,v) VALUES(%s,%s) ON DUPLICATE KEY UPDATE v=VALUES(v)", (k,v))

async def get_total_user_balance(asset: str) -> float:
    row = await fetchone("SELECT COALESCE(SUM(usdt_balance),0) AS t FROM users", ())
    # 若你的用户余额分表，请改对应聚合 SQL
    return float(row["t"] if row and row["t"] is not None else 0.0)

async def ledger_exists_for_ref(reason: str, ref_table: str, ref_id: int) -> bool:
    row = await fetchone("SELECT id FROM ledger WHERE ref_table=%s AND ref_id=%s LIMIT 1", (ref_table, ref_id))
    return bool(row)

async def insert_ledger(user_id: int, asset: str, delta: float, before: float, after: float,
                        reason: str, ref_table: str, ref_id: int):
    await execute(
        "INSERT INTO ledger(user_id, asset, change_amount, balance_before, balance_after, reason, ref_table, ref_id) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
        (user_id, asset, delta, before, after, reason, ref_table, ref_id)
    )

# =========================
# 小工具
# =========================

def _rand_letters(n: int = 4) -> str:
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(n))


# =========================
# 充值订单（recharge_orders）
# =========================

def make_order_no(dt: Optional[datetime] = None) -> str:
    """
    订单号规则：YYYYMMDDHHMM + 4位小写字母，如 202510151945abcd
    """
    dt = dt or datetime.now()
    return dt.strftime('%Y%m%d%H%M') + _rand_letters(4)

async def get_active_recharge_order(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM recharge_orders "
        "WHERE user_id=%s AND status='waiting' AND expire_at>NOW() "
        "ORDER BY id DESC LIMIT 1",
        (user_id,)
    )

async def create_recharge_order(user_id: int, address: str, expected_amount: Optional[float], expire_minutes: int) -> int:
    order_no = make_order_no()
    sql = ("INSERT INTO recharge_orders(order_no, user_id, address, expected_amount, status, created_at, expire_at) "
           "VALUES(%s,%s,%s,%s,'waiting',NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE))")
    new_id = await execute(sql, (order_no, user_id, address, expected_amount, expire_minutes))
    return new_id

async def get_recharge_order(order_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM recharge_orders WHERE id=%s", (order_id,))

async def list_recharge_waiting() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='waiting' AND expire_at>NOW() ORDER BY id ASC LIMIT 100",
        ()
    )

async def list_recharge_collecting() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='collecting' ORDER BY id ASC LIMIT 100",
        ()
    )

async def list_recharge_verifying() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='verifying' ORDER BY id ASC LIMIT 100",
        ()
    )

async def set_recharge_status(order_id: int, status: str, txid: Optional[str]):
    await execute(
        "UPDATE recharge_orders SET status=%s, txid=%s, updated_at=NOW() WHERE id=%s",
        (status, txid, order_id)
    )

async def ledger_exists_for_ref(change_type: str, ref_table: str, ref_id: int) -> bool:
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM ledger WHERE change_type=%s AND ref_table=%s AND ref_id=%s",
        (change_type, ref_table, ref_id)
    )
    return bool(row and row.get("c", 0) > 0)


# =========================
# 用户 / 交易密码（users）
# =========================

async def ensure_user(user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]):
    await execute(
        "INSERT IGNORE INTO users(id, username, first_name, last_name, created_at) "
        "VALUES(%s,%s,%s,%s,NOW())",
        (user_id, username, first_name, last_name)
    )

async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM users WHERE id=%s", (user_id,))

async def get_tx_password_hash(user_id: int) -> Optional[str]:
    row = await fetchone("SELECT tx_password_hash FROM users WHERE id=%s", (user_id,))
    return row.get("tx_password_hash") if row else None

async def has_tx_password(user_id: int) -> bool:
    h = await get_tx_password_hash(user_id)
    return bool(h)

async def set_tx_password_hash(user_id: int, pwd_hash: str) -> None:
    """
    上层已经做过加盐/哈希，这里只落库。
    表结构要求：users(tx_password_hash VARCHAR, tx_password_updated_at DATETIME 可选)
    """
    await execute(
        "UPDATE users SET tx_password_hash=%s, tx_password_updated_at=NOW() WHERE id=%s",
        (pwd_hash, user_id)
    )


# =========================
# 钱包（user_wallets）
# =========================

async def get_wallet(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM user_wallets WHERE user_id=%s", (user_id,))

async def set_tron_wallet(user_id: int, address: str, privkey_enc: str):
    await execute(
        "INSERT INTO user_wallets(user_id, tron_address, tron_privkey_enc, usdt_trc20_balance) "
        "VALUES(%s,%s,%s,0) "
        "ON DUPLICATE KEY UPDATE tron_address=VALUES(tron_address), tron_privkey_enc=VALUES(tron_privkey_enc)",
        (user_id, address, privkey_enc)
    )

async def update_wallet_balance(user_id: int, new_bal: float):
    await execute("UPDATE user_wallets SET usdt_trc20_balance=%s WHERE user_id=%s", (new_bal, user_id))


# =========================
# 账变（ledger）
# =========================

async def add_ledger(user_id: int, change_type: str, amount: float, bal_before: float, bal_after: float,
                     ref_table: str, ref_id: int, remark: str):
    await execute(
        "INSERT INTO ledger(user_id, change_type, amount, balance_before, balance_after, ref_table, ref_id, remark, created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        (user_id, change_type, amount, bal_before, bal_after, ref_table, ref_id, remark)
    )

async def list_ledger_recent(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )


# =========================
# 地址簿（user_addresses）
# =========================

async def list_user_addresses(user_id: int) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM user_addresses WHERE user_id=%s ORDER BY id DESC",
        (user_id,)
    )

async def add_user_address(user_id: int, address: str, alias: str) -> int:
    """
    新增常用地址；建议在上层校验别名长度<=15、TRON 地址格式等。
    表结构：user_addresses(id PK AI, user_id, address, alias, created_at)
    """
    return await execute(
        "INSERT INTO user_addresses(user_id, address, alias, created_at) VALUES(%s,%s,%s,NOW())",
        (user_id, address, alias)
    )

async def delete_user_address(addr_id: int, user_id: int) -> None:
    await execute(
        "DELETE FROM user_addresses WHERE id=%s AND user_id=%s",
        (addr_id, user_id)
    )

async def get_user_address_by_alias(user_id: int, alias: str) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM user_addresses WHERE user_id=%s AND alias=%s",
        (user_id, alias)
    )


# =========================
# 红包（red_packets, red_packet_shares）
# =========================

async def list_red_packets(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM red_packets WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )

async def create_red_packet(user_id: int, rp_type: str, total_amount: float, count: int,
                            currency: Optional[str], cover_text: Optional[str], exclusive_user_id: Optional[int]) -> int:
    currency = currency or "USDT-trc20"
    sql = ("INSERT INTO red_packets(user_id, type, total_amount, count, currency, cover_text, exclusive_user_id, status, created_at) "
           "VALUES(%s,%s,%s,%s,%s,%s,%s,'draft',NOW())")
    new_id = await execute(sql, (user_id, rp_type, total_amount, count, currency, cover_text, exclusive_user_id))
    return new_id

async def get_red_packet(rp_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM red_packets WHERE id=%s", (rp_id,))

async def set_red_packet_status(rp_id: int, status: str):
    await execute("UPDATE red_packets SET status=%s, updated_at=NOW() WHERE id=%s", (status, rp_id))

async def save_red_packet_share(rp_id: int, seq: int, amount: float):
    await execute(
        "INSERT INTO red_packet_shares(red_packet_id, seq, amount) VALUES(%s,%s,%s)",
        (rp_id, seq, amount)
    )

async def list_red_packet_shares(rp_id: int) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM red_packet_shares WHERE red_packet_id=%s ORDER BY id ASC",
        (rp_id,)
    )

async def claim_share(rp_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    """
    简单两段式防并发：
    1) 抓一条未领取份额
    2) 抢占（claimed_by IS NULL）→ 然后再读取返回
    """
    row = await fetchone(
        "SELECT id FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NULL ORDER BY id ASC LIMIT 1",
        (rp_id,)
    )
    if not row:
        return None
    sid = row["id"]
    await execute(
        "UPDATE red_packet_shares SET claimed_by=%s, claimed_at=NOW() WHERE id=%s AND claimed_by IS NULL",
        (user_id, sid)
    )
    got = await fetchone("SELECT * FROM red_packet_shares WHERE id=%s", (sid,))
    if not got or got.get("claimed_by") != user_id:
        return None
    return got

async def count_claimed(rp_id: int) -> int:
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NOT NULL",
        (rp_id,)
    )
    return int(row["c"] if row else 0)

# 兼容旧代码：有的地方引了 add_red_packet_claim，这里提供空实现避免 ImportError
async def add_red_packet_claim(*args, **kwargs):
    return 0

# —— 能量租用记录 —— #
async def last_energy_rent_seconds_ago(address: str) -> int:
    row = await fetchone(
        "SELECT TIMESTAMPDIFF(SECOND, rented_at, NOW()) AS sec FROM energy_rent_logs "
        "WHERE address=%s ORDER BY id DESC LIMIT 1",
        (address,),
    )
    if not row or row.get("sec") is None:
        return 10**9
    return int(row["sec"])

async def has_active_energy_rent(address: str) -> bool:
    row = await fetchone(
        "SELECT id FROM energy_rent_logs WHERE address=%s AND status='active' AND expire_at>NOW() ORDER BY id DESC LIMIT 1",
        (address,),
    )
    return bool(row)

async def add_energy_rent_log(address: str, order_id: int, order_no: str,
                              rent_order_id: str = None, rent_txid: str = None,
                              ttl_seconds: int = 3600) -> None:
    await execute(
        "INSERT INTO energy_rent_logs(address,order_id,order_no,provider,rent_order_id,rent_txid,rented_at,expire_at,status)"
        " VALUES(%s,%s,%s,'trongas',%s,%s,NOW(),DATE_ADD(NOW(),INTERVAL %s SECOND),'active')",
        (address, order_id, order_no, rent_order_id, rent_txid, ttl_seconds),
    )

async def mark_energy_rent_used(address: str) -> None:
    await execute(
        "UPDATE energy_rent_logs SET status='used' WHERE address=%s AND status='active'",
        (address,),
    )

from typing import Optional, List, Dict, Any, Tuple
from .db import fetchone, fetchall, execute
from .logger import app_logger

async def ensure_user(user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]):
    u = await fetchone("SELECT id FROM users WHERE id=%s", (user_id,))
    if not u:
        await execute("INSERT INTO users(id, username, first_name, last_name) VALUES (%s,%s,%s,%s)",
                      (user_id, username, first_name, last_name))
        await execute("INSERT INTO user_wallets(user_id) VALUES (%s)", (user_id,))
        app_logger.info(f"👤 新用户已创建: {user_id}")

async def get_wallet(user_id: int):
    return await fetchone("SELECT * FROM user_wallets WHERE user_id=%s", (user_id,))

async def update_wallet_balance(user_id: int, new_balance: float):
    await execute("UPDATE user_wallets SET usdt_trc20_balance=%s WHERE user_id=%s", (new_balance, user_id))

async def set_tron_wallet(user_id: int, address: str, priv_enc: str):
    await execute("UPDATE user_wallets SET tron_address=%s, tron_privkey_enc=%s WHERE user_id=%s",
                  (address, priv_enc, user_id))

async def set_tx_password_hash(user_id: int, pw_hash: str):
    await execute("UPDATE users SET tx_password_hash=%s WHERE id=%s", (pw_hash, user_id))

async def get_tx_password_hash(user_id: int):
    row = await fetchone("SELECT tx_password_hash FROM users WHERE id=%s", (user_id,))
    return row["tx_password_hash"] if row else None

async def add_user_address(user_id: int, address: str, alias: str):
    return await execute("INSERT INTO user_addresses(user_id, chain, address, alias) VALUES (%s,'TRX',%s,%s)",
                         (user_id, address, alias))

async def list_user_addresses(user_id: int):
    return await fetchall("SELECT * FROM user_addresses WHERE user_id=%s ORDER BY id DESC", (user_id,))

async def add_ledger(user_id: int, change_type: str, amount: float, before: float, after: float,
                     ref_type: Optional[str], ref_id: Optional[int], remark: Optional[str]):
    return await execute("""
        INSERT INTO ledger(user_id, change_type, amount, balance_before, balance_after, ref_type, ref_id, remark)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
    """, (user_id, change_type, amount, before, after, ref_type, ref_id, remark))

async def list_ledger_recent(user_id: int, limit: int = 10):
    return await fetchall("SELECT * FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s", (user_id, limit))

async def create_red_packet(owner_id: int, rp_type: str, total_amount: float, count: int,
                            cover_text: Optional[str], cover_image_file_id: Optional[str],
                            exclusive_user_id: Optional[int]):
    rp_id = await execute("""
        INSERT INTO red_packets(owner_id, type, total_amount, count, cover_text, cover_image_file_id, exclusive_user_id)
        VALUES (%s,%s,%s,%s,%s,%s,%s)
    """, (owner_id, rp_type, total_amount, count, cover_text, cover_image_file_id, exclusive_user_id))
    return rp_id

async def list_red_packets(owner_id: int, limit: int = 10):
    return await fetchall("""
        SELECT * FROM red_packets WHERE owner_id=%s ORDER BY id DESC LIMIT %s
    """, (owner_id, limit))

async def get_red_packet(rp_id: int):
    return await fetchone("SELECT * FROM red_packets WHERE id=%s", (rp_id,))

async def set_red_packet_status(rp_id: int, status: str):
    await execute("UPDATE red_packets SET status=%s WHERE id=%s", (status, rp_id))

async def save_red_packet_share(rp_id: int, seq: int, amount: float):
    return await execute("""
        INSERT INTO red_packet_shares(red_packet_id, seq, amount) VALUES (%s,%s,%s)
    """, (rp_id, seq, amount))

async def list_red_packet_shares(rp_id: int):
    return await fetchall("SELECT * FROM red_packet_shares WHERE red_packet_id=%s ORDER BY seq ASC", (rp_id,))

async def claim_share(rp_id: int, claimer_id: int):
    share = await fetchone("""
        SELECT * FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NULL ORDER BY seq ASC LIMIT 1
    """, (rp_id,))
    if not share:
        return None
    await execute("""UPDATE red_packet_shares SET claimed_by=%s, claimed_at=NOW() WHERE id=%s""",
                  (claimer_id, share["id"]))
    return share

async def add_red_packet_claim(rp_id: int, claimer_id: int, amount: float):
    return await execute("""
        INSERT INTO red_packet_claims(red_packet_id, claimer_id, amount) VALUES (%s,%s,%s)
    """, (rp_id, claimer_id, amount))

async def count_claimed(rp_id: int) -> int:
    row = await fetchone("SELECT COUNT(*) AS c FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NOT NULL", (rp_id,))
    return int(row["c"]) if row else 0

async def create_recharge_order(user_id: int, address: str, expected_amount: Optional[float], expire_minutes: int = 15):
    order_id = await execute("""
        INSERT INTO recharge_orders(user_id, address, expected_amount, expire_at)
        VALUES (%s,%s,%s, DATE_ADD(NOW(), INTERVAL %s MINUTE))
    """, (user_id, address, expected_amount, expire_minutes))
    return order_id

async def list_recharge_waiting():
    return await fetchall("""
        SELECT * FROM recharge_orders WHERE status='waiting' AND expire_at > NOW() ORDER BY id ASC
    """)

async def set_recharge_status(order_id: int, status: str, txid_collect: Optional[str] = None):
    await execute("UPDATE recharge_orders SET status=%s, txid_collect=%s WHERE id=%s",
                  (status, txid_collect, order_id))

async def get_user_by_id(user_id: int):
    return await fetchone("SELECT * FROM users WHERE id=%s", (user_id,))


async def get_recharge_order(order_id: int):
    return await fetchone("SELECT * FROM recharge_orders WHERE id=%s", (order_id,))

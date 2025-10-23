# -*- coding: utf-8 -*-
from .utils.order_no import gen_order_no
from typing import List, Optional, Dict, Any
from datetime import datetime
import random, string
from .db import fetchone, fetchall, execute, execute_rowcount, get_conn  # 新增 get_conn
from decimal import Decimal  # 新增
import aiomysql  # 新增


# ===== sys_flags =====

async def get_flag(k: str) -> Optional[str]:
    row = await fetchone("SELECT v FROM sys_flags WHERE k=%s", (k,))
    return row["v"] if row else None

async def set_flag(k: str, v: str):
    await execute(
        "INSERT INTO sys_flags(k,v) VALUES(%s,%s) ON DUPLICATE KEY UPDATE v=VALUES(v)",
        (k, v),
    )

# ===== 汇总 =====

async def get_total_user_balance(asset: str) -> float:
    # 当前仅一种资产 USDT-TRC20，直接统算 user_wallets.usdt_trc20_balance
    row = await fetchone("SELECT COALESCE(SUM(usdt_trc20_balance),0) AS t FROM user_wallets", ())
    return float(row["t"] if row and row["t"] is not None else 0.0)

# ===== 订单号 =====

def _rand_letters(n: int = 4) -> str:
    return ''.join(random.choice(string.ascii_lowercase) for _ in range(n))

def make_order_no(dt: Optional[datetime] = None, prefix: str = "") -> str:
    dt = dt or datetime.now()
    return (prefix or "") + dt.strftime('%Y%m%d%H%M') + _rand_letters(4)


# ===== 充值订单 =====

async def get_active_recharge_order(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM recharge_orders "
        "WHERE user_id=%s AND status='waiting' AND expire_at>NOW() "
        "ORDER BY id DESC LIMIT 1",
        (user_id,),
    )

async def create_recharge_order(user_id: int, address: str, expected_amount: Optional[float], expire_minutes: int) -> int:
    order_no = make_order_no(prefix="charge_")
    sql = (
        "INSERT INTO recharge_orders(order_no, user_id, address, expected_amount, status, created_at, expire_at) "
        "VALUES(%s,%s,%s,%s,'waiting',NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE))"
    )
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
        "UPDATE recharge_orders SET status=%s, txid=%s WHERE id=%s",
        (status, txid, order_id),
    )

# ===== 用户 / 交易密码 =====
async def ensure_user(user_id: int, username: Optional[str], first_name: Optional[str], last_name: Optional[str]):
    # 计算 display_name：优先 first_name+last_name，其次 username，最后 id
    name = ((first_name or "") + (last_name or "")).strip()
    if not name:
        name = (username or "").strip()
    if not name:
        name = str(user_id)

    await execute(
        "INSERT INTO users(id, username, first_name, last_name, display_name, created_at) "
        "VALUES(%s,%s,%s,%s,%s,NOW()) "
        "ON DUPLICATE KEY UPDATE username=VALUES(username), first_name=VALUES(first_name), "
        "last_name=VALUES(last_name), display_name=VALUES(display_name)",
        (user_id, username, first_name, last_name, name)
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
    await execute(
        "UPDATE users SET tx_password_hash=%s WHERE id=%s",
        (pwd_hash, user_id)
    )

# ===== 钱包 =====

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

async def get_available_usdt(user_id: int) -> float:
    row = await fetchone("SELECT usdt_trc20_balance AS bal, COALESCE(usdt_trc20_frozen,0) AS frz FROM user_wallets WHERE user_id=%s", (user_id,))
    if not row:
        return 0.0
    return float((row["bal"] or 0) - (row["frz"] or 0))

async def adjust_frozen(user_id: int, delta: float):
    # delta 可正可负，最小不低于 0
    await execute(
        "UPDATE user_wallets SET usdt_trc20_frozen=GREATEST(0, COALESCE(usdt_trc20_frozen,0)+%s) WHERE user_id=%s",
        (delta, user_id)
    )

async def deduct_balance_and_unfreeze(user_id: int, total: float):
    # 成功后：余额 -= total；冻结 -= total
    await execute(
        "UPDATE user_wallets SET "
        "usdt_trc20_balance=usdt_trc20_balance-%s, "
        "usdt_trc20_frozen=GREATEST(0, COALESCE(usdt_trc20_frozen,0)-%s) "
        "WHERE user_id=%s",
        (total, total, user_id)
    )
# ===== 账变 =====
async def add_ledger(user_id: int, type_: str, amount: float, before: float, after: float,
                     ref_table: str, ref_id: int, remark: str, order_no: str):
    """
    新签名：带 order_no，并依赖 (user_id, order_no) 唯一索引防重。
    表字段名对齐：change_type（不是 type）。
    """
    sql = ("INSERT INTO ledger(user_id, change_type, amount, balance_before, balance_after, "
           "ref_table, ref_id, order_no, remark, created_at) "
           "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())")
    try:
        await execute(sql, (user_id, type_, amount, before, after,
                            ref_table, ref_id, order_no, remark))
    except Exception as e:
        s = str(e).lower()
        if "duplicate" in s or "unique" in s:
            # 已记账：静默跳过，保证幂等
            return
        raise

async def list_ledger_recent(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )

async def ledger_exists_for_ref(change_type: str, ref_table: str, ref_id: int) -> bool:
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM ledger WHERE change_type=%s AND ref_table=%s AND ref_id=%s",
        (change_type, ref_table, ref_id)
    )
    return bool(row and row.get("c", 0) > 0)

async def get_ledger_by_ref(change_type: str, ref_table: str, ref_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM ledger WHERE change_type=%s AND ref_table=%s AND ref_id=%s ORDER BY id DESC LIMIT 1",
        (change_type, ref_table, ref_id)
    )

# ===== 地址簿 =====
async def list_user_addresses(user_id: int) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM user_addresses WHERE user_id=%s AND status='active' ORDER BY id DESC",
        (user_id,)
    )

async def add_user_address(user_id: int, address: str, alias: str) -> int:
    return await execute(
        "INSERT INTO user_addresses(user_id, address, alias, status, created_at) "
        "VALUES(%s,%s,%s,'active',NOW()) "
        "ON DUPLICATE KEY UPDATE alias=VALUES(alias), status='active', created_at=NOW()",
        (user_id, address, alias)
    )

async def soft_delete_user_address(user_id: int, text: str) -> int:
    """
    根据“地址 或 别名”软删除（仅限当前用户），返回受影响行数
    """
    # 精确优先：别名全等；其次地址包含
    # 避免误删，限制 status='active'
    n1 = await execute_rowcount(
        "UPDATE user_addresses SET status='deleted' "
        "WHERE user_id=%s AND status='active' AND alias=%s",
        (user_id, text)
    )
    if n1:
        return n1
    return await execute_rowcount(
        "UPDATE user_addresses SET status='deleted' "
        "WHERE user_id=%s AND status='active' AND address LIKE %s",
        (user_id, f"%{text}%")
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

# ===== 红包 =====

async def list_red_packets(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    # 表结构: owner_id
    return await fetchall(
        "SELECT * FROM red_packets WHERE owner_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit)
    )

async def create_red_packet(owner_id: int, type_: str, total_amount: float, count: int,
                            exclusive_user_id: Optional[int], cover_text: Optional[str],
                            expires_at):
    from .utils.order_no import gen_order_no
    rp_no = gen_order_no("red")  # red_YYMMDDxxxx
    sql = ("INSERT INTO red_packets(rp_no, owner_id, type, total_amount, count, exclusive_user_id, "
           "cover_text, status, expires_at, created_at) "
           "VALUES(%s,%s,%s,%s,%s,%s,%s,'created',%s,NOW())")
    rp_id = await execute(sql, (rp_no, owner_id, type_, total_amount, count,
                                exclusive_user_id, cover_text, expires_at))
    return rp_id

async def get_red_packet(rp_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM red_packets WHERE id=%s", (rp_id,))

async def set_red_packet_status(rp_id: int, status: str):
    # 表中没有 updated_at 列
    await execute("UPDATE red_packets SET status=%s WHERE id=%s", (status, rp_id))

async def set_red_packet_message(rp_id: int, chat_id: int, message_id: int):
    await execute("UPDATE red_packets SET chat_id=%s, message_id=%s WHERE id=%s", (chat_id, message_id, rp_id))

async def list_red_packet_top_claims(rp_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT s.amount, s.claimed_at, s.claimed_by, u.username, u.first_name, u.last_name "
        "FROM red_packet_shares s LEFT JOIN users u ON u.id=s.claimed_by "
        "WHERE s.red_packet_id=%s AND s.claimed_by IS NOT NULL "
        "ORDER BY s.amount DESC LIMIT %s",
        (rp_id, limit)
    )

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

async def list_recent_claims_with_creator(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    我最近领取的红包记录（从 shares 表推导），并带上创建人信息。
    列：claimed_at, amount, owner.display_name / username / first/last
    """
    return await fetchall(
        "SELECT s.claimed_at, s.amount, rp.owner_id, "
        "u.display_name, u.username, u.first_name, u.last_name "
        "FROM red_packet_shares s "
        "JOIN red_packets rp ON rp.id = s.red_packet_id "
        "LEFT JOIN users u ON u.id = rp.owner_id "
        "WHERE s.claimed_by=%s "
        "ORDER BY s.claimed_at DESC LIMIT %s",
        (user_id, limit)
    )

# 为了兼容旧的 import，保留占位函数（目前未使用）。
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

async def list_user_active_red_packets(user_id: int):
    return await fetchall(
        "SELECT * FROM red_packets "
        "WHERE owner_id=%s "
        "  AND status IN ('paid','sent') "
        "  AND (expires_at IS NULL OR expires_at>NOW())",
        (user_id,)
    )

async def sum_claimed_amount(rp_id: int) -> float:
    row = await fetchone(
        "SELECT COALESCE(SUM(amount),0) AS s FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NOT NULL",
        (rp_id,)
    )
    return float(row["s"] if row else 0.0)

async def list_expired_red_packets(limit: int = 200) -> List[Dict[str, Any]]:
    """
    过期定义：状态为 paid/sent 且 expires_at <= NOW()
    """
    return await fetchall(
        "SELECT * FROM red_packets "
        "WHERE status IN ('paid','sent') AND expires_at IS NOT NULL AND expires_at <= NOW() "
        "ORDER BY id ASC LIMIT %s",
        (limit,)
    )

async def claim_share_atomic(rp_id: int, user_id: int):
    """
    原子抢红包（严格顺序）：
      1) 锁定一条未领取的份额 (FOR UPDATE)
      2) 标记份额为已领取（先扣库存）
      3) 锁定用户钱包，入账金额
      4) 写账变（含唯一 order_no：red_claim_<rp_no>_<share_id>）
    全过程同一事务内；任一步失败将回滚。
    返回 (share_id, amount) 或 None（已抢完）
    """
    async with (await get_conn()) as conn:
        try:
            await conn.begin()
            async with conn.cursor(aiomysql.DictCursor) as cur:
                # 1) 找到一条可领取份额并加锁
                await cur.execute(
                    "SELECT id, amount FROM red_packet_shares "
                    "WHERE red_packet_id=%s AND claimed_by IS NULL "
                    "ORDER BY id ASC LIMIT 1 FOR UPDATE",
                    (rp_id,)
                )
                row = await cur.fetchone()
                if not row:
                    await conn.rollback()
                    return None

                share_id = int(row["id"])
                amt = Decimal(str(row["amount"]))

                # 2) 尝试标记为已领取（若被别人抢到了，这里会失败）
                await cur.execute(
                    "UPDATE red_packet_shares SET claimed_by=%s, claimed_at=NOW() "
                    "WHERE id=%s AND claimed_by IS NULL",
                    (user_id, share_id)
                )
                if cur.rowcount == 0:
                    await conn.rollback()
                    return None

                # 3) 入账：先锁定钱包行
                await cur.execute(
                    "SELECT usdt_trc20_balance FROM user_wallets WHERE user_id=%s FOR UPDATE",
                    (user_id,)
                )
                w = await cur.fetchone() or {}
                before = Decimal(str(w.get("usdt_trc20_balance", 0)))
                after = before + amt
                await cur.execute(
                    "UPDATE user_wallets SET usdt_trc20_balance=%s WHERE user_id=%s",
                    (float(after), user_id)
                )

                # 4) 写账变（幂等靠唯一键）
                await cur.execute("SELECT rp_no FROM red_packets WHERE id=%s", (rp_id,))
                rp = await cur.fetchone() or {}
                rp_no = rp.get("rp_no", str(rp_id))
                order_no = f"red_claim_{rp_no}_{share_id}"
                await cur.execute(
                    "INSERT INTO ledger(user_id, change_type, amount, balance_before, balance_after, "
                    "ref_table, ref_id, order_no, remark, created_at) "
                    "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
                    (user_id, "redpacket_claim", float(amt), float(before), float(after),
                     "red_packets", rp_id, order_no, "领取红包入账")
                )

            await conn.commit()
            return share_id, float(amt)
        except Exception:
            await conn.rollback()
            raise

async def list_red_packet_claims(rp_id: int):
    sql = ("SELECT s.seq AS seq, s.claimed_at, s.amount, s.claimed_by, "
           "u.display_name, u.first_name, u.last_name, u.username "
           "FROM red_packet_shares s "
           "LEFT JOIN users u ON u.id = s.claimed_by "
           "WHERE s.red_packet_id=%s AND s.claimed_by IS NOT NULL "
           "ORDER BY s.id ASC")
    return await fetchall(sql, (rp_id,))

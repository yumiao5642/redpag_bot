import random
import string
from datetime import datetime
from typing import Any, Dict, List, Optional

from .db import execute, fetchall, fetchone  # 导出 execute 供其他模块使用


# =========================
# 小工具
# =========================
def _rand_letters(n: int = 4) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def make_order_no(dt: Optional[datetime] = None) -> str:
    """订单号：YYYYMMDDHHMM + 4位小写字母"""
    dt = dt or datetime.now()
    return dt.strftime("%Y%m%d%H%M") + _rand_letters(4)


# =========================
# 系统开关
# =========================
async def get_flag(k: str) -> Optional[str]:
    row = await fetchone("SELECT v FROM sys_flags WHERE k=%s", (k,))
    return row["v"] if row else None


async def set_flag(k: str, on: bool) -> None:
    v = "1" if on else "0"
    await execute(
        "INSERT INTO sys_flags(k,v) VALUES(%s,%s) "
        "ON DUPLICATE KEY UPDATE v=VALUES(v), updated_at=NOW()",
        (k, v),
    )


# =========================
# 用户
# =========================
async def get_or_create_user(tg_id: int, username: str) -> Dict[str, Any]:
    """
    为兼容历史，这里仍然使用 users(tg_id, username) 这一套。
    你线上若统一使用 users.id = Telegram ID，请按需收敛，这里不做破坏性调整。
    """
    row = await fetchone("SELECT id, tg_id, username FROM users WHERE tg_id=%s", (tg_id,))
    if not row:
        await execute(
            "INSERT INTO users(tg_id, username) VALUES(%s,%s)",
            (tg_id, (username or "")[:64]),
        )
        row = await fetchone("SELECT id, tg_id, username FROM users WHERE tg_id=%s", (tg_id,))
    return row


async def ensure_user(
    user_id: int,
    username: Optional[str],
    first_name: Optional[str],
    last_name: Optional[str],
):
    # 另一套 users(id, username, ...) 兼容入口
    await execute(
        "INSERT IGNORE INTO users(id, username, first_name, last_name, created_at) "
        "VALUES(%s,%s,%s,%s,NOW())",
        (user_id, username, first_name, last_name),
    )


async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM users WHERE id=%s", (user_id,))


# =========================
# 钱包
# =========================
async def get_wallet(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM user_wallets WHERE user_id=%s", (user_id,))


async def set_tron_wallet(user_id: int, address: str, privkey_enc: str):
    await execute(
        "INSERT INTO user_wallets(user_id, tron_address, tron_privkey_enc, usdt_trc20_balance) "
        "VALUES(%s,%s,%s,0) "
        "ON DUPLICATE KEY UPDATE tron_address=VALUES(tron_address), tron_privkey_enc=VALUES(tron_privkey_enc)",
        (user_id, address, privkey_enc),
    )


async def update_wallet_balance(user_id: int, new_bal: float):
    await execute(
        "UPDATE user_wallets SET usdt_trc20_balance=%s WHERE user_id=%s",
        (new_bal, user_id),
    )


async def get_user_balance(user_id: int) -> float:
    """统一以 user_wallets 为准"""
    row = await fetchone("SELECT usdt_trc20_balance FROM user_wallets WHERE user_id=%s", (user_id,))
    return float(row["usdt_trc20_balance"] or 0) if row else 0.0


async def sum_user_usdt_balance() -> float:
    row = await fetchone("SELECT COALESCE(SUM(usdt_trc20_balance),0) AS s FROM user_wallets", ())
    return float(row["s"] or 0)


# =========================
# 充值订单 recharge_orders
# =========================
async def get_recharge_orders_by_status(status_list: List[str]) -> List[Dict[str, Any]]:
    if not status_list:
        return []
    ph = ",".join(["%s"] * len(status_list))
    sql = f"SELECT * FROM recharge_orders WHERE status IN ({ph}) ORDER BY id ASC"
    return await fetchall(sql, tuple(status_list))


async def get_active_recharge_order(user_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM recharge_orders "
        "WHERE user_id=%s AND status='waiting' AND expire_at>NOW() "
        "ORDER BY id DESC LIMIT 1",
        (user_id,),
    )


async def create_recharge_order(
    user_id: int, address: str, expected_amount: Optional[float], expire_minutes: int
) -> int:
    order_no = make_order_no()
    sql = (
        "INSERT INTO recharge_orders(order_no, user_id, address, expected_amount, status, created_at, expire_at) "
        "VALUES(%s,%s,%s,%s,'waiting',NOW(), DATE_ADD(NOW(), INTERVAL %s MINUTE))"
    )
    new_id = await execute(
        sql, (order_no, user_id, address, expected_amount, expire_minutes)
    )
    return new_id


async def get_recharge_order(order_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM recharge_orders WHERE id=%s", (order_id,))


# —— 为 handler 提供的便捷封装（兼容你之前的调用名） —— #
async def get_recharge_order_by_user(user_id: int) -> Optional[Dict[str, Any]]:
    """返回当前仍有效的 waiting 订单，并附带 expire_text / left_min 字段"""
    row = await get_active_recharge_order(user_id)
    if not row:
        return None
    # 补充展示字段
    expire_at = row.get("expire_at")
    row["expire_text"] = str(expire_at)
    try:
        from datetime import datetime
        if isinstance(expire_at, str):
            dt = datetime.fromisoformat(expire_at.replace("Z", "+00:00"))
        else:
            dt = expire_at
        sec = (dt - datetime.now(dt.tzinfo) if getattr(dt, "tzinfo", None) else dt - datetime.now()).total_seconds()
        row["left_min"] = 0 if sec <= 0 else int((sec + 59) // 60)
    except Exception:
        row["left_min"] = 0
    return row


async def create_recharge_order_if_needed(user_id: int):
    """没有有效 waiting 订单则创建一张，返回订单行"""
    row = await get_recharge_order_by_user(user_id)
    if row:
        return row
    w = await get_wallet(user_id)
    addr = (w or {}).get("tron_address")
    if not addr:
        raise RuntimeError("用户钱包地址不存在，无法创建充值订单")
    oid = await create_recharge_order(user_id, addr, None, 15)
    return await get_recharge_order(oid)


async def set_recharge_status(order_id: int, status: str, txid: Optional[str]) -> None:
    if txid:
        await execute(
            "UPDATE recharge_orders SET status=%s, txid=%s, updated_at=NOW() WHERE id=%s",
            (status, txid, order_id),
        )
    else:
        await execute(
            "UPDATE recharge_orders SET status=%s, updated_at=NOW() WHERE id=%s",
            (status, order_id),
        )


# 提供一个空实现避免历史导入报错（如需记录刷新动作可在此落库）
async def mark_recharge_refreshed(order_id: int) -> None:
    await execute("UPDATE recharge_orders SET refreshed_at=NOW() WHERE id=%s", (order_id,))


async def list_recharge_waiting() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='waiting' AND expire_at>NOW() ORDER BY id ASC LIMIT 100",
        (),
    )


async def list_recharge_collecting() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='collecting' ORDER BY id ASC LIMIT 100",
        (),
    )


async def list_recharge_verifying() -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM recharge_orders WHERE status='verifying' ORDER BY id ASC LIMIT 100",
        (),
    )


# =========================
# 账变 ledger
# =========================
async def add_ledger(
    user_id: int,
    change_type: str,  # 'recharge' | 'withdraw' | 'redpacket_send' | 'redpacket_claim' | 'adjust'
    amount: float,
    balance_before: float,
    balance_after: float,
    ref_table: Optional[str] = None,
    ref_type: Optional[str] = None,
    ref_id: Optional[int] = None,
    remark: Optional[str] = None,
) -> None:
    """
    兼容两种调用方式：
    1) 新版（推荐）：add_ledger(u, change_type, amt, before, after, ref_table, ref_type, ref_id, remark)
    2) 旧版（你当前代码）：add_ledger(u, change_type, amt, before, after, ref_table, ref_id, remark)
       —— 少传了 ref_type；此时自动将 ref_type := change_type，并把传入的整数位置参数识别为 ref_id。
    """
    # 兼容旧序：如果第7个参数传来的是 int（其实是 ref_id），把它左移
    if ref_type is not None and not isinstance(ref_type, str):
        # 老序调用：ref_type拿到的是int(rp_id)
        ref_id = int(ref_type)
        ref_type = None  # 留空，稍后默认成 change_type

    if not ref_type:
        ref_type = change_type

    await execute(
        "INSERT INTO ledger(user_id, change_type, ref_table, amount, balance_before, balance_after, "
        "ref_type, ref_id, remark, created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())",
        (
            user_id,
            change_type,
            ref_table,
            amount,
            balance_before,
            balance_after,
            ref_type,
            ref_id,
            (remark or "")[:255],
        ),
    )


async def list_ledger_recent(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM ledger WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )


async def ledger_exists_for_ref(ref_type: str, ref_table: str, ref_id: int) -> bool:
    row = await fetchone(
        "SELECT id FROM ledger WHERE ref_type=%s AND ref_table=%s AND ref_id=%s LIMIT 1",
        (ref_type, ref_table, ref_id),
    )
    return bool(row)


async def get_ledger_amount_by_ref(ref_type: str, ref_table: str, ref_id: int) -> float:
    row = await fetchone(
        "SELECT COALESCE(SUM(amount),0) AS s FROM ledger WHERE ref_type=%s AND ref_table=%s AND ref_id=%s",
        (ref_type, ref_table, ref_id),
    )
    return float(row["s"] or 0)


# =========================
# 地址簿
# =========================
async def list_user_addresses(user_id: int) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM user_addresses WHERE user_id=%s ORDER BY id DESC", (user_id,)
    )


async def add_user_address(user_id: int, address: str, alias: str) -> int:
    return await execute(
        "INSERT INTO user_addresses(user_id, address, alias, created_at) VALUES(%s,%s,%s,NOW())",
        (user_id, address, alias),
    )


async def delete_user_address(addr_id: int, user_id: int) -> None:
    await execute(
        "DELETE FROM user_addresses WHERE id=%s AND user_id=%s", (addr_id, user_id)
    )


async def get_user_address_by_alias(
    user_id: int, alias: str
) -> Optional[Dict[str, Any]]:
    return await fetchone(
        "SELECT * FROM user_addresses WHERE user_id=%s AND alias=%s", (user_id, alias)
    )


# =========================
# 红包（略：保持你原有实现）
# =========================
async def list_red_packets(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM red_packets WHERE user_id=%s ORDER BY id DESC LIMIT %s",
        (user_id, limit),
    )


async def create_red_packet(
    user_id: int,
    rp_type: str,
    total_amount: float,
    count: int,
    currency: Optional[str],
    cover_text: Optional[str],
    exclusive_user_id: Optional[int],
) -> int:
    currency = currency or "USDT-trc20"
    sql = (
        "INSERT INTO red_packets(user_id, type, total_amount, count, currency, cover_text, exclusive_user_id, status, created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,'draft',NOW())"
    )
    new_id = await execute(
        sql,
        (
            user_id,
            rp_type,
            total_amount,
            count,
            currency,
            cover_text,
            exclusive_user_id,
        ),
    )
    return new_id


async def get_red_packet(rp_id: int) -> Optional[Dict[str, Any]]:
    return await fetchone("SELECT * FROM red_packets WHERE id=%s", (rp_id,))


async def set_red_packet_status(rp_id: int, status: str):
    await execute(
        "UPDATE red_packets SET status=%s, updated_at=NOW() WHERE id=%s",
        (status, rp_id),
    )


async def save_red_packet_share(rp_id: int, seq: int, amount: float):
    await execute(
        "INSERT INTO red_packet_shares(red_packet_id, seq, amount) VALUES(%s,%s,%s)",
        (rp_id, seq, amount),
    )


async def list_red_packet_shares(rp_id: int) -> List[Dict[str, Any]]:
    return await fetchall(
        "SELECT * FROM red_packet_shares WHERE red_packet_id=%s ORDER BY id ASC",
        (rp_id,),
    )


async def claim_share(rp_id: int, user_id: int) -> Optional[Dict[str, Any]]:
    row = await fetchone(
        "SELECT id FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NULL ORDER BY id ASC LIMIT 1",
        (rp_id,),
    )
    if not row:
        return None
    sid = row["id"]
    await execute(
        "UPDATE red_packet_shares SET claimed_by=%s, claimed_at=NOW() WHERE id=%s AND claimed_by IS NULL",
        (user_id, sid),
    )
    got = await fetchone("SELECT * FROM red_packet_shares WHERE id=%s", (sid,))
    if not got or got.get("claimed_by") != user_id:
        return None
    return got


async def count_claimed(rp_id: int) -> int:
    row = await fetchone(
        "SELECT COUNT(*) AS c FROM red_packet_shares WHERE red_packet_id=%s AND claimed_by IS NOT NULL",
        (rp_id,),
    )
    return int(row["c"] if row else 0)

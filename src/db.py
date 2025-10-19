import aiomysql
from typing import Any, Dict, List, Optional, Tuple
from .config import MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB
from .logger import app_logger

_pool: Optional[aiomysql.Pool] = None

async def init_pool():
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(
            host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER,
            password=MYSQL_PASSWORD, db=MYSQL_DB, autocommit=True,
            minsize=1, maxsize=10, charset="utf8mb4"
        )
        app_logger.info("✅ MySQL 连接池已初始化")

async def close_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None
        app_logger.info("🛑 MySQL 连接池已关闭")

async def get_conn():
    assert _pool is not None, "MySQL 连接池未初始化"
    return _pool.acquire()

async def fetchone(sql: str, args: Tuple = ()) -> Optional[Dict[str, Any]]:
    async with (await get_conn()) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchone()

async def fetchall(sql: str, args: Tuple = ()) -> List[Dict[str, Any]]:
    async with (await get_conn()) as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute(sql, args)
            return await cur.fetchall()

async def execute(sql: str, args: Tuple = ()) -> int:
    """
    兼容 INSERT：返回 lastrowid（若可用）；UPDATE/DELETE 场景不保证准确数量。
    """
    async with (await get_conn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, args)
            return cur.lastrowid or 0

async def execute_rowcount(sql: str, args: Tuple = ()) -> int:
    """
    返回受影响行数，适合 UPDATE / DELETE 精确统计。
    """
    async with (await get_conn()) as conn:
        async with conn.cursor() as cur:
            await cur.execute(sql, args)
            return cur.rowcount or 0

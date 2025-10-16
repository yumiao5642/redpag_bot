import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "hb_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "hb_pass")
MYSQL_DB = os.getenv("MYSQL_DB", "hb_db")

FERNET_KEY = os.getenv("FERNET_KEY", "")

# TRON / TronGrid / USDT
USDT_CONTRACT = os.getenv("USDT_CONTRACT", "")
AGGREGATE_ADDRESS = os.getenv("AGGREGATE_ADDRESS", "")
TRON_FULLNODE_URL = os.getenv("TRON_FULLNODE_URL", "https://api.trongrid.io")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY", "")  # 逗号分隔可配置多个，用于轮询
TRONGRID_QPS = float(
    os.getenv("TRONGRID_QPS", "10")
)  # 频率限制，默认 10 QPS（官方建议带 key 可达 ~15 QPS）
USDT_DECIMALS = int(os.getenv("USDT_DECIMALS", "6"))

# trongas 能量租用
TRONGAS_API_KEY = os.getenv("TRONGAS_API_KEY", "")

# 业务配置
MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT", "10"))
MIN_WITHDRAW_USDT = float(os.getenv("MIN_WITHDRAW_USDT", "5"))
WITHDRAW_FEE_FIXED = float(os.getenv("WITHDRAW_FEE_FIXED", "1"))
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "@support")

# 基础断言
assert BOT_TOKEN, "请在 .env 中配置 BOT_TOKEN"
assert FERNET_KEY, "请在 .env 中配置 FERNET_KEY"
assert USDT_CONTRACT, "请在 .env 中配置 USDT_CONTRACT（TRC20 USDT 合约地址）"
assert AGGREGATE_ADDRESS, "请在 .env 中配置 AGGREGATE_ADDRESS（归集收款地址）"

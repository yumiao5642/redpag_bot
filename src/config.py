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
TRON_API_KEY = os.getenv("TRON_API_KEY", "")
USDT_CONTRACT = os.getenv("USDT_CONTRACT", "")
AGGREGATE_ADDRESS = os.getenv("AGGREGATE_ADDRESS", "")

MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT", "10"))
MIN_WITHDRAW_USDT = float(os.getenv("MIN_WITHDRAW_USDT", "5"))
WITHDRAW_FEE_FIXED = float(os.getenv("WITHDRAW_FEE_FIXED", "1"))

SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT", "@support")

assert BOT_TOKEN, "请在 .env 中配置 BOT_TOKEN"
assert FERNET_KEY, "请在 .env 中配置 FERNET_KEY（使用 cryptography 生成）"

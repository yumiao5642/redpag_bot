import os
from dotenv import load_dotenv
load_dotenv()

# Telegram / DB
BOT_TOKEN = os.getenv("BOT_TOKEN","")
MYSQL_HOST = os.getenv("MYSQL_HOST","127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT","3306"))
MYSQL_USER = os.getenv("MYSQL_USER","hb_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD","hb_pass")
MYSQL_DB = os.getenv("MYSQL_DB","hb_db")

# Crypto / TRON
FERNET_KEY = os.getenv("FERNET_KEY","")
USDT_CONTRACT = os.getenv("USDT_CONTRACT","")                # 必填：USDT TRC20 合约地址（主网：Tether_USDT_Contract_Address_On_TRON）
AGGREGATE_ADDRESS = os.getenv("AGGREGATE_ADDRESS","")       # 必填：归集收款地址
TRON_FULLNODE_URL = os.getenv("TRON_FULLNODE_URL","")       # 可选：自定义 FullNode（留空用默认）
TRONGAS_API_KEY = os.getenv("TRONGAS_API_KEY","")           # 建议：trongas.io 的 apiKey
USDT_DECIMALS = int(os.getenv("USDT_DECIMALS","6"))         # USDT 精度（默认 6）

# 业务配置
MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT","10"))
MIN_WITHDRAW_USDT = float(os.getenv("MIN_WITHDRAW_USDT","5"))
WITHDRAW_FEE_FIXED = float(os.getenv("WITHDRAW_FEE_FIXED","1"))
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT","@support")

# 基础断言（启动即检查）
assert BOT_TOKEN, "请在 .env 中配置 BOT_TOKEN"
assert FERNET_KEY, "请在 .env 中配置 FERNET_KEY（使用 cryptography 生成）"
assert USDT_CONTRACT, "请在 .env 中配置 USDT_CONTRACT（USDT-TRC20 合约地址）"
assert AGGREGATE_ADDRESS, "请在 .env 中配置 AGGREGATE_ADDRESS（归集收款地址）"

import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN","")

MYSQL_HOST = os.getenv("MYSQL_HOST","127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT","3306"))
MYSQL_USER = os.getenv("MYSQL_USER","rebpag_user")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD","")
MYSQL_DB = os.getenv("MYSQL_DB","rebpag_data")

FERNET_KEY = os.getenv("FERNET_KEY","")

# TRON / TronGrid / USDT
USDT_CONTRACT = os.getenv("USDT_CONTRACT","")
AGGREGATE_ADDRESS = os.getenv("AGGREGATE_ADDRESS","")
TRON_FULLNODE_URL = os.getenv("TRON_FULLNODE_URL","https://api.trongrid.io")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY","")     # 逗号分隔可配置多个，用于轮询
TRONGRID_QPS = float(os.getenv("TRONGRID_QPS","10"))
USDT_DECIMALS = int(os.getenv("USDT_DECIMALS","6"))

# trongas 能量租用
TRONGAS_API_KEY = os.getenv("TRONGAS_API_KEY","")

# 业务配置
MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT","10"))
MIN_WITHDRAW_USDT = float(os.getenv("MIN_WITHDRAW_USDT","5"))
WITHDRAW_FEE_FIXED = float(os.getenv("WITHDRAW_FEE_FIXED","1"))
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT","@support")

# —— GoPlus 风险查询（可选）——
GOPLUS_BASE_URL = os.getenv("GOPLUS_BASE_URL", "https://api.gopluslabs.io")
GOPLUS_API_KEY  = os.getenv("GOPLUS_API_KEY", "")

AGGREGATE_PRIVKEY_ENC = os.getenv("AGGREGATE_PRIVKEY_ENC","")  # 归集地址私钥（Fernet 加密文本）

# —— Telegram 网络/超时（代理可选）——
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT","25"))
TELEGRAM_READ_TIMEOUT    = float(os.getenv("TELEGRAM_READ_TIMEOUT","35"))
TELEGRAM_WRITE_TIMEOUT   = float(os.getenv("TELEGRAM_WRITE_TIMEOUT","35"))
TELEGRAM_POOL_TIMEOUT    = float(os.getenv("TELEGRAM_POOL_TIMEOUT","10"))
TELEGRAM_PROXY           = os.getenv("TELEGRAM_PROXY","").strip()

# === Webhook 基本参数 ===
WEBHOOK_MODE   = os.getenv("WEBHOOK_MODE", "webhook").lower()
WEBHOOK_HOST   = os.getenv("WEBHOOK_HOST", "0.0.0.0")
WEBHOOK_PORT   = int(os.getenv("WEBHOOK_PORT","3010"))
WEBHOOK_PATH   = os.getenv("WEBHOOK_PATH", "/rptg/webhook").strip()

PUBLIC_URL     = os.getenv("PUBLIC_URL","").strip()
WEBHOOK_PUBLIC_BASE = os.getenv("WEBHOOK_PUBLIC_BASE", "").rstrip("/") or PUBLIC_URL

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()

WEBHOOK_URL_PATH = WEBHOOK_PATH.lstrip("/")
WEBHOOK_URL_FULL = f"{WEBHOOK_PUBLIC_BASE}/{WEBHOOK_URL_PATH}"

if WEBHOOK_MODE == "webhook":
    assert WEBHOOK_PUBLIC_BASE.startswith("https://"), "WEBHOOK_PUBLIC_BASE / PUBLIC_URL 必须是 https:// 开头的公网地址"
    assert WEBHOOK_SECRET, "WEBHOOK_SECRET 未配置"

def _parse_allowed_updates(raw: str) -> list[str]:
    s = (raw or "").strip()
    for ch in '[]"\' ':
        s = s.replace(ch, "")
    return [x for x in s.split(",") if x]

ALLOWED_UPDATES = _parse_allowed_updates(os.getenv(
    "ALLOWED_UPDATES",
    "message,callback_query,inline_query,chosen_inline_result,pre_checkout_query,shipping_query"
))


# 基础断言（保留你原有的）
assert BOT_TOKEN, "请在 .env 中配置 BOT_TOKEN"
assert FERNET_KEY, "请在 .env 中配置 FERNET_KEY"
assert USDT_CONTRACT, "请在 .env 中配置 USDT_CONTRACT（TRC20 USDT 合约地址）"
assert AGGREGATE_ADDRESS, "请在 .env 中配置 AGGREGATE_ADDRESS（归集收款地址）"
assert AGGREGATE_PRIVKEY_ENC, "请在 .env 中配置 AGGREGATE_PRIVKEY_ENC（归集地址私钥，使用 FERNET_KEY 加密）"


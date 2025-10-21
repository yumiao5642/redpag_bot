import os
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN","")
MYSQL_HOST = os.getenv("MYSQL_HOST","127.0.0.1")
MYSQL_PORT = int(os.getenv("MYSQL_PORT","3306"))
MYSQL_USER = os.getenv("MYSQL_USER","rebpag_user")     # 按你 dump 命令的默认用户
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD","")        # 建议用环境变量显式传入
MYSQL_DB = os.getenv("MYSQL_DB","rebpag_data")         # 与 dump 的库名一致

FERNET_KEY = os.getenv("FERNET_KEY","")

# TRON / TronGrid / USDT
USDT_CONTRACT = os.getenv("USDT_CONTRACT","")
AGGREGATE_ADDRESS = os.getenv("AGGREGATE_ADDRESS","")
TRON_FULLNODE_URL = os.getenv("TRON_FULLNODE_URL","https://api.trongrid.io")
TRONGRID_API_KEY = os.getenv("TRONGRID_API_KEY","")     # 逗号分隔可配置多个，用于轮询
TRONGRID_QPS = float(os.getenv("TRONGRID_QPS","10"))    # 频率限制，默认 10 QPS（官方建议带 key 可达 ~15 QPS）
USDT_DECIMALS = int(os.getenv("USDT_DECIMALS","6"))

# trongas 能量租用
TRONGAS_API_KEY = os.getenv("TRONGAS_API_KEY","")

# 业务配置
MIN_DEPOSIT_USDT = float(os.getenv("MIN_DEPOSIT_USDT","10"))
MIN_WITHDRAW_USDT = float(os.getenv("MIN_WITHDRAW_USDT","5"))
WITHDRAW_FEE_FIXED = float(os.getenv("WITHDRAW_FEE_FIXED","1"))
SUPPORT_CONTACT = os.getenv("SUPPORT_CONTACT","@support")

# —— GoPlus 风险查询（新增）——
GOPLUS_BASE_URL = os.getenv("GOPLUS_BASE_URL", "https://api.gopluslabs.io")
GOPLUS_API_KEY  = os.getenv("GOPLUS_API_KEY", "")  # 可选；留空则匿名请求（更易受限）
AGGREGATE_PRIVKEY_ENC = os.getenv("AGGREGATE_PRIVKEY_ENC","")  # 归集地址私钥（Fernet 加密文本）

# —— Telegram 网络/超时（解决 get_me 超时）——
# 如需代理，支持：socks5://user:pass@host:port 或 http://host:port
TELEGRAM_CONNECT_TIMEOUT = float(os.getenv("TELEGRAM_CONNECT_TIMEOUT","25"))
TELEGRAM_READ_TIMEOUT    = float(os.getenv("TELEGRAM_READ_TIMEOUT","35"))
TELEGRAM_WRITE_TIMEOUT   = float(os.getenv("TELEGRAM_WRITE_TIMEOUT","35"))
TELEGRAM_POOL_TIMEOUT    = float(os.getenv("TELEGRAM_POOL_TIMEOUT","10"))
TELEGRAM_PROXY           = os.getenv("TELEGRAM_PROXY","").strip()


# 基础断言
assert BOT_TOKEN, "请在 .env 中配置 BOT_TOKEN"
assert FERNET_KEY, "请在 .env 中配置 FERNET_KEY"
assert USDT_CONTRACT, "请在 .env 中配置 USDT_CONTRACT（TRC20 USDT 合约地址）"
assert AGGREGATE_ADDRESS, "请在 .env 中配置 AGGREGATE_ADDRESS（归集收款地址）"
assert AGGREGATE_PRIVKEY_ENC, "请在 .env 中配置 AGGREGATE_PRIVKEY_ENC（归集地址私钥，使用 FERNET_KEY 加密）"

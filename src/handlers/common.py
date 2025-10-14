from telegram import Update
from telegram.ext import ContextTypes
from ..models import ensure_user, get_wallet, set_tron_wallet
from ..services.tron import generate_address
from ..services.encryption import encrypt_text
from ..logger import user_click_logger, app_logger

def fmt_amount(x) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return str(x)

async def ensure_user_and_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    await ensure_user(u.id, u.username, u.first_name, u.last_name)
    wallet = await get_wallet(u.id)
    if not wallet or not wallet.get("tron_address"):
        addr = generate_address()
        await set_tron_wallet(u.id, addr.address, encrypt_text(addr.private_key_hex))
        app_logger.info(f"🔐 为用户 {u.id} 生成 TRON 地址: {addr.address}")
    user_click_logger.info(f"👆 用户 {u.id} 触发交互：{update.effective_message.text if update.effective_message else 'callback'}")

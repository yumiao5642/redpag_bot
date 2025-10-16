# src/services/encryption.py
from __future__ import annotations
import os, base64, hashlib, hmac
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken

# ====== 交易密码：PBKDF2-HMAC-SHA256 ======
# 形如：pbkdf2$sha256$100000$<salt_b64>$<dk_b64>
_ITERATIONS = 100_000
_ALGO = "sha256"

def _b64e(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")

def _b64d(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)

def hash_password(password: str, salt: Optional[str] = None) -> str:
    if not isinstance(password, str) or password == "":
        raise ValueError("password required")
    if salt is None:
        salt = _b64e(os.urandom(16))
    dk = hashlib.pbkdf2_hmac(_ALGO, password.encode(), salt.encode(), _ITERATIONS, dklen=32)
    return f"pbkdf2${_ALGO}${_ITERATIONS}${salt}${_b64e(dk)}"

def verify_password(password: str, stored: str) -> bool:
    try:
        t, algo, iters, salt, b64 = stored.split("$", 4)
        if t != "pbkdf2" or algo != _ALGO:
            return False
        iters = int(iters)
        dk = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), iters, dklen=32)
        return hmac.compare_digest(_b64e(dk), b64)
    except Exception:
        return False

# ====== 字段加解密：Fernet（可选） ======
_FERNET_KEY = os.getenv("FERNET_KEY", "").strip()
_fernet: Optional[Fernet] = None
if _FERNET_KEY:
    try:
        _fernet = Fernet(_FERNET_KEY.encode())
    except Exception:
        _fernet = None

def encrypt_text(plain: str) -> str:
    if not _fernet:
        return plain
    return _fernet.encrypt(plain.encode()).decode()

def decrypt_text(token: str) -> str:
    if not _fernet:
        return token
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        # 兼容历史明文
        return token

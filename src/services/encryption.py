from cryptography.fernet import Fernet

from ..config import FERNET_KEY

_cipher = Fernet(FERNET_KEY.encode() if isinstance(FERNET_KEY, str) else FERNET_KEY)


def encrypt_text(s: str) -> str:
    return _cipher.encrypt(s.encode()).decode()


def decrypt_text(token: str) -> str:
    return _cipher.decrypt(token.encode()).decode()

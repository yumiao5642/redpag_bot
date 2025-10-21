import os
from cryptography.fernet import Fernet
FERNET_KEY="CeAhlWeQx-msjsRhIQd85qHssFBDzVS-7VvSL0sHT2k="
key = os.environ['FERNET_KEY'].encode()
f = Fernet(key)
plain = input("请输入归集私钥(64位hex，不要带0x)：").strip()
enc = f.encrypt(plain.encode()).decode()
print("\nAGGREGATE_PRIVKEY_ENC（粘贴到 .env）：\n" + enc)

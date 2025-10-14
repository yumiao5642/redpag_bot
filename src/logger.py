import logging
import os
from logging.handlers import RotatingFileHandler

LOG_DIR = os.path.join(os.getcwd(), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

def _make_handler(filename: str) -> RotatingFileHandler:
    handler = RotatingFileHandler(os.path.join(LOG_DIR, filename), maxBytes=5*1024*1024, backupCount=5, encoding='utf-8')
    fmt = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(fmt)
    return handler

def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        sh = logging.StreamHandler()
        sh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
        logger.addHandler(sh)
        mapping = {
            "recharge": "recharge.log",
            "redpacket": "redpacket.log",
            "user_click": "user_click.log",
            "withdraw": "withdraw.log",
            "password": "password.log",
            "address": "address.log",
            "collect": "collect.log",
        }
        filename = mapping.get(name, "app.log")
        logger.addHandler(_make_handler(filename))
    return logger

recharge_logger = get_logger("recharge")
redpacket_logger = get_logger("redpacket")
user_click_logger = get_logger("user_click")
withdraw_logger = get_logger("withdraw")
password_logger = get_logger("password")
address_logger = get_logger("address")
collect_logger = get_logger("collect")
app_logger = get_logger("app")

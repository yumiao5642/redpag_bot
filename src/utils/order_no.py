# -*- coding: utf-8 -*-
import random, string
from datetime import datetime

def gen_order_no(prefix: str) -> str:
    # red_ + YYYYMMDDHHMM + 4位小写字母
    date_part = datetime.utcnow().strftime("%Y%m%d%H%M")
    rand_part = "".join(random.choice(string.ascii_lowercase) for _ in range(4))
    return f"{prefix}_{date_part}{rand_part}"

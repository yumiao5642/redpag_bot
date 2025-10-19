# -*- coding: utf-8 -*-
def fmt_amount(x) -> str:
    try:
        return f"{float(x):.2f}"
    except Exception:
        return "0.00"

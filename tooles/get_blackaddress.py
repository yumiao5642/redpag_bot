import requests
from collections import OrderedDict

USDT_CONTRACT = "TXLAQ63Xg1NAzckPwKHvzw7CSEmLMEqcdj"  # TRC-20 USDT 主网合约
BASE = "https://apilist.tronscanapi.com/api/contract/events"  # Tronscan 公共 API

# 这些事件名称在 USDT/黑名单管理上较常见；不同版本合约可能略有差异
RISK_EVENT_KEYWORDS = [
    "AddedBlackList", "AddBlackList", "BlackListed",
    "Frozen", "AddressFrozen", "Freezed", "AccountFrozen",
    "Lock", "BlockAddress", "Prohibit", "Denied"
]

def fetch_events(contract=USDT_CONTRACT, limit=200, start=0):
    params = {"contract": contract, "limit": limit, "start": start, "sort": "-timestamp"}
    r = requests.get(BASE, params=params, timeout=20)
    r.raise_for_status()
    return r.json()

def is_risk_event(name: str) -> bool:
    name = (name or "").lower()
    return any(k.lower() in name for k in RISK_EVENT_KEYWORDS)

def extract_addr_from_event(ev: dict):
    # Tronscan 事件返回里通常有 'parameter' / 'event' / 'result' 等字段
    # 这里做尽量稳健的提取（黑名单/冻结事件通常只有一个目标地址）
    for key in ("parameter", "result", "event"):
        data = ev.get(key)
        if isinstance(data, dict):
            # 常见字段名尝试：
            for k in ("_addr", "addr", "_address", "address", "account", "_account"):
                v = data.get(k)
                if isinstance(v, str) and v.startswith("T") and len(v) >= 34:
                    return v
    # 再从所有值里扫一遍“像地址”的字符串
    def looks_like_tron(s: str) -> bool:
        return isinstance(s, str) and s.startswith("T") and 30 <= len(s) <= 50
    for v in (ev.get("parameter") or {}, ev.get("result") or {}, ev.get("event") or {}):
        if isinstance(v, dict):
            for x in v.values():
                if looks_like_tron(x):
                    return x
    return None

def main(max_pages=5, page_size=200):
    addrs = OrderedDict()
    for i in range(max_pages):
        js = fetch_events(limit=page_size, start=i * page_size)
        events = js.get("data") or js.get("events") or []
        if not events:
            break
        for ev in events:
            name = ev.get("event_name") or ev.get("event") or ""
            if not is_risk_event(name):
                continue
            addr = extract_addr_from_event(ev) or ""
            if addr.startswith("T"):
                # 用 OrderedDict 去重并保序
                addrs[addr] = True
        if len(events) < page_size:
            break

    results = list(addrs.keys())[:50]  # 取前 50 个
    print("从 USDT 合约事件中抓到的疑似被拉黑/冻结地址（用于 GoPlus 测试）：")
    for a in results:
        print(a)

if __name__ == "__main__":
    main()

import random
from decimal import Decimal, getcontext
from typing import List

# 使用 6 位小数，适配 USDT 常见精度
getcontext().prec = 28


def _d(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def split_random(total_amount: float, count: int) -> List[Decimal]:
    """
    随机红包：
    - 单份最大不超过 2 * (均值)
    - 总和严格等于 total_amount
    - 避免出现 0 或最后一份过大的情况
    """
    assert count >= 1
    total = _d(total_amount)
    mean = total / _d(count)
    max_per = mean * _d(2)  # 最大值限制
    shares = []
    remain = total

    for i in range(1, count + 1):
        remain_count = count - len(shares)
        if remain_count == 1:
            # 最后一份
            amt = remain
        else:
            # 剩余均值附近随机，限制上限与下限
            max_allowed = min(max_per, remain - _d("0.000001") * (remain_count - 1))
            min_allowed = max(_d("0.000001"), remain / _d(remain_count) / _d(2))
            if max_allowed < min_allowed:
                max_allowed = min_allowed
            # 在 [min_allowed, max_allowed] 间随机
            r = Decimal(str(random.random()))
            amt = min_allowed + r * (max_allowed - min_allowed)
            # 四舍五入到 6 位小数
            amt = amt.quantize(Decimal("0.000001"))
            if amt <= _d("0"):
                amt = _d("0.000001")
        remain -= amt
        remain = remain.quantize(Decimal("0.000001"))
        shares.append(amt)

    # 修正总和误差
    diff = total - sum(shares)
    if diff != 0:
        shares[-1] = (shares[-1] + diff).quantize(Decimal("0.000001"))
        if shares[-1] <= 0:
            # 极端回退，重新平摊
            return split_average(total_amount, count)

    return shares


def split_average(total_amount: float, count: int) -> List[Decimal]:
    total = _d(total_amount)
    base = (total / _d(count)).quantize(Decimal("0.000001"))
    shares = [base for _ in range(count)]
    # 调整小数误差
    diff = total - sum(shares)
    shares[-1] = (shares[-1] + diff).quantize(Decimal("0.000001"))
    return shares

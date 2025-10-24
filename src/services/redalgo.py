from decimal import Decimal, getcontext
from typing import List
import random

getcontext().prec = 28
Q = Decimal("0.01")  # 两位小数

def _d(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def split_random(total_amount: float, count: int) -> List[Decimal]:
    """
    随机红包（两位小数）：
    - 总和严格等于 total_amount（四舍五入到 0.01）
    - 单份最大不超过 2 * 均值
    - 单份最小 0.01（若 total < 0.01*count 会退化为平均）
    """
    assert count >= 1
    total = _d(total_amount).quantize(Q)
    mean = (total / _d(count)).quantize(Q)
    max_per = (mean * _d(2)).quantize(Q)
    min_per = Q

    # 极端：钱不够均分到 0.01
    if total < min_per * count:
        return split_average(float(total), count)

    shares = []
    remain = total

    for i in range(1, count + 1):
        left = count - len(shares)
        if left == 1:
            amt = remain
        else:
            # 保证剩余至少能分给每人 0.01
            max_allowed = min(max_per, remain - min_per * (left - 1))
            min_allowed = min_per
            if max_allowed < min_allowed:
                max_allowed = min_allowed
            r = Decimal(str(random.random()))
            amt = (min_allowed + r * (max_allowed - min_allowed)).quantize(Q)
            if amt < min_per:
                amt = min_per
        remain = (remain - amt).quantize(Q)
        shares.append(amt)

    # 误差修正
    diff = total - sum(shares)
    if diff != 0:
        shares[-1] = (shares[-1] + diff).quantize(Q)
        if shares[-1] < min_per:
            return split_average(float(total), count)

    # 限幅（防极端随机引发的边界抖动）
    for i, v in enumerate(shares):
        if v > max_per:
            shares[i] = max_per

    return shares

def split_average(total_amount: float, count: int) -> List[Decimal]:
    total = _d(total_amount).quantize(Q)
    base = (total / _d(count)).quantize(Q)
    shares = [base for _ in range(count)]
    diff = total - sum(shares)
    shares[-1] = (shares[-1] + diff).quantize(Q)
    return shares

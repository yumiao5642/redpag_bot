#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
严格体检：
1) 扫描 py39 不兼容的 union（" | None"）
2) 统计 models.py 定义的函数/常量，并核对 handlers / services 里的 import 使用
3) 粗略找“未使用的 models 函数”
4) 捕捉裸 except、广义 except、print 调试残留
5) 触发一次 compileall（能快速发现语法/缩进等硬错误）

用法：
    python3 scripts/repo_audit_strict.py
"""
import os, re, sys, ast, compileall
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")

def iter_py():
    for p in SRC.rglob("*.py"):
        if any(x in p.parts for x in ("__pycache__",)):
            continue
        yield p

def find_py39_union():
    bad = []
    rx = re.compile(r"\|\s*None\b")
    for p in iter_py():
        txt = read(p)
        for i, line in enumerate(txt.splitlines(), 1):
            if rx.search(line):
                bad.append((p, i, line.strip()))
    return bad

def ast_defs_calls_in_models(models: Path):
    txt = read(models)
    tree = ast.parse(txt, filename=str(models))
    defs = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs.add(n.name)
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name):
                    defs.add(t.id)
    return defs

def imported_from_models():
    used = set()
    rx = re.compile(r"from\s+\.{1,2}models\s+import\s+(.+)")
    for p in iter_py():
        if p.name == "models.py":
            continue
        for m in rx.finditer(read(p)):
            names = [x.strip().split(" as ")[0] for x in m.group(1).split(",")]
            for n in names:
                if n:
                    used.add(n)
    return used

def grep_usage(name: str):
    # 粗糙：全仓文本搜索
    pat = re.compile(r"\b" + re.escape(name) + r"\b")
    hits = []
    for p in iter_py():
        for i, line in enumerate(read(p).splitlines(), 1):
            if pat.search(line):
                hits.append((p, i, line.strip()))
    return hits

def scan_broad_except():
    items = []
    rx_bare = re.compile(r"^\s*except\s*:\s*$")
    rx_broad = re.compile(r"^\s*except\s+\((Exception|BaseException)\)\s*:\s*$")
    for p in iter_py():
        for i, line in enumerate(read(p).splitlines(), 1):
            if rx_bare.match(line) or rx_broad.match(line):
                items.append((p, i, line.strip()))
    return items

def scan_prints():
    items = []
    rx = re.compile(r"^\s*print\(")
    for p in iter_py():
        for i, line in enumerate(read(p).splitlines(), 1):
            if rx.match(line):
                items.append((p, i, line.strip()))
    return items

def main():
    print("=== 严格体检（py39 兼容 & 符号核对 & 粗略死代码 & 异常规范 & 编译检查） ===")

    unions = find_py39_union()
    if unions:
        print("\n[!] 发现 py3.9 不兼容的 union 标注（请改为 Optional[...]）:")
        for p,i,l in unions:
            print(f" - {p}:{i}: {l}")
    else:
        print("\n[OK] 未发现 ' | None' 等 py39 不兼容 union")

    models = SRC / "models.py"
    if models.exists():
        defs = ast_defs_calls_in_models(models)
        used = imported_from_models()
        missing = sorted(n for n in used if n not in defs)
        if missing:
            print("\n[!] 其他模块引自 models 但 models 未定义：")
            for n in missing:
                print(f" - {n}")
        else:
            print("\n[OK] models 中能找到所有被 import 的符号")

        # 粗略“未被使用”的定义（排除常见保留）
        ignore = {"__all__", "__version__", "__doc__"}
        unused = []
        for name in sorted(d for d in defs if not d.startswith("_") and d not in ignore):
            hits = grep_usage(name)
            # 仅在 models 自身被定义，不在其他处被引用
            if all(str(p).endswith("/models.py") for p,_,_ in hits):
                unused.append(name)
        if unused:
            print("\n[?] 可能未使用的 models 符号（请人工复核，某些可能供 SQL/反射调用）：")
            for n in unused:
                print(f" - {n}")
        else:
            print("\n[OK] 未发现明显未使用的 models 符号")

    excs = scan_broad_except()
    if excs:
        print("\n[!] 发现裸/过宽 except（建议改为精确异常/加日志）：")
        for p,i,l in excs:
            print(f" - {p}:{i}: {l}")
    else:
        print("\n[OK] 未发现裸/过宽 except")

    prints = scan_prints()
    if prints:
        print("\n[?] 发现 print 调试输出（建议改为 logger）：")
        for p,i,l in prints:
            print(f" - {p}:{i}: {l}")
    else:
        print("\n[OK] 未发现 print 调试输出")

    print("\n[*] 进行编译检查（compileall）...")
    ok = compileall.compile_dir(str(SRC), quiet=1, force=False)
    if ok:
        print("[OK] compileall 编译通过")
    else:
        print("[X] compileall 有错误（请查看上方报错并修复）")

if __name__ == "__main__":
    main()

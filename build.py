#!/usr/bin/env python3
"""
build.py — 把 recipe_*.json 烘焙成一个静态 recipes.json

用法:
    python build.py            # 扫描当前目录
    python build.py ~/Desktop/xhs

说明:
    GitHub Pages / 任何静态托管只能放静态文件,跑不了 serve.py。
    这个脚本把 serve.py 的 /api/recipes 动态输出,一次性写成 recipes.json,
    index.html 会优先读它(读不到才回退到本地 serve.py 的 /api/recipes)。

    以后用 recipe.py 新抽了菜谱,重新跑一遍 `python build.py` 再 git push 即可。
"""

import json
import sys
from pathlib import Path

SCAN_DIR = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd()
OUT = SCAN_DIR / "recipes.json"


def normalize(raw: dict, source: str) -> dict:
    """把旧格式(单菜)和新格式(菜品数组)统一成新格式(与 serve.py 一致)"""
    if "菜品" in raw:
        data = raw
    else:
        data = {"视频主题": raw.get("菜名", "未命名"), "菜品": [raw]}
    data["_source"] = source
    return data


def load_all() -> list:
    recipes = []
    for fp in sorted(SCAN_DIR.rglob("recipe_*.json")):
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
            recipes.append(normalize(raw, fp.name))
        except Exception as e:
            print(f"  跳过 {fp.name}: {e}")
    return recipes


if __name__ == "__main__":
    data = load_all()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    dishes = sum(len(v.get("菜品", [])) for v in data)
    print(f"扫描目录: {SCAN_DIR}")
    print(f"写入 {OUT.name}:{len(data)} 个视频,共 {dishes} 道菜")

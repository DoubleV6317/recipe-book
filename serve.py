#!/usr/bin/env python3
"""
serve.py — 菜谱浏览器本地服务

用法:
    python serve.py              # 扫描当前目录
    python serve.py ~/Desktop/xhs  # 扫描指定目录

然后浏览器打开 http://localhost:8765

功能:
    - 递归扫描目录下所有 recipe_*.json
    - 兼容新格式(菜品数组)和旧格式(单菜)
    - 提供 /api/recipes 返回全部菜谱数据
    - 提供 index.html 静态页面
"""

import json
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

PORT = 8765
SCAN_DIR = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.cwd()
HERE = Path(__file__).parent


def normalize(raw: dict, source: str) -> dict:
    """把旧格式(单菜)和新格式(菜品数组)统一成新格式"""
    if "菜品" in raw:
        data = raw
    else:
        # 旧格式:整个对象就是一道菜
        data = {
            "视频主题": raw.get("菜名", "未命名"),
            "菜品": [raw],
        }
    data["_source"] = source
    return data


def load_all() -> list[dict]:
    recipes = []
    for fp in sorted(SCAN_DIR.rglob("recipe_*.json")):
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
            recipes.append(normalize(raw, fp.name))
        except Exception as e:
            print(f"  跳过 {fp.name}: {e}")
    return recipes


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/recipes":
            payload = json.dumps(load_all(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path in ("/", "/index.html"):
            html = (HERE / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        self.send_error(404)

    def log_message(self, *args):
        pass  # 静音


if __name__ == "__main__":
    if not (HERE / "index.html").exists():
        sys.exit(f"错误:找不到 index.html,请把它和 serve.py 放在同一目录")

    found = load_all()
    print(f"扫描目录: {SCAN_DIR}")
    print(f"找到 {len(found)} 个菜谱文件")
    print(f"\n浏览器打开 → http://localhost:{PORT}\n按 Ctrl+C 停止\n")

    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

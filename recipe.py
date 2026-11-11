#!/usr/bin/env python3
"""
recipe.py — 做饭视频 → 结构化菜谱 小工具

用法:
    python recipe.py video.mp4

前置准备:
    1. 安装 ffmpeg:  Mac: brew install ffmpeg   /  Ubuntu: sudo apt install ffmpeg
    2. 安装依赖:     pip install faster-whisper google-genai pillow
    3. 设置 API key:  export GEMINI_API_KEY="你的key"
       (key 在 https://aistudio.google.com/apikey 免费申请)

流程:
    模块1  ffmpeg 抽帧(每3秒一帧)+ 相似帧去重 + 压缩
    模块2  faster-whisper 本地语音转文字
    模块3  帧 + 转录文本 一起发给 Gemini,返回菜谱 JSON
    输出   recipe_<视频名>.md 菜谱卡片 + recipe_<视频名>.json 原始数据
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

# ──────────────────────────── 配置 ────────────────────────────

FRAME_INTERVAL_SEC = 2        # 每隔几秒抽一帧
MAX_FRAMES_TO_SEND = 24       # 最多发给模型多少帧(控制成本和干扰)
MAX_IMAGE_LONG_EDGE = 1000    # 图片压缩后长边像素
HASH_DIFF_THRESHOLD = 6       # 相邻帧感知哈希差异小于此值视为重复(0-64)
WHISPER_MODEL = "small"       # tiny/base/small/medium, small 对中文够用且不慢
GEMINI_MODEL = "gemini-flash-latest"
DEFAULT_AMOUNT = "常量"   # 视频未提及用量时,菜谱卡片上显示的文字

PROMPT = """以下是一个做饭视频的语音转录文本和按时间顺序排列的关键帧截图。
请综合语音和画面(尤其注意画面中博主贴的字幕/配料表贴纸)提取菜谱信息。

严格只输出一个 JSON 对象,不要输出任何其他文字、不要用 markdown 代码块包裹。格式:
{
  "视频主题": "",
  "菜品": [
    {
      "菜名": "",
      "食材": [{"名称": "", "用量": ""}],
      "调料": [{"名称": "", "用量": ""}],
      "步骤": [{"序号": 1, "描述": "", "时长或火候": ""}],
      "小贴士": []
    }
  ]
}

规则:
- 用量按视频原话记录,包括口语化的模糊量词(如"适量"、"少许"、"一圈"、"一点点"、"来点"),原样保留即可。
- 只有当视频中完全没有提到某食材/调料的量时,"用量"才填"未提及"。
- 绝对不要把模糊量词换算成具体数字,也不要编造视频中没有的数量。
- "适量"只有在视频原话确实说了"适量"时才能填。视频完全没提到量的,必须填"未提及",不要用"适量"作为默认值。
- 画面字幕和语音冲突时,以画面字幕为准(字幕通常是博主校对过的)。
- 步骤描述要具体可操作,合并语音和画面信息。
- "小贴士"放博主提到的注意事项,没有就留空数组。
- 如果视频提到食材需要提前处理(如腌制、焯水、泡发),且视频说明了处理方法,将其作为"预处理"步骤列在步骤1之前。
- 只提取与做菜直接相关的内容。忽略视频中的闲聊、生活记录、产品推广(如锅具/调料品牌推荐、购买链接口播)、片头片尾。
- 厨具品牌、购物信息不要出现在食材、调料或步骤中。
- 视频中制作了几道菜,就在"菜品"数组里输出几道,每道菜独立成一个对象,各自的食材/调料/步骤不要混在一起。
- 只有一道菜时,数组里也只放一个对象。
- 仅在视频中一带而过、没有展示制作过程的菜(如成品展示、口头提及但未制作),不要收录。
- 每道菜的"步骤"序号各自从1开始。

语音转录文本:
"""


# ──────────────────────────── 模块1: 抽帧 ────────────────────────────

def extract_frames(video_path: Path, out_dir: Path) -> list[Path]:
    """用 ffmpeg 每 FRAME_INTERVAL_SEC 秒抽一帧"""
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps=1/{FRAME_INTERVAL_SEC}",
        str(out_dir / "f_%04d.jpg"),
    ]
    subprocess.run(cmd, check=True)
    frames = sorted(out_dir.glob("f_*.jpg"))
    print(f"[模块1] 抽出 {len(frames)} 帧")
    return frames


def average_hash(img: Image.Image, size: int = 8) -> int:
    """简易感知哈希:缩到8x8灰度,和均值比较,得到64位指纹"""
    small = img.convert("L").resize((size, size))
    pixels = list(small.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p > avg else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def dedup_and_compress(frames: list[Path]) -> list[Image.Image]:
    """去掉和前一帧太相似的帧,压缩尺寸,均匀采样到上限数量"""
    kept: list[Image.Image] = []
    last_hash = None
    for fp in frames:
        img = Image.open(fp)
        h = average_hash(img)
        if last_hash is not None and hamming(h, last_hash) < HASH_DIFF_THRESHOLD:
            continue  # 和上一帧几乎一样,跳过
        last_hash = h
        # 压缩:长边限制到 MAX_IMAGE_LONG_EDGE
        w, hgt = img.size
        scale = MAX_IMAGE_LONG_EDGE / max(w, hgt)
        if scale < 1:
            img = img.resize((int(w * scale), int(hgt * scale)))
        kept.append(img)

    # 如果去重后仍然太多,均匀采样
    if len(kept) > MAX_FRAMES_TO_SEND:
        step = len(kept) / MAX_FRAMES_TO_SEND
        kept = [kept[int(i * step)] for i in range(MAX_FRAMES_TO_SEND)]

    print(f"[模块1] 去重压缩后保留 {len(kept)} 帧发送给模型")
    return kept


# ──────────────────────────── 模块2: 语音转文字 ────────────────────────────

def transcribe(video_path: Path) -> str:
    """用 faster-whisper 本地转录,第一次运行会自动下载模型文件"""
    from faster_whisper import WhisperModel

    print(f"[模块2] 加载 whisper 模型 ({WHISPER_MODEL}),首次运行需下载,请稍等…")
    model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="auto")
    segments, info = model.transcribe(str(video_path), language="zh", vad_filter=True)

    lines = []
    for seg in segments:
        lines.append(seg.text.strip())
    text = "\n".join(lines)
    print(f"[模块2] 转录完成,共 {len(text)} 字")
    return text


# ──────────────────────────── 模块3: 调用 Gemini ────────────────────────────

def call_gemini(images: list[Image.Image], asr_text: str) -> dict:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        sys.exit("错误:请先设置环境变量 GEMINI_API_KEY(https://aistudio.google.com/apikey 免费申请)")

    client = genai.Client(api_key=api_key)

    # contents 里图片和文字混排:先所有帧,最后是 prompt + 转录文本
    contents = [*images, PROMPT + asr_text]

    print(f"[模块3] 调用 {GEMINI_MODEL} …")
    resp = client.models.generate_content(model=GEMINI_MODEL, contents=contents)
    raw = resp.text.strip()

    # 容错:万一模型还是包了 ```json 代码块,剥掉它
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        print("模型返回的不是合法 JSON,原始输出如下,方便你调试 prompt:\n")
        print(raw)
        sys.exit(1)


# ──────────────────────────── 输出菜谱卡片 ────────────────────────────

def render_markdown(recipe: dict) -> str:
    if "菜品" not in recipe:
        sys.exit("错误:模型返回的 JSON 缺少「菜品」字段,可能是旧格式或格式异常。原始数据已存到 recipe_*.json,请检查后重试。")

    lines = [f"# {recipe.get('视频主题', '未命名视频')}", ""]

    for dish in recipe.get("菜品", []):
        lines.append(f"## {dish.get('菜名', '未命名菜谱')}")
        lines.append("")

        lines.append("### 食材")
        for item in dish.get("食材", []):
            amount = item.get('用量', '未提及')
            if amount == "未提及":
                amount = DEFAULT_AMOUNT
            lines.append(f"- {item.get('名称', '')} — {amount}")
        lines.append("")

        lines.append("### 调料")
        for item in dish.get("调料", []):
            amount = item.get('用量', '未提及')
            if amount == "未提及":
                amount = DEFAULT_AMOUNT
            lines.append(f"- {item.get('名称', '')} — {amount}")
        lines.append("")

        lines.append("### 步骤")
        for step in dish.get("步骤", []):
            extra = step.get("时长或火候", "")
            suffix = f"({extra})" if extra and extra != "未提及" else ""
            lines.append(f"{step.get('序号', '')}. {step.get('描述', '')} {suffix}".rstrip())
        lines.append("")

        tips = dish.get("小贴士", [])
        if tips:
            lines.append("### 小贴士")
            for t in tips:
                lines.append(f"- {t}")
            lines.append("")

    return "\n".join(lines)


# ──────────────────────────── 主流程 ────────────────────────────

def main():
    if len(sys.argv) != 2:
        sys.exit("用法: python recipe.py <视频文件路径>")

    video_path = Path(sys.argv[1])
    if not video_path.exists():
        sys.exit(f"找不到文件: {video_path}")

    with tempfile.TemporaryDirectory() as tmp:
        # 模块1
        frames = extract_frames(video_path, Path(tmp) / "frames")
        images = dedup_and_compress(frames)

        # 模块2
        asr_text = transcribe(video_path)

        # 模块3
        recipe = call_gemini(images, asr_text)

    # 输出
    stem = video_path.stem
    json_path = Path(f"recipe_{stem}.json")
    md_path = Path(f"recipe_{stem}.md")
    transcript_path = Path(f"transcript_{stem}.txt")

    json_path.write_text(json.dumps(recipe, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(recipe), encoding="utf-8")
    transcript_path.write_text(asr_text, encoding="utf-8")

    print(f"\n完成!菜谱已保存:")
    print(f"  {md_path}   ← 人看的菜谱卡片")
    print(f"  {json_path} ← 结构化数据,以后做搜索/购物清单用")
    print("\n" + "─" * 40 + "\n")
    print(render_markdown(recipe))


if __name__ == "__main__":
    main()

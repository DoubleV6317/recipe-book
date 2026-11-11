# 菜谱本 · 做饭视频 → 结构化菜谱

把做饭视频转成可浏览、可打钩的结构化菜谱。

- **抽取管线**(`recipe.py`):ffmpeg 抽帧 + 相似帧去重 → faster-whisper 本地语音转录 → Gemini 多模态提取,输出菜谱 JSON。支持一镜多菜视频(一个视频拆成多道菜)。
- **浏览器**(`index.html`):手机 / 桌面自适应,Swiper 跟手翻页,食材 / 调料 / 步骤可打钩,搜索过滤,屏幕常亮。

## 在线预览

GitHub Pages:**（部署后填入链接）**

## 本地运行

```bash
# 1. 装依赖
python3 -m venv venv && source venv/bin/activate
pip install faster-whisper google-genai pillow
brew install ffmpeg            # macOS

# 2. 抽取菜谱(需要 Gemini API key:https://aistudio.google.com/apikey)
export GEMINI_API_KEY="你的key"
python recipe.py 视频.mp4       # 生成 recipe_*.json / recipe_*.md

# 3a. 本地动态浏览
python serve.py                # 打开 http://localhost:8765

# 3b. 或生成静态站点(用于 GitHub Pages 等静态托管)
python build.py                # 把所有 recipe_*.json 烘焙成 recipes.json
```

## 文件说明

| 文件 | 作用 |
|------|------|
| `recipe.py` | 视频 → 菜谱 JSON 抽取管线 |
| `serve.py` | 本地动态服务(`/api/recipes`) |
| `build.py` | 生成静态 `recipes.json`(静态托管用) |
| `index.html` | 菜谱浏览器(优先读 `recipes.json`,回退 `/api/recipes`) |
| `recipe_*.json` | 每个视频抽取出的结构化菜谱 |
| `transcript_*.txt` | 语音转录原文 |

> 新抽了菜谱后,重新跑 `python build.py` 再 `git push`,线上即更新。

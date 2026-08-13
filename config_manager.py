"""统一配置管理 — 读写 config.yaml，提供默认值"""
import os
import yaml
from pathlib import Path

CONFIG_PATH = Path(__file__).parent / "config.yaml"
LOCAL_PLAYWRIGHT_BROWSERS = Path(__file__).parent / "playwright-browsers"

# 如果用户把 Chromium 安装到项目目录，后续启动无需每次手动设置环境变量。
if LOCAL_PLAYWRIGHT_BROWSERS.exists():
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(LOCAL_PLAYWRIGHT_BROWSERS))


def get_browser_executable() -> Path | None:
    """返回可用 Chrome/Chromium 路径，优先使用配置或环境变量。"""
    configured = os.getenv("DOUYIN_BROWSER_PATH", "")
    candidates = [
        Path(configured) if configured else None,
        Path(__file__).parent / "browser" / "chrome",
        Path("/tmp/douyin-monitor-browser/chrome/opt/google/chrome/chrome"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ]
    return next((path for path in candidates if path and path.is_file()), None)

DEFAULTS = {
    "schedule": {
        "daily_at": "06:00",
        "interval_minutes": 240,
        "jitter_minutes": 15,
    },
    "spider": {
        "max_scrolls": 80,
        "headless": True,
        "page_load_wait": 8,
        "scroll_idle_limit": 20,
        "viewport_width": 1920,
        "viewport_height": 1080,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "locale": "zh-CN",
    },
    "comments": {
        "video_limit": 50,
        "pages": 3,
        "comment_limit": 30,
        "page_count": 20,
        "inter_video_delay_min": 3,
        "inter_video_delay_max": 6,
        "filter_digg_min": 1,
        "filter_reply_min": 1,
    },
    "radar": {
        "enabled": True,
        "keywords": [
            "ChatGPT Plus", "ChatGPT Pro", "Codex", "Cursor", "Claude", "Gemini",
            "AI工具会员", "GPT充值", "GPT额度", "付款失败", "Plus和Pro区别",
        ],
        "days": 7,
        "max_results_per_keyword": 20,
        "max_comments_per_work": 100,
        "comment_pages": 5,
        "top_works_for_comments": 10,
        "search_scrolls": 8,
        "min_intent_score": 45,
        "output_dir": "./exports/radar",
        "feishu_webhook": "",
        "ai_enabled": False,
        "ai_base_url": "",
        "ai_model": "",
    },
    "transcriber": {
        "model": "small",
        "device": "cpu",
        "language": "zh",
        "beam_size": 5,
        "cookie_import_path": "",
    },
    "output": {
        "export_dir": "./exports",
        "auto_export_csv": True,
    },
    "web": {
        "host": "127.0.0.1",
        "port": 8080,
        "videos_per_page": 20,
        "fresh_threshold_hours": 6,
        "stale_threshold_days": 1,
    },
    "paths": {
        "data_dir": str(Path(__file__).parent / "data"),
        "session_dir": str(Path(__file__).parent / "douyin_session"),
        "db_path": str(Path(__file__).parent / "data" / "douyin_monitor.db"),
    },
}


def load_config() -> dict:
    """加载配置，合并默认值。"""
    if not CONFIG_PATH.exists():
        return dict(DEFAULTS)

    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        user_cfg = yaml.safe_load(f) or {}

    return _deep_merge(DEFAULTS.copy(), user_cfg)


def save_config(cfg: dict, path: Path | None = None):
    """保存配置到 config.yaml（保留结构）。"""
    target = path or CONFIG_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


def get(key: str, default=None):
    """快捷取值：get('spider.headless')。"""
    cfg = load_config()
    parts = key.split(".")
    for p in parts:
        if isinstance(cfg, dict):
            cfg = cfg.get(p)
        else:
            return default
    return cfg if cfg is not None else default


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并，override 的值覆盖 base。"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base

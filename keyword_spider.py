"""抖音关键词搜索采集器。

只读取登录后可见的公开搜索结果，不做点赞、关注、评论、私信或风控绕过。
抖音搜索接口结构会变化，因此这里优先解析浏览器正常加载到的 JSON，
同时保留一个页面 DOM 兜底，避免依赖某个固定的逆向接口。
"""
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


class KeywordSpider:
    def __init__(self, headless: bool | None = None):
        from config_manager import load_config, get

        cfg = load_config()
        self.headless = headless if headless is not None else cfg["spider"]["headless"]
        self.wait_seconds = cfg["spider"].get("page_load_wait", 8)
        self.scrolls = cfg.get("radar", {}).get("search_scrolls", 8)
        self.session_dir = Path(
            get("paths.session_dir", str(Path(__file__).parent / "douyin_session"))
        )

    async def search(self, keyword: str, days: int = 7, limit: int = 20) -> list[dict]:
        since_ts = int(time.time()) - max(1, days) * 86400
        results: dict[str, dict] = {}
        responses: list[dict] = []

        async with async_playwright() as p:
            from config_manager import get_browser_executable, load_config

            cfg = load_config()["spider"]
            self.session_dir.mkdir(parents=True, exist_ok=True)
            launch_options = dict(
                user_data_dir=str(self.session_dir),
                headless=self.headless,
                viewport={
                    "width": cfg.get("viewport_width", 1920),
                    "height": cfg.get("viewport_height", 1080),
                },
                user_agent=cfg.get("user_agent"),
                locale=cfg.get("locale", "zh-CN"),
            )
            executable = get_browser_executable()
            if executable:
                launch_options["executable_path"] = str(executable)
            if hasattr(os, "geteuid") and os.geteuid() == 0:
                launch_options["args"] = ["--no-sandbox"]
            context = await p.chromium.launch_persistent_context(**launch_options)
            page = context.pages[0] if context.pages else await context.new_page()

            async def on_response(resp):
                url = resp.url.lower()
                if "search" not in url and "aweme/list" not in url:
                    return
                try:
                    body = await resp.json()
                except Exception:
                    return
                responses.append(body)

            page.on("response", on_response)
            url = f"https://www.douyin.com/search/{quote(keyword)}"
            logger.info("关键词搜索: %s", keyword)
            try:
                await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                await page.wait_for_timeout(max(2000, self.wait_seconds * 1000))
                for _ in range(max(1, self.scrolls)):
                    await page.mouse.wheel(0, 1400)
                    await page.wait_for_timeout(900)
                    if len(results) >= limit:
                        break
            except Exception as exc:
                logger.warning("关键词页面加载失败 %s: %s", keyword, exc)

            for payload in responses:
                for item in self._extract_items(payload):
                    parsed = self._normalize(item, keyword)
                    if not parsed:
                        continue
                    if parsed["create_time"] and parsed["create_time"] < since_ts:
                        continue
                    results[parsed["platform_work_id"]] = parsed

            if not results:
                for item in await self._dom_fallback(page, keyword):
                    if item["create_time"] and item["create_time"] < since_ts:
                        continue
                    results[item["platform_work_id"]] = item

            await context.close()

        ordered = sorted(
            results.values(),
            key=lambda row: (row.get("create_time", 0), row.get("comment_count", 0)),
            reverse=True,
        )
        return ordered[:limit]

    def _extract_items(self, payload) -> list[dict]:
        found: list[dict] = []
        seen: set[str] = set()

        def visit(node):
            if isinstance(node, dict):
                stats = node.get("statistics") or node.get("stats")
                work_id = node.get("aweme_id") or node.get("item_id") or node.get("video_id")
                if work_id and isinstance(stats, dict):
                    key = str(work_id)
                    if key not in seen:
                        seen.add(key)
                        found.append(node)
                for value in node.values():
                    visit(value)
            elif isinstance(node, list):
                for value in node:
                    visit(value)

        visit(payload)
        return found

    def _normalize(self, raw: dict, keyword: str) -> dict | None:
        work_id = raw.get("aweme_id") or raw.get("item_id") or raw.get("video_id")
        if not work_id:
            return None
        stats = raw.get("statistics") or raw.get("stats") or {}
        author = raw.get("author") or {}
        video = raw.get("video") or {}
        cover = video.get("cover") or video.get("origin_cover") or {}
        urls = cover.get("url_list") if isinstance(cover, dict) else []
        hashtags = []
        for item in raw.get("text_extra") or []:
            if isinstance(item, dict) and item.get("hashtag_name"):
                hashtags.append(item["hashtag_name"])

        create_time = self._int(raw.get("create_time"))
        return {
            "platform_work_id": str(work_id),
            "title": raw.get("desc") or raw.get("title") or "",
            "author_name": author.get("nickname") or author.get("unique_id") or "",
            "author_sec_uid": author.get("sec_uid") or "",
            "author_uid": str(author.get("uid") or ""),
            "url": f"https://www.douyin.com/video/{work_id}",
            "content_type": "video",
            "create_time": create_time,
            "cover_url": (urls or [""])[0] if isinstance(urls, list) else "",
            "like_count": self._int(stats.get("digg_count") or stats.get("like_count")),
            "comment_count": self._int(stats.get("comment_count")),
            "share_count": self._int(stats.get("share_count")),
            "collect_count": self._int(
                stats.get("collect_count") or stats.get("collection_count")
                or stats.get("favorite_count")
            ),
            "hashtags": hashtags,
            "source_keyword": keyword,
            "raw_json": raw,
        }

    async def _dom_fallback(self, page, keyword: str) -> list[dict]:
        try:
            items = await page.locator("a[href*='/video/']").evaluate_all(
                """
                nodes => nodes.map(node => ({
                    href: node.href || '',
                    title: (node.innerText || node.textContent || '').trim()
                }))
                """
            )
        except Exception:
            return []

        results = []
        seen = set()
        for item in items:
            match = re.search(r"/video/(\d+)", item.get("href", ""))
            if not match or match.group(1) in seen:
                continue
            seen.add(match.group(1))
            results.append(
                {
                    "platform_work_id": match.group(1),
                    "title": item.get("title", ""),
                    "author_name": "",
                    "author_sec_uid": "",
                    "author_uid": "",
                    "url": item.get("href") or f"https://www.douyin.com/video/{match.group(1)}",
                    "content_type": "video",
                    "create_time": 0,
                    "cover_url": "",
                    "like_count": 0,
                    "comment_count": 0,
                    "share_count": 0,
                    "collect_count": 0,
                    "hashtags": [],
                    "source_keyword": keyword,
                    "raw_json": {"source": "dom_fallback"},
                }
            )
        return results

    @staticmethod
    def _int(value) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

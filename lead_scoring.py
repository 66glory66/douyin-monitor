"""Content Boom + Comment Copilot 的可解释规则层。

评分用于筛选人工复核对象，不等同于真实成交。真实咨询、加微信、成交
必须通过 radar_feedback 手工回填，形成后续校准数据。
"""
import json
import logging
import math
import os
import re
import statistics
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

HIGH_INTENT_TERMS = (
    "怎么买", "购买", "开通", "充值", "哪里买", "怎么买到", "价格", "多少钱",
    "付款", "支付", "升级", "代开", "会员", "额度不够", "支付失败", "能开吗",
    "求链接", "链接", "购买入口", "怎么买会员",
)
MEDIUM_INTENT_TERMS = (
    "plus", "pro", "区别", "哪个好", "怎么用", "国内", "注册", "限制", "额度",
    "体验", "稳定", "教程", "支持", "能用吗", "推荐",
)
SPAM_TERMS = (
    "互关", "抽奖", "广告", "私信我", "加群", "刷单", "兼职", "无关", "哈哈哈哈",
)
PAIN_TERMS = (
    "付款失败", "额度不够", "不会用", "注册不了", "访问不了", "太贵", "限制", "报错",
    "不能用", "没有额度", "被封", "登录失败",
)


def classify_intent(text: str) -> dict:
    """对单条公开评论做意向分层，返回标签、分数和可解释原因。"""
    raw = (text or "").strip()
    normalized = raw.lower()
    if not normalized:
        return {"label": "normal", "score": 0, "reason": "空评论"}

    spam_hits = [term for term in SPAM_TERMS if term in normalized]
    high_hits = [term for term in HIGH_INTENT_TERMS if term in normalized]
    medium_hits = [term for term in MEDIUM_INTENT_TERMS if term in normalized]
    pain_hits = [term for term in PAIN_TERMS if term in normalized]

    if spam_hits and not high_hits and not medium_hits:
        return {"label": "spam", "score": 5, "reason": f"疑似无关/营销词：{'、'.join(spam_hits[:3])}"}

    score = min(100, len(high_hits) * 35 + len(medium_hits) * 16 + len(pain_hits) * 12)
    # 评论越具体，人工复核优先级越高；避免单纯“链接”无限放大。
    if len(raw) >= 8:
        score += 8
    if "?" in raw or "？" in raw:
        score += 5
    score = min(100, score)

    if high_hits or score >= 70:
        label = "high"
    elif medium_hits or score >= 35:
        label = "medium"
    else:
        label = "normal"

    reasons = []
    if high_hits:
        reasons.append(f"高意向词：{'、'.join(high_hits[:3])}")
    if pain_hits:
        reasons.append(f"问题场景：{'、'.join(pain_hits[:2])}")
    if medium_hits:
        reasons.append(f"比较/使用词：{'、'.join(medium_hits[:3])}")
    if not reasons:
        reasons.append("未识别到明确咨询意向")
    return {"label": label, "score": score, "reason": "；".join(reasons)}


def interaction_score(work: dict) -> int:
    """Content Boom Monitor 的互动加权：赞 + 2收藏 + 3评论 + 4分享。"""
    return (
        int(work.get("like_count", 0) or 0)
        + 2 * int(work.get("collect_count", 0) or 0)
        + 3 * int(work.get("comment_count", 0) or 0)
        + 4 * int(work.get("share_count", 0) or 0)
    )


def score_work(work: dict, comments: list[dict], peer_interactions: list[int] | None = None) -> dict:
    """综合作品互动、账号相对表现、新鲜度和评论意向。

    公开搜索结果通常没有播放量和未来增长快照，所以这里不伪造“增长速度”，
    以当前互动、同账号相对比和高意向评论密度组成可复核的初筛分。
    """
    total_comments = max(1, len(comments))
    high_count = sum(1 for c in comments if c.get("intent_label") == "high")
    lead_count = sum(1 for c in comments if c.get("intent_label") in {"high", "medium"})
    intent_density = high_count / total_comments

    current = interaction_score(work)
    peers = [int(x) for x in (peer_interactions or []) if int(x) > 0]
    has_peer_evidence = len(peers) >= 5
    median_peer = statistics.median(peers) if has_peer_evidence else 0
    relative_ratio = current / max(median_peer, 1) if has_peer_evidence else 0

    created = int(work.get("create_time", 0) or 0)
    age_days = (datetime.now().timestamp() - created) / 86400 if created else 7
    freshness_points = max(0.0, min(15.0, 15.0 - max(0.0, age_days) * 2.0))
    interaction_points = min(35.0, math.log1p(max(current, 0)) * 3.1)
    relative_points = (
        min(25.0, max(0.0, math.log1p(relative_ratio) * 16.0))
        if has_peer_evidence else 0.0
    )
    intent_points = min(25.0, intent_density * 25.0 + min(8.0, lead_count * 1.5))
    boom_score = round(min(100.0, interaction_points + relative_points + intent_points + freshness_points), 2)

    path = infer_content_path(work)
    reason = (
        f"互动加权 {current:,}；账号相对倍数 "
        f"{relative_ratio:.2f}{'' if has_peer_evidence else '（同账号样本不足5条）'}；"
        f"高意向 {high_count}/{len(comments)}；近{max(1, round(age_days))}日"
    )
    return {
        "boom_score": boom_score,
        "interaction_score": current,
        "lead_count": lead_count,
        "high_intent_count": high_count,
        "intent_density": round(intent_density, 4),
        "relative_ratio": round(relative_ratio, 4),
        "replicability": replicability_score(work),
        "content_path": path,
        "scoring_reason": reason,
    }


def infer_content_path(work: dict) -> str:
    text = f"{work.get('title', '')} {work.get('transcript', '')}".lower()
    if any(x in text for x in ("测评", "实测", "对比", "评测", "避坑")):
        return "实测/对比/避坑"
    if any(x in text for x in ("教程", "步骤", "怎么用", "教学", "配置")):
        return "教程/步骤"
    if any(x in text for x in ("推荐", "清单", "盘点", "工具", "合集")):
        return "工具清单/推荐"
    if any(x in text for x in ("失败", "报错", "不能", "解决", "问题")):
        return "问题排障"
    return "经验分享/案例"


def replicability_score(work: dict) -> float:
    text = f"{work.get('title', '')} {work.get('transcript', '')}"
    points = 45.0
    if len(text.strip()) >= 30:
        points += 15
    if any(x in text for x in ("步骤", "第一", "第二", "第三", "1.", "2.")):
        points += 15
    if any(x in text for x in ("实测", "截图", "演示", "对比", "案例")):
        points += 15
    if any(x in text for x in ("私信", "加微信", "扫码", "购买")):
        points += 10
    return min(100.0, points)


def analyze_content(work: dict, transcript: str = "", ai_config: dict | None = None) -> dict:
    """拆解开头钩子、痛点、结构、形式、CTA 和承接路径。

    配置了 AI_API_KEY + AI_BASE_URL + AI_MODEL 时，使用兼容 Chat Completions
    的接口增强分析；没有密钥时使用确定性规则，部署仍可运行。
    """
    source = " ".join(x for x in (work.get("title", ""), transcript) if x).strip()
    ai_config = ai_config or {}
    if ai_config.get("enabled"):
        result = _analyze_with_ai(source, work, ai_config)
        if result:
            result["provider"] = "openai-compatible"
            return result

    title = (work.get("title") or "").strip()
    hook = title[:42] or "从评论问题切入：用户到底卡在哪里？"
    pain = next((term for term in PAIN_TERMS if term in source.lower()), "效率、成本或使用门槛")
    path = infer_content_path({**work, "transcript": transcript})
    fmt = "口播/屏幕录制" if transcript else "短标题+演示画面"
    cta = "评论区回复关键词，人工确认需求后承接"
    structure = "3秒痛点 → 过程/对比 → 结果证据 → 评论关键词CTA"
    return {
        "hook": hook,
        "pain_point": pain,
        "structure": structure,
        "content_format": fmt,
        "cta": cta,
        "path": path,
        "replicability": replicability_score({**work, "transcript": transcript}),
        "analysis_json": {"source_length": len(source), "method": "rules"},
        "provider": "rules",
    }


def _analyze_with_ai(source: str, work: dict, config: dict) -> dict | None:
    api_key = config.get("api_key") or os.getenv("AI_API_KEY", "")
    base_url = (config.get("base_url") or os.getenv("AI_BASE_URL", "")).rstrip("/")
    model = config.get("model") or os.getenv("AI_MODEL", "")
    if not (api_key and base_url and model):
        return None
    prompt = (
        "请把下面一条抖音AI工具内容拆解成严格JSON，字段为：hook、pain_point、"
        "structure、content_format、cta、path、replicability（0-100）。"
        "只分析公开内容，不生成自动私信或夸大承诺。\n"
        f"标题/文本：{source[:5000]}\n互动数据：{json.dumps(work, ensure_ascii=False, default=str)[:1000]}"
    )
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=45,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
        data["analysis_json"] = data.copy()
        data["replicability"] = float(data.get("replicability", 0) or 0)
        return data
    except Exception as exc:
        logger.warning("AI 内容拆解失败，回退规则：%s", exc)
        return None

import time

import db
from lead_scoring import analyze_content, classify_intent, interaction_score, score_work
from radar_db import (
    add_feedback,
    get_radar_conversion_summary,
    get_radar_work,
    init_radar_db,
    upsert_radar_comment,
    upsert_work,
)
from radar import RadarRunner


def test_high_intent_comment_is_explainable():
    result = classify_intent("请问 ChatGPT Plus 多少钱，怎么买会员，国内能开吗？")
    assert result["label"] == "high"
    assert result["score"] >= 70
    assert "高意向词" in result["reason"]


def test_spam_comment_is_not_lead():
    result = classify_intent("互关抽奖，私信我")
    assert result["label"] == "spam"


def test_content_boom_formula_and_score():
    work = {
        "title": "付款失败怎么办？ChatGPT Plus 实测避坑",
        "like_count": 1000,
        "collect_count": 100,
        "comment_count": 80,
        "share_count": 20,
        "create_time": int(time.time()) - 86400,
    }
    assert interaction_score(work) == 1000 + 200 + 240 + 80
    comments = [
        {"intent_label": "high", "text": "怎么买"},
        {"intent_label": "medium", "text": "怎么用"},
        {"intent_label": "normal", "text": "学习了"},
    ]
    score = score_work(work, comments, peer_interactions=[500, 800, 900, 1200, 1000])
    assert 0 < score["boom_score"] <= 100
    assert score["high_intent_count"] == 1
    assert score["content_path"] == "实测/对比/避坑"


def test_relative_score_waits_for_five_peer_works():
    score = score_work(
        {"like_count": 100, "comment_count": 1, "create_time": int(time.time())},
        [],
        peer_interactions=[100, 200, 300, 400],
    )
    assert score["relative_ratio"] == 0
    assert "样本不足5条" in score["scoring_reason"]


def test_rules_content_analysis_has_manual_cta():
    result = analyze_content({"title": "AI会员注册不了排障"})
    assert result["pain_point"] == "注册不了"
    assert "人工" in result["cta"]


def test_feedback_closes_conversion_loop(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "radar-test.db")
    db.init_db()
    init_radar_db()
    work_id = upsert_work({
        "platform_work_id": "feedback-test",
        "title": "付款失败怎么办",
        "create_time": int(time.time()),
    })
    comment_id = upsert_radar_comment(work_id, {
        "comment_id": "comment-feedback-test",
        "text": "怎么买",
        "intent_label": "high",
        "intent_score": 80,
    })
    add_feedback(work_id, {
        "comment_db_id": comment_id,
        "consulted": True,
        "added_wechat": True,
        "purchased": True,
        "amount": 130,
    })
    work = get_radar_work(work_id)
    stats = get_radar_conversion_summary(7)
    assert work["consulted_count"] == 1
    assert work["wechat_count"] == 1
    assert work["purchased_count"] == 1
    assert work["revenue"] == 130
    assert stats["purchased"] == 1
    assert stats["revenue"] == 130


def test_radar_runner_full_pipeline_without_network(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "pipeline-test.db")
    db.init_db()
    init_radar_db()

    async def fake_search(self, keyword, days, limit):
        return [{
            "platform_work_id": "pipeline-work",
            "title": "ChatGPT Plus 付款失败怎么办？",
            "author_name": "测试作者",
            "author_sec_uid": "author-pipeline",
            "url": "https://www.douyin.com/video/pipeline-work",
            "create_time": int(time.time()),
            "like_count": 100,
            "comment_count": 3,
            "share_count": 5,
            "collect_count": 10,
            "source_keyword": keyword,
            "raw_json": {},
        }]

    async def fake_comments(self, video_id, **kwargs):
        return [{
            "comment_id": "pipeline-comment",
            "text": "怎么买会员，多少钱？",
            "digg_count": 2,
            "reply_count": 1,
            "user_name": "测试用户",
            "create_time": int(time.time()),
        }]

    monkeypatch.setattr("keyword_spider.KeywordSpider.search", fake_search)
    monkeypatch.setattr("comment_spider.CommentSpider.fetch_comments", fake_comments)
    cfg = {
        "radar": {
            "keywords": ["ChatGPT Plus"], "days": 7, "max_results_per_keyword": 1,
            "max_comments_per_work": 10, "comment_pages": 1, "top_works_for_comments": 1,
            "output_dir": str(tmp_path / "exports"), "ai_enabled": False,
        },
        "spider": {"headless": True},
        "paths": {"session_dir": str(tmp_path / "session")},
    }
    result = __import__("asyncio").run(RadarRunner(config=cfg, headless=True).run())
    assert result["discovered"] == 1
    assert result["works"] == 1
    assert result["errors"] == []
    assert __import__("pathlib").Path(result["files"]["xlsx"]).exists()

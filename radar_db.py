"""关键词雷达的数据层。

雷达表与旧版 creators/videos/comments 表分开，既能复用同一个 SQLite
数据库，也不会改变原有博主监控的数据结构。
"""
import json
from datetime import datetime

from db import get_db


def init_radar_db() -> None:
    with get_db() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS radar_keywords (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                keyword TEXT NOT NULL UNIQUE,
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS radar_works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform_work_id TEXT NOT NULL UNIQUE,
                title TEXT,
                author_name TEXT,
                author_sec_uid TEXT,
                author_uid TEXT,
                url TEXT,
                content_type TEXT DEFAULT 'video',
                create_time INTEGER,
                cover_url TEXT,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                source_keyword TEXT,
                raw_json TEXT DEFAULT '{}',
                first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                boom_score REAL DEFAULT 0,
                lead_count INTEGER DEFAULT 0,
                high_intent_count INTEGER DEFAULT 0,
                intent_density REAL DEFAULT 0,
                relative_ratio REAL DEFAULT 0,
                replicability REAL DEFAULT 0,
                content_path TEXT DEFAULT '',
                scoring_reason TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS radar_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL REFERENCES radar_works(id) ON DELETE CASCADE,
                like_count INTEGER DEFAULT 0,
                comment_count INTEGER DEFAULT 0,
                share_count INTEGER DEFAULT 0,
                collect_count INTEGER DEFAULT 0,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS radar_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL REFERENCES radar_works(id) ON DELETE CASCADE,
                comment_id TEXT NOT NULL,
                parent_comment_id TEXT DEFAULT '',
                is_reply INTEGER NOT NULL DEFAULT 0,
                text TEXT,
                digg_count INTEGER DEFAULT 0,
                reply_count INTEGER DEFAULT 0,
                user_name TEXT,
                ip_label TEXT,
                create_time INTEGER,
                first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                intent_label TEXT DEFAULT 'normal',
                intent_score REAL DEFAULT 0,
                intent_reason TEXT DEFAULT '',
                reviewed INTEGER NOT NULL DEFAULT 0,
                feedback_status TEXT DEFAULT '',
                UNIQUE(work_id, comment_id)
            );

            CREATE TABLE IF NOT EXISTS radar_content_analysis (
                work_id INTEGER PRIMARY KEY REFERENCES radar_works(id) ON DELETE CASCADE,
                hook TEXT DEFAULT '',
                pain_point TEXT DEFAULT '',
                structure TEXT DEFAULT '',
                content_format TEXT DEFAULT '',
                cta TEXT DEFAULT '',
                path TEXT DEFAULT '',
                replicability REAL DEFAULT 0,
                analysis_json TEXT DEFAULT '{}',
                provider TEXT DEFAULT 'rules',
                analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS radar_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                work_id INTEGER NOT NULL REFERENCES radar_works(id) ON DELETE CASCADE,
                comment_id INTEGER REFERENCES radar_comments(id) ON DELETE SET NULL,
                consulted INTEGER NOT NULL DEFAULT 0,
                added_wechat INTEGER NOT NULL DEFAULT 0,
                purchased INTEGER NOT NULL DEFAULT 0,
                product TEXT DEFAULT '',
                amount REAL DEFAULT 0,
                note TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_radar_works_create_time
                ON radar_works(create_time);
            CREATE INDEX IF NOT EXISTS idx_radar_works_score
                ON radar_works(boom_score DESC);
            CREATE INDEX IF NOT EXISTS idx_radar_comments_intent
                ON radar_comments(intent_label, intent_score DESC);
            """
        )


def upsert_keyword(keyword: str) -> int:
    keyword = keyword.strip()
    if not keyword:
        return 0
    with get_db() as db:
        db.execute(
            "INSERT INTO radar_keywords(keyword) VALUES (?) "
            "ON CONFLICT(keyword) DO UPDATE SET enabled=1",
            (keyword,),
        )
        row = db.execute("SELECT id FROM radar_keywords WHERE keyword=?", (keyword,)).fetchone()
        db.commit()
        return int(row["id"])


def list_keywords(enabled_only: bool = True) -> list[dict]:
    with get_db() as db:
        where = "WHERE enabled=1" if enabled_only else ""
        rows = db.execute(
            f"SELECT * FROM radar_keywords {where} ORDER BY id"
        ).fetchall()
        return [dict(row) for row in rows]


def upsert_work(work: dict) -> int:
    raw = work.get("raw_json", {})
    raw_json = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    fields = (
        work.get("platform_work_id", ""), work.get("title", ""),
        work.get("author_name", ""), work.get("author_sec_uid", ""),
        work.get("author_uid", ""), work.get("url", ""),
        work.get("content_type", "video"), work.get("create_time", 0),
        work.get("cover_url", ""), work.get("like_count", 0),
        work.get("comment_count", 0), work.get("share_count", 0),
        work.get("collect_count", 0), work.get("source_keyword", ""), raw_json,
    )
    with get_db() as db:
        row = db.execute(
            """
            INSERT INTO radar_works(
                platform_work_id,title,author_name,author_sec_uid,author_uid,url,
                content_type,create_time,cover_url,like_count,comment_count,
                share_count,collect_count,source_keyword,raw_json
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(platform_work_id) DO UPDATE SET
                title=excluded.title, author_name=excluded.author_name,
                author_sec_uid=excluded.author_sec_uid, author_uid=excluded.author_uid,
                url=excluded.url, content_type=excluded.content_type,
                create_time=excluded.create_time, cover_url=excluded.cover_url,
                like_count=excluded.like_count, comment_count=excluded.comment_count,
                share_count=excluded.share_count, collect_count=excluded.collect_count,
                source_keyword=excluded.source_keyword, raw_json=excluded.raw_json,
                last_seen_at=CURRENT_TIMESTAMP
            RETURNING id
            """,
            fields,
        ).fetchone()
        db.commit()
        return int(row["id"])


def add_work_snapshot(work_id: int, work: dict) -> None:
    with get_db() as db:
        db.execute(
            """
            INSERT INTO radar_snapshots(work_id,like_count,comment_count,share_count,collect_count)
            VALUES (?,?,?,?,?)
            """,
            (
                work_id, work.get("like_count", 0), work.get("comment_count", 0),
                work.get("share_count", 0), work.get("collect_count", 0),
            ),
        )
        db.commit()


def upsert_radar_comment(work_id: int, comment: dict) -> int:
    with get_db() as db:
        row = db.execute(
            """
            INSERT INTO radar_comments(
                work_id,comment_id,parent_comment_id,is_reply,text,digg_count,
                reply_count,user_name,ip_label,create_time,intent_label,intent_score,intent_reason
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(work_id,comment_id) DO UPDATE SET
                parent_comment_id=excluded.parent_comment_id, is_reply=excluded.is_reply,
                text=excluded.text, digg_count=excluded.digg_count,
                reply_count=excluded.reply_count, user_name=excluded.user_name,
                ip_label=excluded.ip_label, create_time=excluded.create_time,
                last_seen=CURRENT_TIMESTAMP, intent_label=excluded.intent_label,
                intent_score=excluded.intent_score, intent_reason=excluded.intent_reason
            RETURNING id
            """,
            (
                work_id, str(comment.get("comment_id", "")),
                str(comment.get("parent_comment_id", "") or ""),
                int(bool(comment.get("is_reply", False))), comment.get("text", ""),
                comment.get("digg_count", 0), comment.get("reply_count", 0),
                comment.get("user_name", ""), comment.get("ip_label", ""),
                comment.get("create_time", 0), comment.get("intent_label", "normal"),
                comment.get("intent_score", 0), comment.get("intent_reason", ""),
            ),
        ).fetchone()
        db.commit()
        return int(row["id"])


def update_work_score(work_id: int, score: dict) -> None:
    with get_db() as db:
        db.execute(
            """
            UPDATE radar_works SET boom_score=?, lead_count=?, high_intent_count=?,
                intent_density=?, relative_ratio=?, replicability=?, content_path=?,
                scoring_reason=? WHERE id=?
            """,
            (
                score.get("boom_score", 0), score.get("lead_count", 0),
                score.get("high_intent_count", 0), score.get("intent_density", 0),
                score.get("relative_ratio", 0), score.get("replicability", 0),
                score.get("content_path", ""), score.get("scoring_reason", ""), work_id,
            ),
        )
        db.commit()


def upsert_content_analysis(work_id: int, analysis: dict) -> None:
    analysis_json = analysis.get("analysis_json", analysis)
    if not isinstance(analysis_json, str):
        analysis_json = json.dumps(analysis_json, ensure_ascii=False)
    with get_db() as db:
        db.execute(
            """
            INSERT INTO radar_content_analysis(
                work_id,hook,pain_point,structure,content_format,cta,path,
                replicability,analysis_json,provider
            ) VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(work_id) DO UPDATE SET
                hook=excluded.hook, pain_point=excluded.pain_point,
                structure=excluded.structure, content_format=excluded.content_format,
                cta=excluded.cta, path=excluded.path,
                replicability=excluded.replicability, analysis_json=excluded.analysis_json,
                provider=excluded.provider, analyzed_at=CURRENT_TIMESTAMP
            """,
            (
                work_id, analysis.get("hook", ""), analysis.get("pain_point", ""),
                analysis.get("structure", ""), analysis.get("content_format", ""),
                analysis.get("cta", ""), analysis.get("path", ""),
                analysis.get("replicability", 0), analysis_json,
                analysis.get("provider", "rules"),
            ),
        )
        db.commit()


def add_feedback(work_id: int, feedback: dict) -> int:
    """保存人工转化结果，并把状态同步到对应评论。"""
    with get_db() as db:
        comment_value = feedback.get("comment_db_id") or feedback.get("comment_id")
        comment_db_id = None
        if comment_value not in (None, ""):
            row = db.execute(
                "SELECT id FROM radar_comments WHERE work_id=? AND (id=? OR comment_id=?)",
                (work_id, comment_value, str(comment_value)),
            ).fetchone()
            comment_db_id = row["id"] if row else None

        consulted = int(bool(feedback.get("consulted")))
        added_wechat = int(bool(feedback.get("added_wechat")))
        purchased = int(bool(feedback.get("purchased")))
        cur = db.execute(
            """
            INSERT INTO radar_feedback(
                work_id,comment_id,consulted,added_wechat,purchased,product,amount,note
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                work_id, comment_db_id, consulted, added_wechat, purchased,
                feedback.get("product", ""), float(feedback.get("amount", 0) or 0),
                feedback.get("note", ""),
            ),
        )
        if comment_db_id:
            status = "purchased" if purchased else "added_wechat" if added_wechat else "consulted" if consulted else "reviewed"
            db.execute(
                "UPDATE radar_comments SET reviewed=1, feedback_status=? WHERE id=?",
                (status, comment_db_id),
            )
        db.commit()
        return int(cur.lastrowid)


def list_radar_works(limit: int = 50, days: int = 7) -> list[dict]:
    with get_db() as db:
        rows = db.execute(
            """
            SELECT w.*, a.hook, a.pain_point, a.structure, a.content_format,
                   a.cta, a.path, a.provider AS analysis_provider,
                   COALESCE(SUM(f.consulted), 0) AS consulted_count,
                   COALESCE(SUM(f.added_wechat), 0) AS wechat_count,
                   COALESCE(SUM(f.purchased), 0) AS purchased_count,
                   COALESCE(SUM(f.amount), 0) AS revenue
            FROM radar_works w
            LEFT JOIN radar_content_analysis a ON a.work_id=w.id
            LEFT JOIN radar_feedback f ON f.work_id=w.id
            WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0
            GROUP BY w.id
            ORDER BY w.boom_score DESC, w.comment_count DESC, w.create_time DESC
            LIMIT ?
            """,
            (int(datetime.now().timestamp()) - days * 86400, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def list_radar_comments(work_id: int | None = None, limit: int = 200) -> list[dict]:
    with get_db() as db:
        if work_id:
            rows = db.execute(
                "SELECT * FROM radar_comments WHERE work_id=? "
                "ORDER BY intent_score DESC, digg_count DESC LIMIT ?",
                (work_id, limit),
            ).fetchall()
        else:
            rows = db.execute(
                """
                SELECT c.*, w.title, w.platform_work_id
                FROM radar_comments c JOIN radar_works w ON w.id=c.work_id
                ORDER BY c.intent_score DESC, c.digg_count DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


def get_radar_work(work_id: int) -> dict | None:
    with get_db() as db:
        row = db.execute(
            """
            SELECT w.*, a.hook, a.pain_point, a.structure, a.content_format,
                   a.cta, a.path, a.provider AS analysis_provider,
                   COALESCE(SUM(f.consulted), 0) AS consulted_count,
                   COALESCE(SUM(f.added_wechat), 0) AS wechat_count,
                   COALESCE(SUM(f.purchased), 0) AS purchased_count,
                   COALESCE(SUM(f.amount), 0) AS revenue
            FROM radar_works w LEFT JOIN radar_content_analysis a ON a.work_id=w.id
            LEFT JOIN radar_feedback f ON f.work_id=w.id
            WHERE w.id=?
            GROUP BY w.id
            """,
            (work_id,),
        ).fetchone()
        return dict(row) if row else None


def get_radar_conversion_summary(days: int = 7) -> dict:
    """统计人工回填的咨询、加微信、成交，不把公开评论冒充真实客户。"""
    since = int(datetime.now().timestamp()) - max(1, days) * 86400
    with get_db() as db:
        row = db.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM radar_works w
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS works,
                (SELECT COUNT(*) FROM radar_comments c JOIN radar_works w ON w.id=c.work_id
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS comments,
                (SELECT COUNT(*) FROM radar_comments c JOIN radar_works w ON w.id=c.work_id
                 WHERE c.intent_label='high' AND (w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0)) AS high_intent_comments,
                (SELECT COALESCE(SUM(f.consulted), 0) FROM radar_feedback f JOIN radar_works w ON w.id=f.work_id
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS consulted,
                (SELECT COALESCE(SUM(f.added_wechat), 0) FROM radar_feedback f JOIN radar_works w ON w.id=f.work_id
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS added_wechat,
                (SELECT COALESCE(SUM(f.purchased), 0) FROM radar_feedback f JOIN radar_works w ON w.id=f.work_id
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS purchased,
                (SELECT COALESCE(SUM(f.amount), 0) FROM radar_feedback f JOIN radar_works w ON w.id=f.work_id
                 WHERE w.create_time >= ? OR w.create_time IS NULL OR w.create_time=0) AS revenue
            """,
            (since, since, since, since, since, since, since),
        ).fetchone()
    result = dict(row) if row else {}
    for key in ("works", "comments", "high_intent_comments", "consulted", "added_wechat", "purchased"):
        result[key] = int(result.get(key) or 0)
    result["revenue"] = float(result.get("revenue") or 0)
    result["consult_rate"] = round(result["consulted"] / max(result["high_intent_comments"], 1), 4)
    result["wechat_rate"] = round(result["added_wechat"] / max(result["consulted"], 1), 4)
    result["purchase_rate"] = round(result["purchased"] / max(result["added_wechat"], 1), 4)
    return result

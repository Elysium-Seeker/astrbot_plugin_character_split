import asyncio
import json
import math
import os
import random
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

SCOPE_GLOBAL = "global"
SCOPE_MODE = "mode"
SCOPE_SESSION = "session"
ALLOWED_SCOPES = (SCOPE_GLOBAL, SCOPE_MODE, SCOPE_SESSION)


class MemoryManager:
    def __init__(self, data_dir: str, logger: Any):
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "character_split_mem.db")
        self.logger = logger
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    CREATE TABLE IF NOT EXISTS mode_memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        umo TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        importance INTEGER DEFAULT 5,
                        scope TEXT DEFAULT 'mode',
                        period_id INTEGER DEFAULT 0,
                        source TEXT DEFAULT 'summary',
                        last_used_at DATETIME
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_umo_mode ON mode_memories (umo, mode)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_umo_scope ON mode_memories (umo, scope)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_umo_mode_scope ON mode_memories (umo, mode, scope)"
                )
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_umo_mode_period ON mode_memories (umo, mode, period_id)"
                )

                # legacy schema migrations
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN importance INTEGER DEFAULT 5")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN scope TEXT DEFAULT 'mode'")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN period_id INTEGER DEFAULT 0")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN source TEXT DEFAULT 'summary'")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN last_used_at DATETIME")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
        except Exception as exc:
            self.logger.error(f"Failed to initialize memory DB: {exc}")

    @staticmethod
    def _safe_int(raw: Any, default: int = 0) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _normalize_scope(scope: str) -> str:
        normalized = (scope or SCOPE_MODE).strip().lower()
        return normalized if normalized in ALLOWED_SCOPES else SCOPE_MODE

    @staticmethod
    def _normalize_importance(raw: Any) -> int:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 5
        return max(1, min(10, value))

    @staticmethod
    def _parse_timestamp(raw: Any) -> Optional[datetime]:
        text = str(raw or "").strip()
        if not text:
            return None

        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            pass

        formats = ["%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"]
        for fmt in formats:
            try:
                dt = datetime.strptime(text, fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    @staticmethod
    def _row_to_memory(row: Any) -> Dict[str, Any]:
        return {
            "id": row[0],
            "mode": row[1],
            "scope": row[2],
            "title": row[3],
            "content": row[4],
            "timestamp": row[5],
            "importance": row[6],
            "period_id": row[7],
            "source": row[8],
        }

    def _effective_importance(
        self,
        item: Dict[str, Any],
        global_no_decay_min_importance: int,
        global_half_life_days: int,
        mode_half_life_days: int,
        session_half_life_days: int,
        low_importance_decay_boost: float,
    ) -> float:
        base = float(self._normalize_importance(item.get("importance", 5)))
        scope = self._normalize_scope(str(item.get("scope", SCOPE_MODE)))

        if scope == SCOPE_GLOBAL and base >= float(max(1, global_no_decay_min_importance)):
            return base

        if scope == SCOPE_GLOBAL:
            half_life_days = max(1.0, float(global_half_life_days))
        elif scope == SCOPE_MODE:
            half_life_days = max(1.0, float(mode_half_life_days))
        else:
            half_life_days = max(1.0, float(session_half_life_days))

        dt = self._parse_timestamp(item.get("timestamp"))
        if dt is None:
            return base

        now = datetime.now(timezone.utc)
        age_seconds = max(0.0, (now - dt.astimezone(timezone.utc)).total_seconds())
        age_days = age_seconds / 86400.0

        priority_factor = 1.0 + ((10.0 - base) / 9.0) * max(0.0, float(low_importance_decay_boost))
        decay = math.exp(-math.log(2.0) * age_days * priority_factor / half_life_days)
        return base * decay

    def _rank_memories(
        self,
        items: List[Dict[str, Any]],
        global_no_decay_min_importance: int,
        global_half_life_days: int,
        mode_half_life_days: int,
        session_half_life_days: int,
        low_importance_decay_boost: float,
    ) -> List[Dict[str, Any]]:
        ranked: List[Dict[str, Any]] = []
        for item in items:
            cloned = dict(item)
            cloned["_score"] = self._effective_importance(
                cloned,
                global_no_decay_min_importance=global_no_decay_min_importance,
                global_half_life_days=global_half_life_days,
                mode_half_life_days=mode_half_life_days,
                session_half_life_days=session_half_life_days,
                low_importance_decay_boost=low_importance_decay_boost,
            )
            ranked.append(cloned)

        ranked.sort(
            key=lambda x: (
                float(x.get("_score", 0.0)),
                self._normalize_importance(x.get("importance", 5)),
                self._safe_int(x.get("id"), 0),
            ),
            reverse=True,
        )
        return ranked

    @staticmethod
    def _strip_rank_fields(item: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = dict(item)
        cleaned.pop("_score", None)
        return cleaned

    def _query_scope_rows(
        self,
        cursor: sqlite3.Cursor,
        umo: str,
        mode: str,
        scope: str,
        min_id: int = 0,
        period_id: Optional[int] = None,
        exclude_ids: Optional[Sequence[int]] = None,
        candidate_size: int = 80,
    ) -> List[Dict[str, Any]]:
        normalized_scope = self._normalize_scope(scope)
        params: List[Any] = [umo, normalized_scope]
        query = (
            "SELECT id, mode, scope, title, content, timestamp, importance, period_id, source "
            "FROM mode_memories WHERE umo = ? AND scope = ?"
        )

        if normalized_scope != SCOPE_GLOBAL:
            query += " AND mode = ?"
            params.append(mode)

        safe_min_id = max(0, self._safe_int(min_id, 0))
        if safe_min_id > 0:
            query += " AND id > ?"
            params.append(safe_min_id)

        if period_id is not None:
            query += " AND period_id = ?"
            params.append(max(0, self._safe_int(period_id, 0)))

        safe_excludes = [max(0, self._safe_int(i, 0)) for i in (exclude_ids or []) if self._safe_int(i, 0) > 0]
        if safe_excludes:
            placeholders = ",".join("?" for _ in safe_excludes)
            query += f" AND id NOT IN ({placeholders})"
            params.extend(safe_excludes)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, self._safe_int(candidate_size, 80)))

        cursor.execute(query, tuple(params))
        return [self._row_to_memory(row) for row in cursor.fetchall()]

    def _pick_surprise_memory(
        self,
        cursor: sqlite3.Cursor,
        umo: str,
        mode: str,
        excluded_ids: Optional[Sequence[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        query = (
            "SELECT id, mode, scope, title, content, timestamp, importance, period_id, source "
            "FROM mode_memories WHERE umo = ? AND mode = ? AND scope IN (?, ?)"
        )
        params: List[Any] = [umo, mode, SCOPE_MODE, SCOPE_SESSION]

        safe_excludes = [max(0, self._safe_int(i, 0)) for i in (excluded_ids or []) if self._safe_int(i, 0) > 0]
        if safe_excludes:
            placeholders = ",".join("?" for _ in safe_excludes)
            query += f" AND id NOT IN ({placeholders})"
            params.extend(safe_excludes)

        query += " ORDER BY id ASC LIMIT 180"
        cursor.execute(query, tuple(params))
        rows = [self._row_to_memory(row) for row in cursor.fetchall()]
        if not rows:
            return None

        older: List[Dict[str, Any]] = []
        now = datetime.now(timezone.utc)
        for item in rows:
            dt = self._parse_timestamp(item.get("timestamp"))
            if dt is None:
                continue
            age_days = (now - dt.astimezone(timezone.utc)).total_seconds() / 86400.0
            if age_days >= 1.0:
                older.append(item)

        pool = older if older else rows
        if not pool:
            return None

        older_half_count = max(1, len(pool) // 2)
        surprise_pool = pool[:older_half_count]
        return random.choice(surprise_pool)

    async def add_memory(
        self,
        umo: str,
        mode: str,
        title: str,
        content: str,
        importance: int = 5,
        scope: str = SCOPE_MODE,
        period_id: int = 0,
        source: str = "summary",
    ) -> int:
        def _add() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    (
                        "INSERT INTO mode_memories "
                        "(umo, mode, title, content, importance, scope, period_id, source) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                    ),
                    (
                        umo,
                        mode,
                        title.strip(),
                        content.strip(),
                        self._normalize_importance(importance),
                        self._normalize_scope(scope),
                        max(0, self._safe_int(period_id, 0)),
                        str(source or "summary").strip() or "summary",
                    ),
                )
                conn.commit()
                return int(cursor.lastrowid)

        try:
            return await asyncio.to_thread(_add)
        except Exception as exc:
            self.logger.error(f"Failed to add memory: {exc}")
            return -1

    async def get_layered_memories(
        self,
        umo: str,
        mode: str,
        global_limit: int = 5,
        mode_limit: int = 5,
        session_limit: int = 5,
        min_global_id: int = 0,
        min_mode_id: int = 0,
        min_session_id: int = 0,
        global_no_decay_min_importance: int = 9,
        global_half_life_days: int = 180,
        mode_half_life_days: int = 30,
        session_half_life_days: int = 3,
        low_importance_decay_boost: float = 1.0,
        surprise_probability: float = 0.0,
        surprise_max_items: int = 0,
    ) -> Dict[str, List[Dict[str, Any]]]:
        def _safe_limit(value: Any) -> int:
            try:
                num = int(value)
            except (TypeError, ValueError):
                num = 0
            return max(0, num)

        def _get() -> Dict[str, List[Dict[str, Any]]]:
            layers: Dict[str, List[Dict[str, Any]]] = {
                SCOPE_GLOBAL: [],
                SCOPE_MODE: [],
                SCOPE_SESSION: [],
            }

            global_size = _safe_limit(global_limit)
            mode_size = _safe_limit(mode_limit)
            session_size = _safe_limit(session_limit)

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if global_size > 0:
                    global_rows = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_GLOBAL,
                        min_id=min_global_id,
                        candidate_size=max(80, global_size * 10),
                    )
                    global_ranked = self._rank_memories(
                        global_rows,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )
                    layers[SCOPE_GLOBAL] = global_ranked[:global_size]

                if mode_size > 0:
                    mode_rows = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_MODE,
                        min_id=min_mode_id,
                        candidate_size=max(80, mode_size * 10),
                    )
                    mode_ranked = self._rank_memories(
                        mode_rows,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )
                    layers[SCOPE_MODE] = mode_ranked[:mode_size]

                if session_size > 0:
                    session_rows = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_SESSION,
                        min_id=min_session_id,
                        candidate_size=max(80, session_size * 10),
                    )
                    session_ranked = self._rank_memories(
                        session_rows,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )
                    layers[SCOPE_SESSION] = session_ranked[:session_size]

                surprise_count = max(0, self._safe_int(surprise_max_items, 0))
                if surprise_count > 0 and float(surprise_probability) > 0:
                    all_ids = {
                        item["id"]
                        for scope_items in layers.values()
                        for item in scope_items
                        if self._safe_int(item.get("id"), 0) > 0
                    }
                    for _ in range(surprise_count):
                        if random.random() > float(surprise_probability):
                            continue

                        surprise = self._pick_surprise_memory(
                            cursor,
                            umo=umo,
                            mode=mode,
                            excluded_ids=list(all_ids),
                        )
                        if not surprise:
                            continue

                        scope = self._normalize_scope(str(surprise.get("scope", SCOPE_MODE)))
                        if scope not in {SCOPE_MODE, SCOPE_SESSION}:
                            continue

                        all_ids.add(self._safe_int(surprise.get("id"), 0))
                        layers[scope].append(surprise)

                        scope_limit = mode_size if scope == SCOPE_MODE else session_size
                        if scope_limit <= 0:
                            layers[scope] = []
                            continue

                        reranked = self._rank_memories(
                            layers[scope],
                            global_no_decay_min_importance=global_no_decay_min_importance,
                            global_half_life_days=global_half_life_days,
                            mode_half_life_days=mode_half_life_days,
                            session_half_life_days=session_half_life_days,
                            low_importance_decay_boost=low_importance_decay_boost,
                        )
                        layers[scope] = reranked[:scope_limit]

            return {
                SCOPE_GLOBAL: [self._strip_rank_fields(i) for i in layers[SCOPE_GLOBAL]],
                SCOPE_MODE: [self._strip_rank_fields(i) for i in layers[SCOPE_MODE]],
                SCOPE_SESSION: [self._strip_rank_fields(i) for i in layers[SCOPE_SESSION]],
            }

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            self.logger.error(f"Failed to get layered memories: {exc}")
            return {SCOPE_GLOBAL: [], SCOPE_MODE: [], SCOPE_SESSION: []}

    async def get_period_layered_memories(
        self,
        umo: str,
        mode: str,
        period_id: int,
        mode_limit: int = 5,
        session_limit: int = 5,
        include_bonus: bool = True,
        bonus_limit: int = 1,
        fallback_to_recent: bool = True,
        global_no_decay_min_importance: int = 9,
        global_half_life_days: int = 180,
        mode_half_life_days: int = 30,
        session_half_life_days: int = 3,
        low_importance_decay_boost: float = 1.0,
    ) -> Dict[str, List[Dict[str, Any]]]:
        safe_period = max(0, self._safe_int(period_id, 0))
        safe_mode_limit = max(0, self._safe_int(mode_limit, 0))
        safe_session_limit = max(0, self._safe_int(session_limit, 0))

        if safe_mode_limit <= 0 and safe_session_limit <= 0:
            return {SCOPE_GLOBAL: [], SCOPE_MODE: [], SCOPE_SESSION: []}

        if safe_period <= 0 and fallback_to_recent:
            recent = await self.get_layered_memories(
                umo,
                mode,
                global_limit=0,
                mode_limit=safe_mode_limit,
                session_limit=safe_session_limit,
                global_no_decay_min_importance=global_no_decay_min_importance,
                global_half_life_days=global_half_life_days,
                mode_half_life_days=mode_half_life_days,
                session_half_life_days=session_half_life_days,
                low_importance_decay_boost=low_importance_decay_boost,
            )
            recent[SCOPE_GLOBAL] = []
            return recent

        def _get() -> Dict[str, List[Dict[str, Any]]]:
            layers: Dict[str, List[Dict[str, Any]]] = {
                SCOPE_GLOBAL: [],
                SCOPE_MODE: [],
                SCOPE_SESSION: [],
            }

            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()

                if safe_mode_limit > 0:
                    mode_rows = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_MODE,
                        period_id=safe_period,
                        candidate_size=max(60, safe_mode_limit * 8),
                    )
                    mode_ranked = self._rank_memories(
                        mode_rows,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )
                    layers[SCOPE_MODE] = mode_ranked[:safe_mode_limit]

                if safe_session_limit > 0:
                    session_rows = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_SESSION,
                        period_id=safe_period,
                        candidate_size=max(60, safe_session_limit * 8),
                    )
                    session_ranked = self._rank_memories(
                        session_rows,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )
                    layers[SCOPE_SESSION] = session_ranked[:safe_session_limit]

                if not layers[SCOPE_MODE] and not layers[SCOPE_SESSION] and fallback_to_recent:
                    if safe_mode_limit > 0:
                        fallback_mode_rows = self._query_scope_rows(
                            cursor,
                            umo=umo,
                            mode=mode,
                            scope=SCOPE_MODE,
                            candidate_size=max(80, safe_mode_limit * 8),
                        )
                        fallback_mode_ranked = self._rank_memories(
                            fallback_mode_rows,
                            global_no_decay_min_importance=global_no_decay_min_importance,
                            global_half_life_days=global_half_life_days,
                            mode_half_life_days=mode_half_life_days,
                            session_half_life_days=session_half_life_days,
                            low_importance_decay_boost=low_importance_decay_boost,
                        )
                        layers[SCOPE_MODE] = fallback_mode_ranked[:safe_mode_limit]

                    if safe_session_limit > 0:
                        fallback_session_rows = self._query_scope_rows(
                            cursor,
                            umo=umo,
                            mode=mode,
                            scope=SCOPE_SESSION,
                            candidate_size=max(80, safe_session_limit * 8),
                        )
                        fallback_session_ranked = self._rank_memories(
                            fallback_session_rows,
                            global_no_decay_min_importance=global_no_decay_min_importance,
                            global_half_life_days=global_half_life_days,
                            mode_half_life_days=mode_half_life_days,
                            session_half_life_days=session_half_life_days,
                            low_importance_decay_boost=low_importance_decay_boost,
                        )
                        layers[SCOPE_SESSION] = fallback_session_ranked[:safe_session_limit]

                safe_bonus_limit = max(0, self._safe_int(bonus_limit, 0))
                if include_bonus and safe_bonus_limit > 0:
                    excluded_ids = {
                        self._safe_int(item.get("id"), 0)
                        for item in (layers[SCOPE_MODE] + layers[SCOPE_SESSION])
                        if self._safe_int(item.get("id"), 0) > 0
                    }

                    bonus_mode = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_MODE,
                        exclude_ids=list(excluded_ids),
                        candidate_size=max(80, safe_bonus_limit * 20),
                    )
                    bonus_session = self._query_scope_rows(
                        cursor,
                        umo=umo,
                        mode=mode,
                        scope=SCOPE_SESSION,
                        exclude_ids=list(excluded_ids),
                        candidate_size=max(80, safe_bonus_limit * 20),
                    )

                    if safe_period > 0:
                        bonus_mode = [m for m in bonus_mode if self._safe_int(m.get("period_id"), 0) != safe_period]
                        bonus_session = [m for m in bonus_session if self._safe_int(m.get("period_id"), 0) != safe_period]

                    bonus_all = bonus_mode + bonus_session
                    bonus_ranked = self._rank_memories(
                        bonus_all,
                        global_no_decay_min_importance=global_no_decay_min_importance,
                        global_half_life_days=global_half_life_days,
                        mode_half_life_days=mode_half_life_days,
                        session_half_life_days=session_half_life_days,
                        low_importance_decay_boost=low_importance_decay_boost,
                    )

                    for item in bonus_ranked[:safe_bonus_limit]:
                        scope = self._normalize_scope(str(item.get("scope", SCOPE_MODE)))
                        if scope not in {SCOPE_MODE, SCOPE_SESSION}:
                            continue

                        layers[scope].append(item)
                        scope_limit = safe_mode_limit if scope == SCOPE_MODE else safe_session_limit
                        if scope_limit <= 0:
                            layers[scope] = []
                            continue

                        reranked = self._rank_memories(
                            layers[scope],
                            global_no_decay_min_importance=global_no_decay_min_importance,
                            global_half_life_days=global_half_life_days,
                            mode_half_life_days=mode_half_life_days,
                            session_half_life_days=session_half_life_days,
                            low_importance_decay_boost=low_importance_decay_boost,
                        )
                        layers[scope] = reranked[:scope_limit]

            return {
                SCOPE_GLOBAL: [],
                SCOPE_MODE: [self._strip_rank_fields(i) for i in layers[SCOPE_MODE]],
                SCOPE_SESSION: [self._strip_rank_fields(i) for i in layers[SCOPE_SESSION]],
            }

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            self.logger.error(f"Failed to get period layered memories: {exc}")
            return {SCOPE_GLOBAL: [], SCOPE_MODE: [], SCOPE_SESSION: []}

    async def get_recent_memories(
        self,
        umo: str,
        mode: str,
        limit: int = 5,
        strategy: str = "recent",
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, self._safe_int(limit, 5))
        layers = await self.get_layered_memories(
            umo,
            mode,
            global_limit=safe_limit,
            mode_limit=safe_limit,
            session_limit=safe_limit,
        )
        merged = layers.get(SCOPE_GLOBAL, []) + layers.get(SCOPE_MODE, []) + layers.get(SCOPE_SESSION, [])
        if strategy == "recent":
            merged.sort(key=lambda item: self._safe_int(item.get("id"), 0), reverse=True)
        else:
            merged.sort(
                key=lambda item: (
                    self._normalize_importance(item.get("importance", 5)),
                    self._safe_int(item.get("id"), 0),
                ),
                reverse=True,
            )
        return merged[:safe_limit]

    async def remove_memory(self, umo: str, mem_id: int) -> bool:
        def _remove() -> bool:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM mode_memories WHERE umo = ? AND id = ?", (umo, mem_id))
                conn.commit()
                return cursor.rowcount > 0

        try:
            return await asyncio.to_thread(_remove)
        except Exception as exc:
            self.logger.error(f"Failed to remove memory: {exc}")
            return False

    async def clear_memories(self, umo: str, mode: Optional[str] = None, scope: Optional[str] = None) -> int:
        safe_scope = self._normalize_scope(scope) if scope else None
        safe_mode = str(mode or "").strip().lower()

        def _clear() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = "DELETE FROM mode_memories WHERE umo = ?"
                params: List[Any] = [umo]

                if safe_scope:
                    query += " AND scope = ?"
                    params.append(safe_scope)

                if safe_mode and safe_scope != SCOPE_GLOBAL:
                    query += " AND mode = ?"
                    params.append(safe_mode)

                cursor.execute(query, tuple(params))
                conn.commit()
                return int(cursor.rowcount)

        try:
            return await asyncio.to_thread(_clear)
        except Exception as exc:
            self.logger.error(f"Failed to clear memories: {exc}")
            return 0

    async def mark_memories_used(self, memory_ids: Sequence[int]) -> int:
        safe_ids = [max(0, self._safe_int(i, 0)) for i in memory_ids if self._safe_int(i, 0) > 0]
        if not safe_ids:
            return 0

        def _mark() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                placeholders = ",".join("?" for _ in safe_ids)
                query = f"UPDATE mode_memories SET last_used_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders})"
                cursor.execute(query, tuple(safe_ids))
                conn.commit()
                return int(cursor.rowcount)

        try:
            return await asyncio.to_thread(_mark)
        except Exception as exc:
            self.logger.error(f"Failed to mark memories used: {exc}")
            return 0

    async def get_memory_total(self, umo: str) -> int:
        def _count() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM mode_memories WHERE umo = ?", (umo,))
                row = cursor.fetchone()
                return int(row[0]) if row else 0

        try:
            return await asyncio.to_thread(_count)
        except Exception as exc:
            self.logger.error(f"Failed to count memories: {exc}")
            return 0

    async def _get_compaction_source_memories(
        self,
        umo: str,
        source_limit: Optional[int] = 300,
    ) -> List[Dict[str, Any]]:
        def _get() -> List[Dict[str, Any]]:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = (
                    "SELECT id, mode, scope, title, content, timestamp, importance, period_id, source "
                    "FROM mode_memories WHERE umo = ? ORDER BY importance DESC, id DESC"
                )
                params: List[Any] = [umo]
                if source_limit is not None:
                    query += " LIMIT ?"
                    params.append(max(1, self._safe_int(source_limit, 300)))
                cursor.execute(query, tuple(params))
                return [self._row_to_memory(row) for row in cursor.fetchall()]

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            self.logger.error(f"Failed to fetch compaction source memories: {exc}")
            return []

    async def _replace_umo_memories(
        self,
        umo: str,
        fallback_mode: str,
        items: List[Dict[str, Any]],
    ) -> int:
        safe_mode = fallback_mode if fallback_mode in {"work", "rest"} else "work"

        def _replace() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM mode_memories WHERE umo = ?", (umo,))
                for item in items:
                    scope = self._normalize_scope(str(item.get("scope", SCOPE_MODE)))
                    mode = str(item.get("mode", safe_mode)).strip().lower()
                    if mode not in {"work", "rest"}:
                        mode = safe_mode
                    title = str(item.get("title", "")).strip()
                    content = str(item.get("content", "")).strip()
                    importance = self._normalize_importance(item.get("importance", 5))
                    period_id = max(0, self._safe_int(item.get("period_id"), 0))
                    source = str(item.get("source", "autodream")).strip() or "autodream"
                    if not title or not content:
                        continue

                    cursor.execute(
                        (
                            "INSERT INTO mode_memories "
                            "(umo, mode, title, content, importance, scope, period_id, source) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                        ),
                        (umo, mode, title, content, importance, scope, period_id, source),
                    )

                conn.commit()
                cursor.execute("SELECT COUNT(*) FROM mode_memories WHERE umo = ?", (umo,))
                row = cursor.fetchone()
                return int(row[0]) if row else 0

        try:
            return await asyncio.to_thread(_replace)
        except Exception as exc:
            self.logger.error(f"Failed to replace memories after autodream: {exc}")
            return -1

    @staticmethod
    def _strip_markdown_code_fence(text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        return cleaned.strip()

    @staticmethod
    def _extract_text(value: Any) -> str:
        if isinstance(value, str):
            return value

        if isinstance(value, list):
            parts: List[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
                        continue
                    content = item.get("content")
                    if isinstance(content, str):
                        parts.append(content)
            return " ".join(parts)

        if isinstance(value, dict):
            for key in ("text", "content", "message"):
                candidate = value.get(key)
                if isinstance(candidate, str):
                    return candidate

        return ""

    @staticmethod
    def _normalize_text_fragment(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        cleaned = (text or "").strip()
        if max_chars <= 0 or len(cleaned) <= max_chars:
            return cleaned
        if max_chars <= 3:
            return cleaned[:max_chars]
        return cleaned[: max_chars - 3].rstrip() + "..."

    @staticmethod
    def _build_history_text(
        history_contexts: List[Dict[str, Any]],
        history_limit: Optional[int] = 40,
        message_char_limit: int = 220,
        total_char_limit: int = 4800,
    ) -> str:
        if history_limit is None:
            source = history_contexts
        else:
            safe_limit = max(1, int(history_limit))
            source = history_contexts[-safe_limit:]

        safe_message_chars = max(40, int(message_char_limit))
        safe_total_chars = max(400, int(total_char_limit))

        parts: List[str] = []
        total_chars = 0
        for msg in source:
            role = str(msg.get("role", "unknown")).strip().lower()
            if role not in {"system", "user", "assistant"}:
                continue

            raw_content = msg.get("content", "")
            content = MemoryManager._extract_text(raw_content)
            content = MemoryManager._normalize_text_fragment(content)
            if not content:
                continue
            content = MemoryManager._truncate_text(content, safe_message_chars)

            line = f"{role}: {content}"
            projected = total_chars + len(line) + 1
            if projected > safe_total_chars:
                remaining = safe_total_chars - total_chars
                if remaining < 20:
                    break
                parts.append(MemoryManager._truncate_text(line, remaining))
                break

            parts.append(line)
            total_chars = projected

        return "\n".join(parts)

    @staticmethod
    def _parse_memory_items(raw_json: str) -> List[Dict[str, Any]]:
        parsed = json.loads(raw_json)
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            memories = parsed.get("memories", [])
            if isinstance(memories, list):
                return [item for item in memories if isinstance(item, dict)]
        return []

    async def _memory_exists(self, umo: str, mode: str, scope: str, title: str, content: str) -> bool:
        normalized_scope = self._normalize_scope(scope)

        def _exists() -> bool:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                if normalized_scope == SCOPE_GLOBAL:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM mode_memories
                        WHERE umo = ?
                          AND scope = ?
                          AND title = ?
                          AND content = ?
                        LIMIT 1
                        """,
                        (umo, normalized_scope, title, content),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT 1
                        FROM mode_memories
                        WHERE umo = ?
                          AND mode = ?
                          AND scope = ?
                          AND title = ?
                          AND content = ?
                        LIMIT 1
                        """,
                        (umo, mode, normalized_scope, title, content),
                    )
                return cursor.fetchone() is not None

        return await asyncio.to_thread(_exists)

    def _reclassify_scope(self, suggested_scope: str, title: str, content: str) -> str:
        scope = self._normalize_scope(suggested_scope)
        text = f"{title} {content}".lower()

        global_keywords = (
            "always",
            "长期",
            "长期偏好",
            "习惯",
            "人设",
            "身份",
            "生日",
            "姓名",
            "偏好",
            "禁忌",
            "原则",
            "长期",
            "总是",
            "永远",
        )
        mode_keywords = (
            "工作模式",
            "休息模式",
            "work mode",
            "rest mode",
            "项目",
            "流程",
            "规则",
            "风格",
            "工作中",
            "休息时",
        )
        session_keywords = (
            "今天",
            "这次",
            "刚刚",
            "当前",
            "本轮",
            "临时",
            "稍后",
            "待办",
            "this round",
            "today",
            "temporary",
            "current task",
        )

        has_global = any(k in text for k in global_keywords)
        has_mode = any(k in text for k in mode_keywords)
        has_session = any(k in text for k in session_keywords)

        if has_global and not has_session:
            return SCOPE_GLOBAL
        if has_mode and not has_global and scope == SCOPE_SESSION:
            return SCOPE_MODE
        if has_session and not has_global and not has_mode:
            return SCOPE_SESSION

        if scope == SCOPE_GLOBAL and has_session and not has_global:
            return SCOPE_MODE
        return scope

    async def trigger_summary_and_save(
        self,
        context: Any,
        umo: str,
        mode: str,
        history_contexts: List[Dict[str, Any]],
        history_limit: Optional[int] = 40,
        message_char_limit: int = 220,
        total_char_limit: int = 4800,
        period_id: int = 0,
        source: str = "summary",
    ) -> Dict[str, Any]:
        if not history_contexts:
            return {"status": "empty_history", "added": 0, "parsed": 0}

        try:
            provider_id = await context.get_current_chat_provider_id(umo)
            if not provider_id:
                self.logger.warning(f"[Memory] No provider for {umo}")
                return {"status": "no_provider", "added": 0, "parsed": 0}

            system_prompt = (
                "你是记忆提取器。仅提取可复用事实，忽略寒暄、重复和一次性细节。\n"
                "必须输出 JSON 数组，元素字段为 scope/title/content/importance。\n"
                "scope 只能是 global/mode/session，分类标准如下：\n"
                "- global: 跨模式长期稳定事实，如用户长期偏好、身份、禁忌。\n"
                "- mode: 仅在当前工作或休息模式长期有用的规则与上下文。\n"
                "- session: 仅当前阶段短期有用、后续可能失效的信息。\n"
                "importance 为 1-10 整数，只输出 JSON，不要解释。\n"
                "元素格式：{\"scope\":\"global|mode|session\",\"title\":\"...\",\"content\":\"...\",\"importance\":8}"
            )

            history_text = self._build_history_text(
                history_contexts,
                history_limit,
                message_char_limit,
                total_char_limit,
            )
            if not history_text or len(history_text) < 20:
                return {"status": "history_too_short", "added": 0, "parsed": 0}

            response = await context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=(
                    "请提取三层记忆为 JSON。请尽量区分长期(global)、模式长期(mode)、短期(session)：\n"
                    + history_text
                ),
            )

            text_result = self._strip_markdown_code_fence(getattr(response, "completion_text", ""))
            items = self._parse_memory_items(text_result)
            if not items:
                return {"status": "no_output", "added": 0, "parsed": 0}

            parsed = 0
            added = 0
            skipped_exists = 0
            skipped_invalid = 0

            for item in items:
                title = str(item.get("title", "")).strip()
                content = str(item.get("content", "")).strip()
                raw_scope = str(item.get("scope", SCOPE_MODE))
                scope = self._normalize_scope(raw_scope)
                scope = self._reclassify_scope(scope, title, content)
                importance = self._normalize_importance(item.get("importance", 5))

                if not title or not content:
                    skipped_invalid += 1
                    continue
                if title.lower() == "none" or content.lower() == "none":
                    skipped_invalid += 1
                    continue

                parsed += 1
                exists = await self._memory_exists(umo, mode, scope, title, content)
                if exists:
                    skipped_exists += 1
                    continue

                mem_id = await self.add_memory(
                    umo=umo,
                    mode=mode,
                    title=title,
                    content=content,
                    importance=importance,
                    scope=scope,
                    period_id=period_id,
                    source=source,
                )
                if mem_id > 0:
                    added += 1
                    self.logger.info(
                        f"[Memory] Added scope={scope} id={mem_id} importance={importance} mode={mode} period={period_id} title={title}"
                    )

            return {
                "status": "ok" if added > 0 else "no_new",
                "added": added,
                "parsed": parsed,
                "skipped_exists": skipped_exists,
                "skipped_invalid": skipped_invalid,
                "period_id": max(0, self._safe_int(period_id, 0)),
                "source": source,
            }
        except json.JSONDecodeError:
            self.logger.warning("[Memory] LLM summary output is not valid JSON")
            return {"status": "bad_json", "added": 0, "parsed": 0}
        except Exception:
            self.logger.exception(f"[Memory] Error during summary for mode={mode}")
            return {"status": "error", "added": 0, "parsed": 0}

    async def autodream_compact(
        self,
        context: Any,
        umo: str,
        mode: str,
        retain_count: int = 60,
        source_limit: Optional[int] = 180,
    ) -> Dict[str, Any]:
        before_total = await self.get_memory_total(umo)
        if before_total <= 0:
            return {"status": "empty", "before": 0, "after": 0}

        source = await self._get_compaction_source_memories(umo, source_limit)
        if not source:
            return {"status": "no_source", "before": before_total, "after": before_total}

        try:
            provider_id = await context.get_current_chat_provider_id(umo)
            if not provider_id:
                self.logger.warning(f"[AutoDream] No provider for {umo}")
                return {"status": "no_provider", "before": before_total, "after": before_total}

            safe_retain = max(5, int(retain_count))
            lines: List[str] = []
            for item in source:
                title = self._truncate_text(
                    self._normalize_text_fragment(str(item.get("title", ""))),
                    48,
                )
                content = self._truncate_text(
                    self._normalize_text_fragment(str(item.get("content", ""))),
                    180,
                )
                if not title or not content:
                    continue
                lines.append(
                    (
                        f"[id={item.get('id')}|mode={item.get('mode')}|scope={item.get('scope')}"
                        f"|importance={item.get('importance')}|period={item.get('period_id')}] "
                        f"{title}: {content}"
                    )
                )

            if not lines:
                return {"status": "no_source", "before": before_total, "after": before_total}

            system_prompt = (
                "你是记忆压缩器。目标：合并重复、删除噪声、保留关键长期信息。\n"
                "输出必须是 JSON 数组，且最多保留指定条数。\n"
                "每个元素格式：{\"scope\":\"global|mode|session\",\"mode\":\"work|rest\",\"title\":\"...\",\"content\":\"...\",\"importance\":8}\n"
                "importance 范围 1-10，只输出 JSON。"
            )

            response = await context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=(
                    f"当前记忆总量: {before_total}\n"
                    f"目标保留条数上限: {safe_retain}\n"
                    f"当前模式提示: {mode}\n"
                    "请重整以下记忆：\n"
                    + "\n".join(lines)
                ),
            )

            text_result = self._strip_markdown_code_fence(getattr(response, "completion_text", ""))
            raw_items = self._parse_memory_items(text_result)
            if not raw_items:
                return {"status": "no_output", "before": before_total, "after": before_total}

            safe_mode = mode if mode in {"work", "rest"} else "work"
            dedup = set()
            compacted: List[Dict[str, Any]] = []
            for item in raw_items:
                title = str(item.get("title", "")).strip()
                content = str(item.get("content", "")).strip()
                if not title or not content:
                    continue
                if title.lower() == "none" or content.lower() == "none":
                    continue

                scope = self._normalize_scope(str(item.get("scope", SCOPE_MODE)))
                item_mode = str(item.get("mode", safe_mode)).strip().lower()
                if item_mode not in {"work", "rest"}:
                    item_mode = safe_mode
                importance = self._normalize_importance(item.get("importance", 5))

                key = (scope, item_mode, title, content)
                if key in dedup:
                    continue
                dedup.add(key)

                compacted.append(
                    {
                        "scope": scope,
                        "mode": item_mode,
                        "title": title,
                        "content": content,
                        "importance": importance,
                        "source": "autodream",
                    }
                )
                if len(compacted) >= safe_retain:
                    break

            if not compacted:
                return {"status": "no_output", "before": before_total, "after": before_total}

            after_total = await self._replace_umo_memories(umo, safe_mode, compacted)
            if after_total < 0:
                return {"status": "replace_failed", "before": before_total, "after": before_total}

            return {
                "status": "ok",
                "before": before_total,
                "after": after_total,
                "retained": len(compacted),
            }
        except json.JSONDecodeError:
            self.logger.warning("[AutoDream] LLM output is not valid JSON")
            return {"status": "bad_json", "before": before_total, "after": before_total}
        except Exception:
            self.logger.exception(f"[AutoDream] Error during compaction for umo={umo}")
            return {"status": "error", "before": before_total, "after": before_total}

    async def run_compaction_if_needed(
        self,
        context: Any,
        umo: str,
        mode: str,
        enabled: bool,
        total_threshold: int,
        retain_count: int,
        source_limit: int,
    ) -> Dict[str, Any]:
        if not enabled:
            return {"status": "disabled"}

        total = await self.get_memory_total(umo)
        if total < max(1, self._safe_int(total_threshold, 1)):
            return {
                "status": "below_threshold",
                "before": total,
                "after": total,
                "threshold": max(1, self._safe_int(total_threshold, 1)),
            }

        return await self.autodream_compact(
            context=context,
            umo=umo,
            mode=mode,
            retain_count=max(5, self._safe_int(retain_count, 60)),
            source_limit=max(20, self._safe_int(source_limit, 180)),
        )

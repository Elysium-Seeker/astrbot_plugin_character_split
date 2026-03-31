import asyncio
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

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
                        scope TEXT DEFAULT 'mode'
                    )
                    """
                )
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_umo_mode ON mode_memories (umo, mode)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_umo_scope ON mode_memories (umo, scope)")
                cursor.execute(
                    "CREATE INDEX IF NOT EXISTS idx_umo_mode_scope ON mode_memories (umo, mode, scope)"
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
                conn.commit()
        except Exception as exc:
            self.logger.error(f"Failed to initialize memory DB: {exc}")

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
    def _row_to_memory(row: Any) -> Dict[str, Any]:
        return {
            "id": row[0],
            "title": row[1],
            "content": row[2],
            "timestamp": row[3],
            "importance": row[4],
            "scope": row[5],
        }

    async def add_memory(
        self,
        umo: str,
        mode: str,
        title: str,
        content: str,
        importance: int = 5,
        scope: str = SCOPE_MODE,
    ) -> int:
        def _add() -> int:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO mode_memories (umo, mode, title, content, importance, scope) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        umo,
                        mode,
                        title.strip(),
                        content.strip(),
                        self._normalize_importance(importance),
                        self._normalize_scope(scope),
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
    ) -> Dict[str, List[Dict[str, Any]]]:
        def _get() -> Dict[str, List[Dict[str, Any]]]:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                layers: Dict[str, List[Dict[str, Any]]] = {
                    SCOPE_GLOBAL: [],
                    SCOPE_MODE: [],
                    SCOPE_SESSION: [],
                }

                cursor.execute(
                    """
                    SELECT id, title, content, timestamp, importance, scope
                    FROM mode_memories
                    WHERE umo = ? AND scope = ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (umo, SCOPE_GLOBAL, max(1, int(global_limit))),
                )
                layers[SCOPE_GLOBAL] = [self._row_to_memory(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT id, title, content, timestamp, importance, scope
                    FROM mode_memories
                    WHERE umo = ? AND mode = ? AND scope = ?
                    ORDER BY importance DESC, id DESC
                    LIMIT ?
                    """,
                    (umo, mode, SCOPE_MODE, max(1, int(mode_limit))),
                )
                layers[SCOPE_MODE] = [self._row_to_memory(row) for row in cursor.fetchall()]

                cursor.execute(
                    """
                    SELECT id, title, content, timestamp, importance, scope
                    FROM mode_memories
                    WHERE umo = ? AND mode = ? AND scope = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (umo, mode, SCOPE_SESSION, max(1, int(session_limit))),
                )
                session_rows = cursor.fetchall()
                session_rows.sort(key=lambda row: row[0])
                layers[SCOPE_SESSION] = [self._row_to_memory(row) for row in session_rows]

                return layers

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            self.logger.error(f"Failed to get layered memories: {exc}")
            return {SCOPE_GLOBAL: [], SCOPE_MODE: [], SCOPE_SESSION: []}

    async def get_recent_memories(
        self,
        umo: str,
        mode: str,
        limit: int = 5,
        strategy: str = "recent",
    ) -> List[Dict[str, Any]]:
        """Compatibility method for old call-sites.

        Returns a flattened list of memories related to current mode:
        global + mode + session, sorted by id descending by default.
        """

        def _get() -> List[Dict[str, Any]]:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                query = (
                    """
                    SELECT id, title, content, timestamp, importance, scope
                    FROM mode_memories
                    WHERE umo = ?
                      AND (
                        scope = ?
                        OR (scope = ? AND mode = ?)
                        OR (scope = ? AND mode = ?)
                      )
                    """
                )

                if strategy == "importance":
                    query += " ORDER BY importance DESC, id DESC LIMIT ?"
                else:
                    query += " ORDER BY id DESC LIMIT ?"

                cursor.execute(
                    query,
                    (
                        umo,
                        SCOPE_GLOBAL,
                        SCOPE_MODE,
                        mode,
                        SCOPE_SESSION,
                        mode,
                        max(1, int(limit)),
                    ),
                )
                return [self._row_to_memory(row) for row in cursor.fetchall()]

        try:
            return await asyncio.to_thread(_get)
        except Exception as exc:
            self.logger.error(f"Failed to get recent memories: {exc}")
            return []

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
    def _build_history_text(
        history_contexts: List[Dict[str, Any]],
        history_limit: Optional[int] = 40,
    ) -> str:
        if history_limit is None:
            source = history_contexts
        else:
            safe_limit = max(1, int(history_limit))
            source = history_contexts[-safe_limit:]

        parts: List[str] = []
        for msg in source:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, str) and content.strip():
                parts.append(f"{role}: {content}")
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
        def _exists() -> bool:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
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
                    (umo, mode, scope, title, content),
                )
                return cursor.fetchone() is not None

        return await asyncio.to_thread(_exists)

    async def trigger_summary_and_save(
        self,
        context: Any,
        umo: str,
        mode: str,
        history_contexts: List[Dict[str, Any]],
        history_limit: Optional[int] = 40,
    ):
        if not history_contexts:
            return

        try:
            provider_id = await context.get_current_chat_provider_id(umo)
            if not provider_id:
                self.logger.warning(f"[Memory] No provider for {umo}")
                return

            system_prompt = (
                "你是一个三层记忆管理器。请从对话里提取有价值事实并按 scope 分类。\n"
                "scope 可选值：global/mode/session。\n"
                "global: 通用偏好或长期身份特征，importance 建议 8-10。\n"
                "mode: 工作或休息模式下的长期规则，importance 建议 5-8。\n"
                "session: 当前任务的短期上下文，importance 建议 1-5。\n"
                "仅输出 JSON 数组，不要任何多余文本。\n"
                "数组元素格式：{\"scope\":\"global\",\"title\":\"...\",\"content\":\"...\",\"importance\":8}"
            )

            history_text = self._build_history_text(history_contexts, history_limit)
            if not history_text:
                return
            response = await context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=f"请提取三层记忆为 JSON：\n{history_text}",
            )

            text_result = self._strip_markdown_code_fence(getattr(response, "completion_text", ""))
            items = self._parse_memory_items(text_result)
            if not items:
                return

            for item in items:
                title = str(item.get("title", "")).strip()
                content = str(item.get("content", "")).strip()
                scope = self._normalize_scope(str(item.get("scope", SCOPE_MODE)))
                importance = self._normalize_importance(item.get("importance", 5))

                if not title or not content:
                    continue
                if title.lower() == "none" or content.lower() == "none":
                    continue

                exists = await self._memory_exists(umo, mode, scope, title, content)
                if exists:
                    continue

                mem_id = await self.add_memory(
                    umo=umo,
                    mode=mode,
                    title=title,
                    content=content,
                    importance=importance,
                    scope=scope,
                )
                self.logger.info(
                    f"[Memory] Added scope={scope} id={mem_id} importance={importance} mode={mode} title={title}"
                )
        except json.JSONDecodeError:
            self.logger.warning("[Memory] LLM summary output is not valid JSON")
        except Exception:
            self.logger.exception(f"[Memory] Error during summary for mode={mode}")

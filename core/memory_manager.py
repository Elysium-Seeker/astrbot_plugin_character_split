import sqlite3
import os
import asyncio
import json
from typing import List, Dict, Any, Optional

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
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS mode_memories (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        umo TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        title TEXT NOT NULL,
                        content TEXT NOT NULL,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_umo_mode ON mode_memories (umo, mode)')
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to initialize memory DB: {e}")

    async def add_memory(self, umo: str, mode: str, title: str, content: str) -> int:
        def _add():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO mode_memories (umo, mode, title, content) VALUES (?, ?, ?, ?)",
                    (umo, mode, title, content)
                )
                conn.commit()
                return cursor.lastrowid
        try:
            return await asyncio.to_thread(_add)
        except Exception as e:
            self.logger.error(f"Failed to add memory: {e}")
            return -1

    async def get_recent_memories(self, umo: str, mode: str, limit: int = 5) -> List[Dict[str, Any]]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT id, title, content, timestamp FROM mode_memories WHERE umo = ? AND mode = ? ORDER BY id DESC LIMIT ?",
                    (umo, mode, limit)
                )
                return [{"id": r[0], "title": r[1], "content": r[2], "timestamp": r[3]} for r in cursor.fetchall()]
        try:
            items = await asyncio.to_thread(_get)
            return sorted(items, key=lambda x: x["id"])
        except Exception as e:
            self.logger.error(f"Failed to get memory: {e}")
            return []

    async def remove_memory(self, umo: str, mem_id: int) -> bool:
        def _remove():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM mode_memories WHERE umo = ? AND id = ?", (umo, mem_id))
                conn.commit()
                return cursor.rowcount > 0
        try:
            return await asyncio.to_thread(_remove)
        except Exception as e:
            self.logger.error(f"Failed to remove memory: {e}")
            return False

    async def trigger_summary_and_save(self, context: Any, umo: str, mode: str, history_contexts: List[Dict[str, Any]]):
        if not history_contexts or len(history_contexts) < 2:
            return
        try:
            provider_id = await context.get_current_chat_provider_id(umo)
            if not provider_id:
                self.logger.warning(f"[Memory] No provider for {umo}")
                return

            self.logger.info(f"[Memory] Triggering background summary for mode {mode} (UMO: {umo})")

            system_prompt = (
                "你是一个极其精简且客观的长期记忆提取助手。\n"
                "请分析如下这轮对话历史，提取出对未来有用的长效事实记忆（如：用户的习惯、重要设定、关键约定）。\n"
                "如果对话中全是闲聊或寒暄，没有任何值得长期记录的设定，请务必返回：[{\"title\": \"none\", \"content\": \"none\"}]\n"
                "否则，返回纯JSON数组：\n"
                "[\n"
                "  {\"title\": \"主题或标签\", \"content\": \"具体细节\"}\n"
                "]\n"
                "不要包含任何其他说明文字。"
            )

            history_text = ""
            for msg in history_contexts[-40:]:
                role = msg.get("role", "unknown")
                msg_content = msg.get("content", "")
                if isinstance(msg_content, str):
                    history_text += f"{role}: {msg_content}\n"

            resp = await context.llm_generate(
                chat_provider_id=provider_id,
                system_prompt=system_prompt,
                prompt=f"请总结以下厇史：\n{history_text}"
            )

            text_result = resp.completion_text.strip()
            if text_result.startswith("```json"):
                text_result = text_result[7:]
            if text_result.startswith("```"):
                text_result = text_result[3:]
            if text_result.endswith("```"):
                text_result = text_result[:-3]
            text_result = text_result.strip()

            data = json.loads(text_result)
            for item in data:
                title = item.get("title", "").strip()
                content = item.get("content", "").strip()
                if title and content and title.lower() != "none" and content.lower() != "none":
                    mem_id = await self.add_memory(umo, mode, title, content)
                    self.logger.info(f"[Memory] Extracted and saved memory {mem_id} for mode {mode}: {title}")

        except json.JSONDecodeError:
            self.logger.warning(f"[Memory] Failed to parse JSON from LLM: {getattr(resp, 'completion_text', 'No response')}")
        except Exception as e:
            self.logger.exception(f"[Memory] Error during summary for mode {mode}")
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
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                        importance INTEGER DEFAULT 5
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_umo_mode ON mode_memories (umo, mode)')
                # Migration for existing DB
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN importance INTEGER DEFAULT 5")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to initialize memory DB: {e}")

    async def add_memory(self, umo: str, mode: str, title: str, content: str, importance: int = 5) -> int:
        def _add():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO mode_memories (umo, mode, title, content, importance) VALUES (?, ?, ?, ?, ?)",
                    (umo, mode, title, content, importance)
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
                    "SELECT id, title, content, timestamp, importance FROM mode_memories WHERE umo = ? AND mode = ? ORDER BY importance DESC, id DESC LIMIT ?",
                    (umo, mode, limit)
                )
                return [{"id": r[0], "title": r[1], "content": r[2], "timestamp": r[3], "importance": r[4]} for r in cursor.fetchall()]
        try:
            items = await asyncio.to_thread(_get)
            return items # Already sorted by SQL DESC
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
                "你是一个极其精简且客观的长期事实记忆提取助手。\n"
                "请分析如下这轮对话历史，提取出对未来有用的长效核心记忆（如：用户的习惯、身份设定、关键约束）。\n"
                "并为每条记忆打分（importance: 1-10，10为最重要，如用户的名字/人设级要求设为8-10，普通偏好设为1-5）。\n"
                "如果对话中全是没有记忆价值的废话闲聊，请务必返回：[{\"title\": \"none\", \"content\": \"none\", \"importance\": 0}]\n"
                "否则，返回纯JSON数组：\n"
                "[\n"
                "  {\"title\": \"主题或标签\", \"content\": \"具体细节\", \"importance\": 8}\n"
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
                prompt=f"请提取记忆至JSON：\n{history_text}"
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
                importance = int(item.get("importance", 5))
                if title and content and title.lower() != "none" and content.lower() != "none":
                    mem_id = await self.add_memory(umo, mode, title, content, importance)
                    self.logger.info(f"[Memory] Extracted and saved memory {mem_id} (imp:{importance}) for mode {mode}: {title}")
                    
        except json.JSONDecodeError:
            self.logger.warning(f"[Memory] Failed to parse JSON from LLM: {getattr(resp, 'completion_text', 'No response')}")
        except Exception as e:
            self.logger.exception(f"[Memory] Error during summary for mode {mode}")

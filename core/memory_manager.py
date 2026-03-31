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
                        importance INTEGER DEFAULT 5,
                        scope TEXT DEFAULT 'mode'
                    )
                ''')
                cursor.execute('CREATE INDEX IF NOT EXISTS idx_umo_mode ON mode_memories (umo, mode)')
                # Migrations
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN importance INTEGER DEFAULT 5")
                except sqlite3.OperationalError:
                    pass
                try:
                    cursor.execute("ALTER TABLE mode_memories ADD COLUMN scope TEXT DEFAULT 'mode'")
                except sqlite3.OperationalError:
                    pass
                conn.commit()
        except Exception as e:
            self.logger.error(f"Failed to initialize memory DB: {e}")

    async def add_memory(self, umo: str, mode: str, title: str, content: str, importance: int = 5, scope: str = "mode") -> int:
        def _add():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO mode_memories (umo, mode, title, content, importance, scope) VALUES (?, ?, ?, ?, ?, ?)",
                    (umo, mode, title, content, importance, scope)
                )
                conn.commit()
                return cursor.lastrowid
        try:
            return await asyncio.to_thread(_add)
        except Exception as e:
            self.logger.error(f"Failed to add memory: {e}")
            return -1

    async def get_layered_memories(self, umo: str, mode: str) -> Dict[str, List[Dict[str, Any]]]:
        def _get():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                layers = {"global": [], "mode": [], "session": []}
                
                # Layer 1: global
                cursor.execute("SELECT id, title, content, timestamp, importance, scope FROM mode_memories WHERE umo=? AND scope='global' ORDER BY importance DESC, id DESC LIMIT 5", (umo,))
                layers["global"] = [{"id": r[0], "title": r[1], "content": r[2], "timestamp": r[3], "importance": r[4], "scope": r[5]} for r in cursor.fetchall()]
                
                # Layer 2: mode
                cursor.execute("SELECT id, title, content, timestamp, importance, scope FROM mode_memories WHERE umo=? AND scope='mode' AND mode=? ORDER BY importance DESC, id DESC LIMIT 5", (umo, mode))
                layers["mode"] = [{"id": r[0], "title": r[1], "content": r[2], "timestamp": r[3], "importance": r[4], "scope": r[5]} for r in cursor.fetchall()]
                
                # Layer 3: session (limit 5 recent)
                cursor.execute("SELECT id, title, content, timestamp, importance, scope FROM mode_memories WHERE umo=? AND scope='session' AND mode=? ORDER BY id DESC LIMIT 5", (umo, mode))
                s_rows = cursor.fetchall()
                s_rows.sort(key=lambda x: x[0]) # keep chronological
                layers["session"] = [{"id": r[0], "title": r[1], "content": r[2], "timestamp": r[3], "importance": r[4], "scope": r[5]} for r in s_rows]
                
                return layers
        try:
            return await asyncio.to_thread(_get)
        except Exception as e:
            self.logger.error(f"Failed to get layered memory: {e}")
            return {"global": [], "mode": [], "session": []}

    async def remove_memory(self, umo: str, mem_id: int) -> bool:
        def _remove():
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # removal spans across all scopes
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
                "你是一个极其敏锐的【三层架构】记忆管理者。\n"
                "请分析如下的对话历史，并将其进行分类提取为三个层级的记忆状态：\n\n"
                "1. [scope: 'global']全局记忆 (Layer 1)：脱离当前场景也能通用的全局用户偏好、身份、习惯等长效设定（重要性 8-10分）。\n"
                "2. [scope: 'mode']模式记忆 (Layer 2)：当前特定模式（工作/休息）下的专属场景规则、约定、或长效业务背景（重要性 5-8分）。\n"
                "3. [scope: 'session']会话记忆 (Layer 3)：当前正在处理的具体任务、临时上下文或短期待办事项（重要性 1-5分）。\n\n"
                "请严格以纯JSON数组格式返回（不要包含多余说明，若某一分类完全没有价值内容则直接跳过，全废话则返回空数组 []）：\n"
                "[\n"
                "  {\"scope\": \"global\", \"title\": \"代码偏好\", \"content\": \"要求不废话直接给代码\", \"importance\": 9},\n"
                "  {\"scope\": \"mode\", \"title\": \"工作指令\", \"content\": \"严格遵照PEP8标准\", \"importance\": 7},\n"
                "  {\"scope\": \"session\", \"title\": \"正在处理\", \"content\": \"正在升级三层级数据库架构\", \"importance\": 4}\n"
                "]"
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
                prompt=f"请提取三层记忆至JSON：\n{history_text}"
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
                scope = item.get("scope", "mode").strip().lower()
                if scope not in ("global", "mode", "session"):
                    scope = "mode"
                    
                if title and content and title.lower() != "none" and content.lower() != "none":
                    mem_id = await self.add_memory(umo, mode, title, content, importance, scope)
                    self.logger.info(f"[Memory] Extracted L-{scope} memory {mem_id} (imp:{importance}) for mode {mode}: {title}")
                    
        except json.JSONDecodeError:
            self.logger.warning(f"[Memory] Failed to parse JSON from LLM: {getattr(resp, 'completion_text', 'No response')}")
        except Exception as e:
            self.logger.exception(f"[Memory] Error during summary for mode {mode}")

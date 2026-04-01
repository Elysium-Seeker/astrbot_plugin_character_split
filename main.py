# pyright: reportMissingImports=false

import asyncio
from typing import Any, Dict, Optional, Tuple

try:
    from .core import (
        ConversationSplitter,
        MODE_SET,
        PLUGIN_NAME,
        STATE_KV_KEY,
        ModeResolver,
        PersonaPromptBuilder,
        SplitConfig,
        StateStore,
    )
    from .core.memory_manager import MemoryManager
except ImportError:  # pragma: no cover
    from core import (  # type: ignore
        ConversationSplitter,
        MODE_SET,
        PLUGIN_NAME,
        STATE_KV_KEY,
        ModeResolver,
        PersonaPromptBuilder,
        SplitConfig,
        StateStore,
    )
    from core.memory_manager import MemoryManager  # type: ignore

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.star import StarTools

@register("character_split", "Elysium-Seeker", "Split work/rest dialog and manage auto-memory", "1.2.1")
class CharacterSplitPlugin(Star):
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}

        self._split_config = SplitConfig(self.config)
        self._state_store = self._create_state_store()
        self._mode_resolver = ModeResolver(self._split_config, self._state_store)
        self._persona_builder = PersonaPromptBuilder(self._split_config)
        self._conversation_splitter = ConversationSplitter(self._state_store, logger)
        
        # 内置独立记忆系统
        self._memory_manager = MemoryManager(StarTools.get_data_dir(), logger)
        
        self._runtime_state_lock = asyncio.Lock()
        self._mode_dirty_runtime: Dict[str, Dict[str, bool]] = {}

    async def initialize(self):
        await self._state_store.ensure_state()

    async def terminate(self):
        await self._state_store.save_state()

    @filter.command_group(
        "mode",
        desc="工作/休息模式控制台",
    )
    def mode(self):
        """Mode command group"""

    @mode.command("help", desc="查看 mode 指令帮助面板")
    async def mode_help(self, event: AstrMessageEvent):
        """Show mode command help"""
        yield event.plain_result(self._help_text())

    @mode.command("status", desc="查询当前生效模式及触发来源")
    async def mode_status(self, event: AstrMessageEvent):
        """Show current mode status"""
        session_id, umo = self._get_session_identifiers(event)
        mode, source = await self._mode_resolver.resolve_mode(session_id, umo)

        layers = await self._memory_manager.get_layered_memories(umo, mode)
        mem_count = sum(len(items) for items in layers.values())

        text = (
            f"mode: {mode} ({source})\n"
            f"local_time: {self._split_config.current_time_desc()}\n"
            f"session_id: {session_id or '-'}\n"
            f"umo: {umo or '-'}\n"
            f"memories_attached: {mem_count}"
        )
        yield event.plain_result(text)

    @mode.command("work", desc="锁定当前会话为工作模式")
    async def mode_work(self, event: AstrMessageEvent):
        """Force work mode for current session"""
        msg = await self._set_mode_override(event, "work")
        yield event.plain_result(msg)

    @mode.command("rest", desc="锁定当前会话为休息模式")
    async def mode_rest(self, event: AstrMessageEvent):
        """Force rest mode for current session"""
        msg = await self._set_mode_override(event, "rest")
        yield event.plain_result(msg)

    @mode.command("auto", desc="解除强制锁定，恢复时间规则自动调度")
    async def mode_auto(self, event: AstrMessageEvent):
        """Reset to auto mode resolution"""
        msg = await self._set_mode_override(event, "auto")
        yield event.plain_result(msg)

    @mode.command("set", desc="兼容旧版：参数填 work/rest/auto 快速锁定模式")
    async def mode_set(self, event: AstrMessageEvent, target: str = ""):
        """Compatibility command for /mode set work|rest|auto"""
        target = (target or "").strip().lower()
        if target not in MODE_SET and target != "auto":
            yield event.plain_result("Usage: /mode set work|rest|auto")
            return

        msg = await self._set_mode_override(event, target)
        yield event.plain_result(msg)

    @filter.command_group("csmem", desc="独立多角色记忆管理系统")
    def csmem(self):
        """Memory management group"""

    @csmem.command("list", desc="按三层结构列出当前可用记忆")
    async def mem_list(self, event: AstrMessageEvent):
        """List current memories grouped by memory layer"""
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

        layers = await self._memory_manager.get_layered_memories(
            umo,
            mode,
            global_limit=10,
            mode_limit=10,
            session_limit=10,
        )
        total = sum(len(items) for items in layers.values())

        if total == 0:
            yield event.plain_result(f"当前模式 [{mode}] 暂无可用记忆。")
            return

        scope_names = {
            "global": "Layer1-全局",
            "mode": f"Layer2-{mode}",
            "session": "Layer3-会话",
        }
        output = [f"[{mode}] 三层记忆总数: {total}"]
        for scope in ("global", "mode", "session"):
            items = layers.get(scope, [])
            output.append(f"\n[{scope_names[scope]}] ({len(items)})")
            if not items:
                output.append("- (空)")
                continue
            for m in items:
                imp = m.get("importance", 5)
                output.append(f"- #{m['id']} [⭐{imp}] {m['title']}: {m['content']}")

        yield event.plain_result("\n".join(output))

    @csmem.command("rm", desc="删除指定ID的记忆事实")
    async def mem_rm(self, event: AstrMessageEvent, mem_id: int):
        """Remove a specific memory by ID"""
        session_id, umo = self._get_session_identifiers(event)
        success = await self._memory_manager.remove_memory(umo, int(mem_id))
        if success:
            yield event.plain_result(f"已删除记录 #{mem_id}")
        else:
            yield event.plain_result(f"删除失败：未找到从属于你的记录 #{mem_id}")
    @csmem.command("sync", desc="对当前会话历史立即进行记忆总结与提取")
    async def mem_sync(self, event: AstrMessageEvent):
        """Force run background memory summarization for current conversation"""
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

        conv_mgr = await self._get_conversation_manager()
        history = []
        if conv_mgr:
            try:
                import json
                cid = await self._conversation_splitter._call_conversation_method(
                    conv_mgr.get_curr_conversation_id, umo, timeout_seconds=4.0
                )
                if cid:
                    conv = await self._conversation_splitter._call_conversation_method(
                        conv_mgr.get_conversation, umo, cid, timeout_seconds=4.0
                    )
                    if conv and hasattr(conv, "history"):
                        history = json.loads(conv.history)
            except Exception as e:
                logger.warning(f"character_split failed to get history for sync: {e}")

        if not history or len(history) < 2:
            yield event.plain_result(f"当前模式 [{mode}] 对话历史过短，暂无需提取记忆。")
            return

        yield event.plain_result(f"⏳ 正在后台提取当前模式 [{mode}] 的三层记忆...")
        import asyncio
        summary_limits = self._get_summary_limits()
        asyncio.create_task(
            self._memory_manager.trigger_summary_and_save(
                self.context,
                umo,
                mode,
                history,
                history_limit=summary_limits["history_limit"],
                message_char_limit=summary_limits["message_char_limit"],
                total_char_limit=summary_limits["total_char_limit"],
            )
        )
    @filter.on_llm_request(
        priority=100,
        desc="拦截 LLM 请求前置钩子：根据时间和用户配置判定工作状况并剥离上下文及注入增量提示词",
    )
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            session_id, umo = self._get_session_identifiers(event)
            mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)
            
            # Switch conversation & optionally trigger Memory auto-extraction
            switched = await self._sync_mode_conversation(event, mode, umo)

            if switched:
                conv_mgr = await self._get_conversation_manager()
                if conv_mgr:
                    import json
                    try:
                        new_cid = await self._conversation_splitter._call_conversation_method(
                            conv_mgr.get_curr_conversation_id, umo, timeout_seconds=4.0
                        )
                        if new_cid:
                            new_conv = await self._conversation_splitter._call_conversation_method(
                                conv_mgr.get_conversation, umo, new_cid, timeout_seconds=4.0
                            )
                            if new_conv:
                                req.conversation = getattr(new_conv, "inner", new_conv)
                                if hasattr(req.conversation, "history"):
                                    req.contexts = json.loads(req.conversation.history)
                    except Exception as e:
                        logger.warning(f"character_split failed to sync req context: {e}")

            self._mark_mode_dirty(umo, mode)
            await self._inject_mode_prompt(req, mode, umo)
        except Exception:
            logger.exception("character_split on_llm_request failed")
            raise

    async def _sync_mode_conversation(self, event: AstrMessageEvent, mode: str, umo: str) -> bool:
        source_mode = await self._get_current_mode_from_conversation(umo)
        
        trigger_summary = False
        old_history = []
        if source_mode and source_mode != mode:
            skip_without_messages = self._split_config.get_bool("skip_checkpoint_without_messages", True)
            is_dirty = await self._is_mode_dirty(umo, source_mode)
            if not (skip_without_messages and not is_dirty):
                trigger_summary = True
                conv_mgr = await self._get_conversation_manager()
                if conv_mgr:
                    try:
                        import json
                        old_cid = await self._conversation_splitter._call_conversation_method(
                            conv_mgr.get_curr_conversation_id, umo, timeout_seconds=4.0
                        )
                        if old_cid:
                            old_conv = await self._conversation_splitter._call_conversation_method(
                                conv_mgr.get_conversation, umo, old_cid, timeout_seconds=4.0
                            )
                            if old_conv and hasattr(old_conv, "history"):
                                old_history = json.loads(old_conv.history)
                    except Exception as e:
                        logger.warning(f"character_split failed to get old history: {e}")

        switched = await self._conversation_splitter.ensure_mode_conversation(
            self.context,
            event,
            mode,
            pre_switch_hook=None,
        )
        
        if switched and trigger_summary and old_history and source_mode:
            import asyncio
            summary_limits = self._get_summary_limits()
            # background run summary
            asyncio.create_task(
                self._memory_manager.trigger_summary_and_save(
                    self.context,
                    umo,
                    source_mode,
                    old_history,
                    history_limit=summary_limits["history_limit"],
                    message_char_limit=summary_limits["message_char_limit"],
                    total_char_limit=summary_limits["total_char_limit"],
                )
            )
            await self._clear_mode_dirty(umo, source_mode)
            
        return switched

    async def _inject_mode_prompt(self, req: ProviderRequest, mode: str, umo: str):
        persona_limit = self._split_config.get_int("persona_prompt_char_limit", 480, 120, 3000)
        persona_prompt = self._truncate_text(self._persona_builder.build(mode), persona_limit)

        mem_str = ""
        if self._split_config.get_bool("inject_layered_memory", True):
            global_limit = self._split_config.get_int("prompt_global_memory_limit", 3, 0, 10)
            mode_limit = self._split_config.get_int("prompt_mode_memory_limit", 3, 0, 10)
            session_limit = self._split_config.get_int("prompt_session_memory_limit", 2, 0, 10)
            item_char_limit = self._split_config.get_int("prompt_memory_item_char_limit", 120, 40, 600)
            total_char_limit = self._split_config.get_int("prompt_memory_total_char_limit", 1200, 120, 8000)

            layers = await self._memory_manager.get_layered_memories(
                umo,
                mode,
                global_limit=global_limit,
                mode_limit=mode_limit,
                session_limit=session_limit,
            )

            mem_blocks = []
            mem_blocks.append(
                self._format_layer_block("Layer1 全局长期", layers.get("global", []), item_char_limit)
            )
            mem_blocks.append(
                self._format_layer_block(f"Layer2 {mode} 模式", layers.get("mode", []), item_char_limit)
            )
            mem_blocks.append(
                self._format_layer_block("Layer3 当前会话", layers.get("session", []), item_char_limit)
            )
            mem_str = "\n\n".join(block for block in mem_blocks if block)
            mem_str = self._truncate_text(mem_str, total_char_limit)

        old_prompt = getattr(req, "system_prompt", "") or ""
        mode_block = f"[Mode]\nCurrent mode: {mode}\n{persona_prompt}".strip()
        if mem_str:
            mode_block = f"{mode_block}\n\n{mem_str}".strip()

        if old_prompt.strip():
            req.system_prompt = f"{old_prompt.strip()}\n\n{mode_block}".strip()
        else:
            req.system_prompt = mode_block

    def _format_layer_block(self, title: str, memories: Any, item_char_limit: int) -> str:
        if not memories:
            return ""

        safe_item_chars = max(40, int(item_char_limit))
        title_chars = max(16, safe_item_chars // 3)
        content_chars = max(24, safe_item_chars - title_chars - 2)

        lines = [f"[{title}]"]
        for mem in memories:
            raw_title = self._normalize_inline_text(str(mem.get("title", "")))
            raw_content = self._normalize_inline_text(str(mem.get("content", "")))
            mem_title = self._truncate_text(raw_title, title_chars)
            mem_content = self._truncate_text(raw_content, content_chars)

            if not mem_title and not mem_content:
                continue
            if mem_title and mem_content:
                lines.append(f"- {mem_title}: {mem_content}")
            elif mem_content:
                lines.append(f"- {mem_content}")
            else:
                lines.append(f"- {mem_title}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _get_summary_limits(self) -> Dict[str, Any]:
        history_limit_value = self._split_config.get_int("summary_history_limit", 28, 0, 200)
        return {
            "history_limit": None if history_limit_value == 0 else history_limit_value,
            "message_char_limit": self._split_config.get_int("summary_message_char_limit", 220, 60, 1200),
            "total_char_limit": self._split_config.get_int("summary_total_char_limit", 4800, 600, 20000),
        }

    @staticmethod
    def _normalize_inline_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        cleaned = (text or "").strip()
        if max_chars <= 0 or len(cleaned) <= max_chars:
            return cleaned
        if max_chars <= 3:
            return cleaned[:max_chars]
        return cleaned[: max_chars - 3].rstrip() + "..."

    async def _get_conversation_manager(self):
        return getattr(self.context, "conversation_manager", None)

    def _mark_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        state = self._mode_dirty_runtime.setdefault(umo, {})
        state[mode] = True

    async def _clear_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        state = self._mode_dirty_runtime.setdefault(umo, {})
        state[mode] = False

    async def _is_mode_dirty(self, umo: str, mode: str) -> bool:
        if not umo or mode not in MODE_SET:
            return False
        state = self._mode_dirty_runtime.get(umo, {})
        return bool(state.get(mode, False))

    async def _get_current_mode_from_conversation(self, umo: str) -> Optional[str]:
        if not umo:
            return None

        conv_mgr = await self._get_conversation_manager()
        if conv_mgr is None:
            return None

        try:
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        except Exception:
            return None

        if not curr_cid:
            return None

        await self._state_store.ensure_state()
        work_cid = self._state_store.get_mode_conversation_id(umo, "work")
        rest_cid = self._state_store.get_mode_conversation_id(umo, "rest")
        if curr_cid == work_cid:
            return "work"
        if curr_cid == rest_cid:
            return "rest"
        return None

    def _create_state_store(self) -> StateStore:
        return StateStore(
            plugin_name=str(getattr(self, "name", PLUGIN_NAME) or PLUGIN_NAME),
            state_kv_key=STATE_KV_KEY,
            logger=logger,
            get_data_path_func=StarTools.get_data_dir,
            get_kv_data_func=getattr(self, "get_kv_data", None),
            put_kv_data_func=getattr(self, "put_kv_data", None),
        )

    async def _set_mode_override(self, event: AstrMessageEvent, target: str) -> str:
        session_id, umo = self._get_session_identifiers(event)
        key = session_id or umo
        if not key:
            return "Cannot determine current session key."

        await self._state_store.ensure_state()
        if target == "auto":
            self._state_store.clear_session_override(key)
            await self._state_store.save_state()
            return "Session mode override cleared."

        if target not in MODE_SET:
            return "Usage: /mode set work|rest|auto"

        self._state_store.set_session_override(key, target)
        await self._state_store.save_state()
        return f"Session override set to: {target}"

    def _get_session_identifiers(self, event: AstrMessageEvent) -> Tuple[str, str]:
        session_id = ""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            session_id = str(getattr(message_obj, "session_id", "") or "")
        return session_id, umo

    def _help_text(self) -> str:
        return (
            "Character Split Commands:\n"
            "----- 模式控制 -----\n"
            "/mode help - 帮助面板\n"
            "/mode status - 当前状态及记忆数\n"
            "/mode work - 锁定为工作模式\n"
            "/mode rest - 锁定为休息模式\n"
            "/mode auto - 解除锁定恢复自动\n"
            "/mode set work|rest|auto\n"
            "----- 记忆管理 -----\n"
            "/csmem list - 查看三层记忆\n"
            "/csmem rm <id> - 删除指定记忆\n"
            "/csmem sync - 手动触发三层记忆提取\n"
        )

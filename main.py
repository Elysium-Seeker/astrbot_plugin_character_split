# pyright: reportMissingImports=false

import asyncio
import copy
import inspect
from typing import Any, Dict, List, Optional, Tuple

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

@register("character_split", "Elysium-Seeker", "Split work/rest dialog and manage auto-memory", "1.1.0")
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
        
        # count memory items
        memories = await self._memory_manager.get_recent_memories(umo, mode, limit=100)
        mem_count = len(memories)

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

    @csmem.command("list", desc="列出当前模式下记录的记忆事实")
    async def mem_list(self, event: AstrMessageEvent):
        """List current memories"""
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)
        memories = await self._memory_manager.get_recent_memories(umo, mode, limit=20)
        
        if not memories:
            yield event.plain_result(f"当前模式 [{mode}] 暂无长期记忆。")
            return
            
        output = f"[{mode}] 下的近期记忆:\n"
        for idx, m in enumerate(memories, 1):
            output += f"{m['id']}. {m['title']} : {m['content']} ({m['timestamp']})\n"
        yield event.plain_result(output)

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

        yield event.plain_result(f"⏳ 正在后台提取当前模式 [{mode}] 的长期记忆...")
        import asyncio
        asyncio.create_task(
            self._memory_manager.trigger_summary_and_save(self.context, umo, mode, history)
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

            await self._mark_mode_dirty(umo, mode)
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
            # background run summary
            asyncio.create_task(
                self._memory_manager.trigger_summary_and_save(self.context, umo, source_mode, old_history)
            )
            await self._clear_mode_dirty(umo, source_mode)
            
        return switched

    async def _inject_mode_prompt(self, req: ProviderRequest, mode: str, umo: str):
        persona_prompt = self._persona_builder.build(mode)
        
        memories = await self._memory_manager.get_recent_memories(umo, mode, limit=5)
        mem_str = ""
        if memories:
            mem_str = "[当前模式核心记忆与纪要]\n====================\n"
            for m in memories:
                mem_str += f"- {m['title']}: {m['content']}\n"
            mem_str += "====================\n"
            
        old_prompt = getattr(req, "system_prompt", "") or ""
        req.system_prompt = (old_prompt.strip() + f"\n\n[Mode]\nCurrent mode: {mode}\n{persona_prompt}\n\n{mem_str}").strip()

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
            "/csmem list - 查看本模式长期记忆\n"
            "/csmem rm <id> - 删除指定记忆\n"
        )

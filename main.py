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

@register("character_split", "Elysium-Seeker", "Split work/rest dialog and manage auto-memory", "1.1.9")
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

    @mode.command("help", desc="看指令帮助")
    async def mode_help(self, event: AstrMessageEvent):
        """Show mode command help"""
        yield event.plain_result(self._help_text())

    @mode.command("status", desc="看看当前是工作还是休息，以及为什么这么判")
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

    @mode.command("work", desc="强制当前聊天立马切成工作模式")
    async def mode_work(self, event: AstrMessageEvent):
        """Force work mode for current session"""
        msg = await self._set_mode_override(event, "work")
        yield event.plain_result(msg)

    @mode.command("rest", desc="强制切成休息模式")
    async def mode_rest(self, event: AstrMessageEvent):
        """Force rest mode for current session"""
        msg = await self._set_mode_override(event, "rest")
        yield event.plain_result(msg)

    @mode.command("auto", desc="取消锁定恢复顺其自然（按时间切）")
    async def mode_auto(self, event: AstrMessageEvent):
        """Reset to auto mode resolution"""
        msg = await self._set_mode_override(event, "auto")
        yield event.plain_result(msg)

    @mode.command("set", desc="兼容旧指令写法")
    async def mode_set(self, event: AstrMessageEvent, target: str = ""):
        """Compatibility command for /mode set work|rest|auto"""
        target = (target or "").strip().lower()
        if target not in MODE_SET and target != "auto":
            yield event.plain_result("Usage: /mode set work|rest|auto")
            return

        msg = await self._set_mode_override(event, target)
        yield event.plain_result(msg)

    @filter.command_group("csmem", desc="独立三层记忆管理系统")
    def csmem(self):
        """Memory management group"""

    @csmem.command("list", desc="翻一翻当前环境的三层记忆池里都记了啥")
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

    @csmem.command("rm", desc="记错了？抄下 list 里的 ID 给删了")
    async def mem_rm(self, event: AstrMessageEvent, mem_id: int):
        """Remove a specific memory by ID"""
        session_id, umo = self._get_session_identifiers(event)
        success = await self._memory_manager.remove_memory(umo, int(mem_id))
        if success:
            yield event.plain_result(f"已删除记录 #{mem_id}")
        else:
            yield event.plain_result(f"删除失败：没找到这条记录 #{mem_id}")
            
    @csmem.command("sync", desc="觉得 Bot 脑子没跟上？立马把刚刚聊的总结存起来")
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

        if not history:
            yield event.plain_result(f"当前模式 [{mode}] 暂无可提取的历史内容。")
            return

        yield event.plain_result(f"⏳ 正在后台提取当前模式 [{mode}] 的三层记忆（全量历史）...")
        import asyncio
        asyncio.create_task(
            self._memory_manager.trigger_summary_and_save(
                self.context,
                umo,
                mode,
                history,
                history_limit=None,
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
            # background run summary
            asyncio.create_task(
                self._memory_manager.trigger_summary_and_save(self.context, umo, source_mode, old_history)
            )
            await self._clear_mode_dirty(umo, source_mode)
            
        return switched

    async def _inject_mode_prompt(self, req: ProviderRequest, mode: str, umo: str):
        persona_prompt = self._persona_builder.build(mode)
        layers = await self._memory_manager.get_layered_memories(umo, mode)

        mem_blocks = []
        mem_blocks.append(self._format_layer_block("Layer1 全局长期", layers.get("global", [])))
        mem_blocks.append(self._format_layer_block(f"Layer2 {mode} 模式", layers.get("mode", [])))
        mem_blocks.append(self._format_layer_block("Layer3 当前会话", layers.get("session", [])))
        mem_str = "\n\n".join(block for block in mem_blocks if block)

        old_prompt = getattr(req, "system_prompt", "") or ""
        req.system_prompt = (
            old_prompt.strip() + f"\n\n[Mode]\nCurrent mode: {mode}\n{persona_prompt}\n\n{mem_str}"
        ).strip()

    def _format_layer_block(self, title: str, memories: Any) -> str:
        if not memories:
            return ""

        lines = [f"[{title}]"]
        for mem in memories:
            lines.append(f"- {mem.get('title', '')}: {mem.get('content', '')}")
        return "\n".join(lines)

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
        work_cid = await self._state_store.get_mode_conversation_id(umo, "work")
        rest_cid = await self._state_store.get_mode_conversation_id(umo, "rest")
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
            await self._state_store.clear_session_override(key)
            await self._state_store.save_state()
            return "Session mode override cleared."

        if target not in MODE_SET:
            return "Usage: /mode set work|rest|auto"

        await self._state_store.set_session_override(key, target)
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
            "/mode help - 看指令帮助\n"
            "/mode status - 当前是工作还是休息，为什么这么判\n"
            "/mode work - 强制当前聊天立马切成工作模式\n"
            "/mode rest - 强制切成休息模式\n"
            "/mode auto - 取消锁定恢复顺其自然\n"
            "/mode set [work|rest|auto] - 兼容旧写法\n"
            "----- 记忆管理 -----\n"
            "/csmem list - 翻一翻当前的三层记忆池\n"
            "/csmem rm <id> - 记错了？抄下 list 里的 ID 删了\n"
            "/csmem sync - 觉得脑子跟不上？赶紧敲一锤立刻总结\n"
        )

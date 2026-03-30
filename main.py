"""pyright: reportMissingImports=false"""

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
    from .runtime import (
        AstrMessageEvent,
        Context,
        Star,
        filter,
        get_astrbot_data_path,
        logger,
        register,
    )
except Exception:  # pragma: no cover
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
    from runtime import (  # type: ignore
        AstrMessageEvent,
        Context,
        Star,
        filter,
        get_astrbot_data_path,
        logger,
        register,
    )


@register("character_split", "Copilot", "Split work/rest dialog for mnemosyne memory backend", "0.1.5")
class CharacterSplitPlugin(Star):
    def __init__(self, context: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}

        self._split_config = SplitConfig(self.config)
        self._state_store = self._create_state_store()
        self._mode_resolver = ModeResolver(self._split_config, self._state_store)
        self._persona_builder = PersonaPromptBuilder(self._split_config)
        self._conversation_splitter = ConversationSplitter(self._state_store, logger)

    async def initialize(self):
        await self._state_store.ensure_state()

    async def terminate(self):
        await self._state_store.save_state()

    @filter.command_group(
        "mode",
        desc="模式管理指令组。",
    )
    def mode(self):
        """Mode command group"""

    @mode.command("help", desc="查看 mode 指令帮助。")
    async def mode_help(self, event: Any):
        """Show mode command help"""
        yield event.plain_result(self._help_text())

    @mode.command("status", desc="查看当前模式与判定来源。")
    async def mode_status(self, event: Any):
        """Show current mode status"""
        session_id, umo = self._get_session_identifiers(event)
        mode, source = await self._mode_resolver.resolve_mode(session_id, umo)
        text = (
            f"mode: {mode} ({source})\n"
            "memory_backend: mnemosyne\n"
            f"local_time: {self._split_config.current_time_desc()}\n"
            f"session_id: {session_id or '-'}\n"
            f"umo: {umo or '-'}"
        )
        yield event.plain_result(text)

    @mode.command("work", desc="当前会话固定为工作模式。")
    async def mode_work(self, event: Any):
        """Force work mode for current session"""
        msg = await self._set_mode_override(event, "work")
        yield event.plain_result(msg)

    @mode.command("rest", desc="当前会话固定为休息模式。")
    async def mode_rest(self, event: Any):
        """Force rest mode for current session"""
        msg = await self._set_mode_override(event, "rest")
        yield event.plain_result(msg)

    @mode.command("auto", desc="清除覆盖，恢复自动判定。")
    async def mode_auto(self, event: Any):
        """Reset to auto mode resolution"""
        msg = await self._set_mode_override(event, "auto")
        yield event.plain_result(msg)

    @mode.command("set", desc="兼容旧用法：/mode set work|rest|auto。")
    async def mode_set(self, event: Any, target: str = ""):
        """Compatibility command for /mode set work|rest|auto"""
        target = (target or "").strip().lower()
        if target not in MODE_SET and target != "auto":
            yield event.plain_result("Usage: /mode set work|rest|auto")
            return

        msg = await self._set_mode_override(event, target)
        yield event.plain_result(msg)

    @filter.on_llm_request(
        priority=10,
        desc="LLM 请求前置钩子：按 override/time/whitelist/default 判定 work/rest，切换对应会话并注入模式增强提示词。",
    )
    async def on_llm_request(self, event: Any, req: Any):
        try:
            session_id, umo = self._get_session_identifiers(event)
            mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)
            await self._conversation_splitter.ensure_mode_conversation(self.context, event, mode)

            persona_prompt = self._persona_builder.build(mode)
            old_prompt = getattr(req, "system_prompt", "") or ""
            merged = (old_prompt.strip() + "\n\n" + f"[Mode]\nCurrent mode: {mode}\n{persona_prompt}").strip()
            req.system_prompt = merged
        except Exception as exc:
            logger.error(f"character_split on_llm_request failed: {exc}")

    def _create_state_store(self) -> StateStore:
        return StateStore(
            plugin_name=str(getattr(self, "name", PLUGIN_NAME) or PLUGIN_NAME),
            state_kv_key=STATE_KV_KEY,
            logger=logger,
            get_data_path_func=get_astrbot_data_path,
            get_kv_data_func=getattr(self, "get_kv_data", None),
            put_kv_data_func=getattr(self, "put_kv_data", None),
        )

    async def _set_mode_override(self, event: Any, target: str) -> str:
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

    def _get_session_identifiers(self, event: Any) -> Tuple[str, str]:
        session_id = ""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            session_id = str(getattr(message_obj, "session_id", "") or "")
        return session_id, umo

    def _help_text(self) -> str:
        return (
            "Character Split Commands:\n"
            "/mode help\n"
            "/mode status\n"
            "/mode work\n"
            "/mode rest\n"
            "/mode auto\n"
            "/mode set work|rest|auto"
        )

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


@register("character_split", "Copilot", "Split work/rest dialog for mnemosyne memory backend", "0.1.2")
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

    @filter.command("mode")
    async def mode(self, event: Any):
        """Manage mode split behavior. Usage: /mode help"""
        args = self._parse_mode_args(getattr(event, "message_str", ""))
        if not args:
            yield event.plain_result(self._help_text())
            return

        action = args[0].lower()
        if action == "help":
            yield event.plain_result(self._help_text())
            return

        session_id, umo = self._get_session_identifiers(event)
        key = session_id or umo

        if action == "status":
            mode, source = await self._mode_resolver.resolve_mode(session_id, umo)
            text = (
                f"mode: {mode} ({source})\n"
                "memory_backend: mnemosyne\n"
                f"local_time: {self._split_config.current_time_desc()}\n"
                f"session_id: {session_id or '-'}\n"
                f"umo: {umo or '-'}"
            )
            yield event.plain_result(text)
            return

        if action == "set":
            if len(args) < 2:
                yield event.plain_result("Usage: /mode set work|rest|auto")
                return

            target = args[1].lower()
            if not key:
                yield event.plain_result("Cannot determine current session key.")
                return

            await self._state_store.ensure_state()
            if target == "auto":
                self._state_store.clear_session_override(key)
                await self._state_store.save_state()
                yield event.plain_result("Session mode override cleared.")
                return

            if target not in MODE_SET:
                yield event.plain_result("Usage: /mode set work|rest|auto")
                return

            self._state_store.set_session_override(key, target)
            await self._state_store.save_state()
            yield event.plain_result(f"Session override set to: {target}")
            return

        yield event.plain_result(self._help_text())

    @filter.on_llm_request(priority=10)
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

    def _parse_mode_args(self, message_str: str) -> List[str]:
        tokens = (message_str or "").strip().split()
        if not tokens:
            return []

        head = tokens[0].lstrip("/").lower()
        if head == "mode":
            return tokens[1:]
        return tokens

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
            "/mode status\n"
            "/mode set work|rest|auto"
        )

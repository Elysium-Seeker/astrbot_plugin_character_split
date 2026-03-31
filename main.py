# pyright: reportMissingImports=false

from threading import Lock
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

try:
    from astrbot.api import logger
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.provider import ProviderRequest
    from astrbot.api.star import Context, Star, register
except ImportError:  # pragma: no cover
    try:
        from .runtime import (  # type: ignore
            AstrMessageEvent,
            Context,
            ProviderRequest,
            Star,
            filter,
            logger,
            register,
        )
    except ImportError:  # pragma: no cover
        from runtime import (  # type: ignore
            AstrMessageEvent,
            Context,
            ProviderRequest,
            Star,
            filter,
            logger,
            register,
        )

@register("character_split", "Elysium-Seeker", "Split work/rest dialog for mnemosyne memory backend", "1.0.1")
class CharacterSplitPlugin(Star):
    def __init__(self, context: Any, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}

        self._split_config = SplitConfig(self.config)
        self._state_store = self._create_state_store()
        self._mode_resolver = ModeResolver(self._split_config, self._state_store)
        self._persona_builder = PersonaPromptBuilder(self._split_config)
        self._conversation_splitter = ConversationSplitter(self._state_store, logger)
        self._warned_missing_mnemosyne = False
        self._warned_missing_mnemosyne_recall = False
        self._runtime_state_lock = Lock()
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
    async def mode_help(self, event: Any):
        """Show mode command help"""
        yield event.plain_result(self._help_text())

    @mode.command("status", desc="查询当前生效模式及触发来源（如时间、覆写配置）")
    async def mode_status(self, event: Any):
        """Show current mode status"""
        session_id, umo = self._get_session_identifiers(event)
        mode, source = await self._mode_resolver.resolve_mode(session_id, umo)
        mnemosyne_available = await self._is_mnemosyne_available()
        require_backend = self._split_config.get_bool("require_mnemosyne_for_split", True)
        split_state = "enabled" if (mnemosyne_available or not require_backend) else "fallback-single-conversation"
        backend_state = "mnemosyne(ready)" if mnemosyne_available else "mnemosyne(unavailable)"
        text = (
            f"mode: {mode} ({source})\n"
            f"memory_backend: {backend_state}\n"
            f"split_state: {split_state}\n"
            f"local_time: {self._split_config.current_time_desc()}\n"
            f"session_id: {session_id or '-'}\n"
            f"umo: {umo or '-'}"
        )
        yield event.plain_result(text)

    @mode.command("work", desc="锁定当前会话为工作模式")
    async def mode_work(self, event: Any):
        """Force work mode for current session"""
        msg = await self._set_mode_override(event, "work")
        yield event.plain_result(msg)

    @mode.command("rest", desc="锁定当前会话为休息模式")
    async def mode_rest(self, event: Any):
        """Force rest mode for current session"""
        msg = await self._set_mode_override(event, "rest")
        yield event.plain_result(msg)

    @mode.command("auto", desc="解除强制锁定，恢复时间规则自动调度")
    async def mode_auto(self, event: Any):
        """Reset to auto mode resolution"""
        msg = await self._set_mode_override(event, "auto")
        yield event.plain_result(msg)

    @mode.command("set", desc="兼容旧版：参数填 work/rest/auto 快速锁定模式")
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
        desc="拦截 LLM 请求前置钩子：根据时间和用户配置判定工作状况并剥离上下文及注入增量提示词",
    )
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            session_id, umo = self._get_session_identifiers(event)
            mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)
            mnemosyne_available = await self._is_mnemosyne_available()
            require_backend = self._split_config.get_bool("require_mnemosyne_for_split", True)
            source_mode = await self._get_current_mode_from_conversation(umo)

            if mnemosyne_available or not require_backend:
                pre_switch_hook = (
                    self._build_pre_switch_hook(event, umo, source_mode) if mnemosyne_available else None
                )
                switched = await self._conversation_splitter.ensure_mode_conversation(
                    self.context,
                    event,
                    mode,
                    pre_switch_hook=pre_switch_hook,
                )
                if switched and mnemosyne_available:
                    await self._trigger_mnemosyne_recall(event, mode)
            else:
                self._warn_missing_mnemosyne_once()

            self._mark_mode_dirty(umo, mode)

            persona_prompt = self._persona_builder.build(mode)
            old_prompt = getattr(req, "system_prompt", "") or ""
            merged = (old_prompt.strip() + "\n\n" + f"[Mode]\nCurrent mode: {mode}\n{persona_prompt}").strip()
            req.system_prompt = merged
        except Exception:
            logger.exception("character_split on_llm_request failed")

    async def _get_loaded_stars(self) -> List[Any]:
        get_all_stars = getattr(self.context, "get_all_stars", None)
        if not callable(get_all_stars):
            return []

        stars = get_all_stars()
        if hasattr(stars, "__await__"):
            stars = await stars
        stars = stars or []
        if isinstance(stars, dict):
            return list(stars.values())
        if isinstance(stars, list):
            return stars
        try:
            return list(stars)
        except Exception:
            return []

    def _is_mnemosyne_star(self, star: Any) -> bool:
        star_name = str(getattr(star, "name", "") or "").lower()
        root_name = str(getattr(star, "root_dir_name", "") or "").lower()
        return "mnemosyne" in star_name or "mnemosyne" in root_name

    async def _is_mnemosyne_available(self) -> bool:
        stars = await self._get_loaded_stars()
        for star in stars:
            if self._is_mnemosyne_star(star):
                with self._runtime_state_lock:
                    self._warned_missing_mnemosyne = False
                return True
        return False

    def _warn_missing_mnemosyne_once(self):
        with self._runtime_state_lock:
            if self._warned_missing_mnemosyne:
                return
            logger.warning(
                "character_split: mnemosyne backend unavailable. Split is temporarily disabled to preserve single-conversation context. "
                "Set require_mnemosyne_for_split=false to force split without mnemosyne."
            )
            self._warned_missing_mnemosyne = True

    def _mark_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        with self._runtime_state_lock:
            state = self._mode_dirty_runtime.setdefault(umo, {})
            state[mode] = True

    def _clear_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        with self._runtime_state_lock:
            state = self._mode_dirty_runtime.setdefault(umo, {})
            state[mode] = False

    def _is_mode_dirty(self, umo: str, mode: str) -> bool:
        if not umo or mode not in MODE_SET:
            return False
        with self._runtime_state_lock:
            state = self._mode_dirty_runtime.get(umo, {})
            return bool(state.get(mode, False))

    async def _get_current_mode_from_conversation(self, umo: str) -> Optional[str]:
        if not umo:
            return None

        conv_mgr = getattr(self.context, "conversation_manager", None)
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

    def _build_pre_switch_hook(self, event: Any, umo: str, source_mode: Optional[str]):
        if source_mode not in MODE_SET:
            return lambda: self._trigger_mnemosyne_checkpoint(event)

        skip_without_messages = self._split_config.get_bool("skip_checkpoint_without_messages", True)
        if skip_without_messages and not self._is_mode_dirty(umo, source_mode):
            logger.info(
                f"character_split skip checkpoint: source mode '{source_mode}' has no new messages in this period"
            )
            return None

        return lambda: self._trigger_mnemosyne_checkpoint_for_mode(event, umo, source_mode)

    async def _trigger_mnemosyne_checkpoint_for_mode(self, event: Any, umo: str, source_mode: str):
        success = await self._trigger_mnemosyne_checkpoint(event)
        if success:
            self._clear_mode_dirty(umo, source_mode)

    async def _trigger_mnemosyne_checkpoint(self, event: Any):
        if not self._split_config.get_bool("flush_mnemosyne_on_mode_switch", True):
            return False

        if hasattr(event, "set_extra"):
            try:
                event.set_extra("mnemosyne_mode_switch_checkpoint", True)
            except Exception:
                pass

        stars = await self._get_loaded_stars()

        candidate_methods = [
            "checkpoint_now",
            "flush_memory",
            "save_memory_now",
            "force_extract_memory",
            "extract_memory_now",
            "trigger_memory_extraction",
        ]

        for star in stars:
            if not self._is_mnemosyne_star(star):
                continue

            candidates = []
            for attr in ("star_obj", "plugin", "instance", "star", "star_cls"):
                obj = getattr(star, attr, None)
                if obj is not None:
                    candidates.append(obj)
            candidates.append(star)

            seen_ids = set()
            for plugin_obj in candidates:
                obj_id = id(plugin_obj)
                if obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)

                for method_name in candidate_methods:
                    method = getattr(plugin_obj, method_name, None)
                    if not callable(method):
                        continue

                    for args in ((event,), tuple()):
                        try:
                            result = method(*args)
                            if hasattr(result, "__await__"):
                                await result
                            logger.info(
                                f"character_split mnemosyne checkpoint via {method_name} succeeded"
                            )
                            return True
                        except TypeError:
                            continue
                        except Exception as exc:
                            logger.warning(
                                f"character_split mnemosyne checkpoint via {method_name} failed: {exc}"
                            )
                            break
        return False

    async def _trigger_mnemosyne_recall(self, event: Any, mode: str):
        if not self._split_config.get_bool("force_mnemosyne_recall_on_mode_switch", True):
            return

        if hasattr(event, "set_extra"):
            try:
                event.set_extra("mnemosyne_mode_switch_force_recall", True)
                event.set_extra("mnemosyne_target_mode", mode)
            except Exception:
                pass

        stars = await self._get_loaded_stars()
        candidate_methods = [
            "recall_now",
            "reload_memory",
            "refresh_memory",
            "inject_memory_now",
            "retrieve_memory",
            "retrieve_memories",
            "force_recall",
        ]

        for star in stars:
            if not self._is_mnemosyne_star(star):
                continue

            candidates = []
            for attr in ("star_obj", "plugin", "instance", "star", "star_cls"):
                obj = getattr(star, attr, None)
                if obj is not None:
                    candidates.append(obj)
            candidates.append(star)

            seen_ids = set()
            for plugin_obj in candidates:
                obj_id = id(plugin_obj)
                if obj_id in seen_ids:
                    continue
                seen_ids.add(obj_id)

                for method_name in candidate_methods:
                    method = getattr(plugin_obj, method_name, None)
                    if not callable(method):
                        continue

                    for args in ((event, mode), (event,), (mode,), tuple()):
                        try:
                            result = method(*args)
                            if hasattr(result, "__await__"):
                                await result
                            with self._runtime_state_lock:
                                self._warned_missing_mnemosyne_recall = False
                            logger.info(
                                f"character_split mnemosyne recall via {method_name} succeeded"
                            )
                            return
                        except TypeError:
                            continue
                        except Exception as exc:
                            logger.warning(
                                f"character_split mnemosyne recall via {method_name} failed: {exc}"
                            )
                            break

        with self._runtime_state_lock:
            if not self._warned_missing_mnemosyne_recall:
                logger.warning(
                    "character_split: mode switched but no mnemosyne recall API matched. "
                    "Set force_mnemosyne_recall_on_mode_switch=false if you do not need forced recall."
                )
                self._warned_missing_mnemosyne_recall = True

    def _create_state_store(self) -> StateStore:
        return StateStore(
            plugin_name=str(getattr(self, "name", PLUGIN_NAME) or PLUGIN_NAME),
            state_kv_key=STATE_KV_KEY,
            logger=logger,
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

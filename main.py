"""pyright: reportMissingImports=false"""

import importlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    _astr_api = importlib.import_module("astrbot.api")
    _event_mod = importlib.import_module("astrbot.api.event")
    _star_mod = importlib.import_module("astrbot.api.star")
    _provider_mod = importlib.import_module("astrbot.api.provider")

    logger = _astr_api.logger
    AstrBotConfig = getattr(_astr_api, "AstrBotConfig", dict)
    AstrMessageEvent = _event_mod.AstrMessageEvent
    filter = _event_mod.filter
    Context = _star_mod.Context
    Star = _star_mod.Star
    register = _star_mod.register
    ProviderRequest = _provider_mod.ProviderRequest
except Exception:  # pragma: no cover
    class _DummyLogger:
        def info(self, msg: str):
            print(msg)

        def warning(self, msg: str):
            print(msg)

        def error(self, msg: str):
            print(msg)

    class _DummyFilter:
        @staticmethod
        def command(*_args: Any, **_kwargs: Any):
            def _decorator(func: Any):
                return func

            return _decorator

        @staticmethod
        def on_llm_request(*_args: Any, **_kwargs: Any):
            def _decorator(func: Any):
                return func

            return _decorator

    def register(*_args: Any, **_kwargs: Any):
        def _decorator(cls: Any):
            return cls

        return _decorator

    class Context:  # type: ignore
        pass

    class Star:  # type: ignore
        def __init__(self, context: Any):
            self.context = context

    class AstrMessageEvent:  # type: ignore
        pass

    logger = _DummyLogger()
    filter = _DummyFilter()
    AstrBotConfig = dict
    ProviderRequest = Any

try:
    get_astrbot_data_path = importlib.import_module(
        "astrbot.core.utils.astrbot_path"
    ).get_astrbot_data_path
except Exception:  # pragma: no cover
    get_astrbot_data_path = None


MODE_WORK = "work"
MODE_REST = "rest"
MODE_SET = {MODE_WORK, MODE_REST}
PLUGIN_NAME = "astrbot_plugin_character_split"
STATE_KV_KEY = "character_split_state"


@register("character_split", "Copilot", "Split work/rest dialog for mnemosyne memory backend", "1.0.0")
class CharacterSplitPlugin(Star):
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}
        self._state: Optional[Dict[str, Any]] = None

    async def initialize(self):
        await self._ensure_state()

    async def terminate(self):
        await self._save_state()

    @filter.command("persona")
    async def persona(self, event: AstrMessageEvent):
        """Manage mode split behavior. Usage: /persona help"""
        args = self._parse_persona_args(getattr(event, "message_str", ""))
        if not args:
            yield event.plain_result(self._help_text())
            return

        action = args[0].lower()

        if action == "help":
            yield event.plain_result(self._help_text())
            return

        if action == "status":
            mode, source = await self._resolve_mode(event)
            session_id, umo = self._get_session_identifiers(event)
            now_desc = self._current_time_desc()
            text = (
                f"mode: {mode} ({source})\n"
                "memory_backend: mnemosyne\n"
                f"local_time: {now_desc}\n"
                f"session_id: {session_id or '-'}\n"
                f"umo: {umo or '-'}"
            )
            yield event.plain_result(text)
            return

        if action == "set":
            if len(args) < 2:
                yield event.plain_result("Usage: /persona set work|rest|auto")
                return
            target = args[1].lower()
            session_id, umo = self._get_session_identifiers(event)
            key = session_id or umo
            if not key:
                yield event.plain_result("Cannot determine current session key.")
                return

            state = await self._ensure_state()
            overrides = state["session_overrides"]
            if target == "auto":
                overrides.pop(key, None)
                await self._save_state()
                yield event.plain_result("Session mode override cleared.")
                return
            if target not in MODE_SET:
                yield event.plain_result("Usage: /persona set work|rest|auto")
                return

            overrides[key] = target
            await self._save_state()
            yield event.plain_result(f"Session override set to: {target}")
            return

        yield event.plain_result(self._help_text())

    @filter.on_llm_request(priority=10)
    async def on_llm_request(self, event: AstrMessageEvent, req: Any):
        try:
            mode, _ = await self._resolve_mode(event)
            await self._ensure_mode_conversation(event, mode)

            persona_prompt = self._get_persona_prompt(mode)

            additions: List[str] = []
            additions.append(f"[Mode]\nCurrent mode: {mode}\n{persona_prompt}")

            old_prompt = getattr(req, "system_prompt", "") or ""
            merged = (old_prompt.strip() + "\n\n" + "\n\n".join(additions)).strip()
            req.system_prompt = merged
        except Exception as exc:
            logger.error(f"character_split on_llm_request failed: {exc}")

    async def _ensure_mode_conversation(self, event: AstrMessageEvent, mode: str):
        conv_mgr = getattr(self.context, "conversation_manager", None)
        if conv_mgr is None:
            return

        umo = getattr(event, "unified_msg_origin", "")
        if not umo:
            return

        state = await self._ensure_state()
        conversation_map = state["session_conversations"].setdefault(umo, {})
        target_cid = conversation_map.get(mode)

        if target_cid:
            try:
                curr_cid = await conv_mgr.get_curr_conversation_id(umo)
                if curr_cid != target_cid:
                    await conv_mgr.switch_conversation(umo, target_cid)
                return
            except Exception:
                conversation_map.pop(mode, None)

        new_title = f"{mode}:{getattr(event, 'get_sender_name', lambda: 'user')()}"
        new_cid = await self._new_conversation(conv_mgr, umo, new_title)
        if new_cid:
            conversation_map[mode] = new_cid
            await self._save_state()

    async def _new_conversation(self, conv_mgr: Any, umo: str, title: str) -> Optional[str]:
        try:
            return await conv_mgr.new_conversation(unified_msg_origin=umo, title=title)
        except TypeError:
            pass
        except Exception as exc:
            logger.warning(f"new_conversation failed (keywords): {exc}")

        try:
            return await conv_mgr.new_conversation(umo, title=title)
        except TypeError:
            pass
        except Exception as exc:
            logger.warning(f"new_conversation failed (positional with title): {exc}")

        try:
            return await conv_mgr.new_conversation(umo)
        except Exception as exc:
            logger.error(f"new_conversation failed: {exc}")
            return None

    async def _resolve_mode(self, event: AstrMessageEvent) -> Tuple[str, str]:
        session_id, umo = self._get_session_identifiers(event)
        state = await self._ensure_state()

        # Manual override is always the highest priority.
        for key in (session_id, umo):
            if key and state["session_overrides"].get(key) in MODE_SET:
                return state["session_overrides"][key], "override"

        time_mode = self._resolve_mode_from_time()
        if time_mode in MODE_SET:
            return time_mode, "time"

        work_ids = self._parse_ids(self._cfg("work_sessions", ""))
        rest_ids = self._parse_ids(self._cfg("rest_sessions", ""))

        for key in (session_id, umo):
            if key and key in work_ids:
                return MODE_WORK, "config"
        for key in (session_id, umo):
            if key and key in rest_ids:
                return MODE_REST, "config"

        default_mode = str(self._cfg("default_mode", MODE_REST)).strip().lower()
        if default_mode not in MODE_SET:
            default_mode = MODE_REST
        return default_mode, "default"

    def _get_persona_prompt(self, mode: str) -> str:
        default_core = (
            "You are the same person in both work and rest modes. "
            "Keep the same values, memory continuity and identity across modes."
        )
        default_work = (
            "WORK augmentation: keep responses concise and structured. "
            "Strengthen capability in task decomposition, priority planning, risk spotting, "
            "decision framing and practical execution suggestions."
        )
        default_rest = (
            "REST augmentation: keep responses warm, empathetic and humanized while staying truthful. "
            "Use a relaxed conversational tone and include emotional support when appropriate."
        )

        core_prompt = str(self._cfg("core_persona_prompt", default_core)).strip() or default_core

        if mode == MODE_WORK:
            mode_prompt = str(self._cfg("work_persona_prompt", default_work)).strip() or default_work
            return f"{core_prompt}\n\n{mode_prompt}"

        mode_prompt = str(self._cfg("rest_persona_prompt", default_rest)).strip() or default_rest
        return f"{core_prompt}\n\n{mode_prompt}"

    def _parse_persona_args(self, message_str: str) -> List[str]:
        tokens = (message_str or "").strip().split()
        if not tokens:
            return []

        head = tokens[0].lstrip("/").lower()
        if head == "persona":
            return tokens[1:]
        return tokens

    def _get_session_identifiers(self, event: AstrMessageEvent) -> Tuple[str, str]:
        session_id = ""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            session_id = str(getattr(message_obj, "session_id", "") or "")
        return session_id, umo

    def _parse_ids(self, raw: Any) -> Set[str]:
        text = str(raw or "")
        normalized = text.replace(",", "\n").replace(";", "\n")
        result: Set[str] = set()
        for line in normalized.splitlines():
            v = line.strip()
            if v:
                result.add(v)
        return result

    def _cfg(self, key: str, default: Any) -> Any:
        try:
            return self.config.get(key, default)
        except Exception:
            return default

    def _cfg_bool(self, key: str, default: bool) -> bool:
        value = self._cfg(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _cfg_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self._cfg(key, default)
        try:
            num = int(value)
        except Exception:
            num = default
        return max(minimum, min(maximum, num))

    def _resolve_mode_from_time(self) -> Optional[str]:
        if not self._cfg_bool("time_mode_enabled", True):
            return None

        now = self._now_in_config_timezone()
        work_days = self._parse_work_days(self._cfg("work_days", "1,2,3,4,5"))

        # Python weekday: Monday=0..Sunday=6, convert to 1..7.
        today = now.weekday() + 1
        if work_days and today not in work_days:
            return MODE_REST

        minute_now = now.hour * 60 + now.minute
        windows = self._parse_time_windows(self._cfg("work_time_windows", "09:00-18:00"))
        if not windows:
            return None

        for start_min, end_min in windows:
            if start_min <= end_min:
                if start_min <= minute_now <= end_min:
                    return MODE_WORK
            else:
                # Cross-midnight window, e.g. 22:00-02:00.
                if minute_now >= start_min or minute_now <= end_min:
                    return MODE_WORK

        return MODE_REST

    def _parse_work_days(self, raw: Any) -> Set[int]:
        text = str(raw or "")
        normalized = text.replace(";", ",").replace(" ", ",")
        values: Set[int] = set()
        for item in normalized.split(","):
            v = item.strip()
            if not v:
                continue
            try:
                day = int(v)
            except Exception:
                continue
            if 1 <= day <= 7:
                values.add(day)
        return values

    def _parse_time_windows(self, raw: Any) -> List[Tuple[int, int]]:
        text = str(raw or "").strip()
        if not text:
            return []

        segments: List[str] = []
        for line in text.splitlines():
            parts = line.replace(";", ",").split(",")
            for part in parts:
                seg = part.strip()
                if seg:
                    segments.append(seg)

        windows: List[Tuple[int, int]] = []
        for seg in segments:
            if "-" not in seg:
                continue
            left, right = seg.split("-", 1)
            start_min = self._parse_hhmm(left.strip())
            end_min = self._parse_hhmm(right.strip())
            if start_min is None or end_min is None:
                continue
            windows.append((start_min, end_min))
        return windows

    def _parse_hhmm(self, hhmm: str) -> Optional[int]:
        if ":" not in hhmm:
            return None
        hh, mm = hhmm.split(":", 1)
        try:
            h = int(hh)
            m = int(mm)
        except Exception:
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m

    def _now_in_config_timezone(self) -> datetime:
        offset = self._cfg_int("timezone_offset_hours", 8, -12, 14)
        tz = timezone(timedelta(hours=offset))
        return datetime.now(tz)

    def _current_time_desc(self) -> str:
        now = self._now_in_config_timezone()
        offset = self._cfg_int("timezone_offset_hours", 8, -12, 14)
        sign = "+" if offset >= 0 else ""
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} UTC{sign}{offset}"

    async def _ensure_state(self) -> Dict[str, Any]:
        if self._state is not None:
            return self._state

        state: Optional[Dict[str, Any]] = None

        state = await self._load_state_from_kv()
        if state is None:
            state = self._load_state_from_file()

        self._state = self._normalize_state(state)
        return self._state

    async def _load_state_from_kv(self) -> Optional[Dict[str, Any]]:
        getter = getattr(self, "get_kv_data", None)
        if getter is None:
            return None

        try:
            data = await getter(STATE_KV_KEY, None)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning(f"load kv state failed: {exc}")
        return None

    def _load_state_from_file(self) -> Dict[str, Any]:
        path = self._state_file_path()
        if not path.exists():
            return self._default_state()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:
            logger.warning(f"load file state failed: {exc}")

        return self._default_state()

    async def _save_state(self):
        if self._state is None:
            return

        putter = getattr(self, "put_kv_data", None)
        if putter is not None:
            try:
                await putter(STATE_KV_KEY, self._state)
            except Exception as exc:
                logger.warning(f"save kv state failed: {exc}")

        try:
            path = self._state_file_path()
            path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"save file state failed: {exc}")

    def _state_file_path(self) -> Path:
        plugin_name = str(getattr(self, "name", PLUGIN_NAME) or PLUGIN_NAME)

        if get_astrbot_data_path is not None:
            base = get_astrbot_data_path() / "plugin_data" / plugin_name
        else:
            base = Path(__file__).resolve().parent / "data"

        base.mkdir(parents=True, exist_ok=True)
        return base / "state.json"

    def _normalize_state(self, raw: Any) -> Dict[str, Any]:
        base = self._default_state()
        if not isinstance(raw, dict):
            return base

        for key in base.keys():
            value = raw.get(key)
            if isinstance(value, dict):
                base[key] = value
        return base

    def _default_state(self) -> Dict[str, Any]:
        return {
            "session_overrides": {},
            "session_conversations": {},
        }

    def _help_text(self) -> str:
        return (
            "Character Split Commands:\n"
            "/persona status\n"
            "/persona set work|rest|auto"
        )

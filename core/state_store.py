# pyright: reportMissingImports=false

import asyncio
import inspect
import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

try:
    from astrbot.api.star import StarTools
except ImportError:  # pragma: no cover
    StarTools = None  # type: ignore





class StateStore:
    def __init__(
        self,
        plugin_name: str,
        state_kv_key: str,
        logger: Any,
        get_data_path_func: Any = None,
        get_kv_data_func: Any = None,
        put_kv_data_func: Any = None,
    ):
        self._plugin_name = plugin_name
        self._state_kv_key = state_kv_key
        self._logger = logger
        self._get_data_path_func = get_data_path_func
        self._get_kv_data_func = get_kv_data_func
        self._put_kv_data_func = put_kv_data_func
        self._state: Optional[Dict[str, Any]] = None
        self._state_lock = asyncio.Lock()

    async def ensure_state(self) -> Dict[str, Any]:
        async with self._state_lock:
            if self._state is not None:
                return self._state

            state = await self._load_state_from_kv()
            if state is None:
                state = await self._load_state_from_file()

            normalized = self._normalize_state(state)
            self._state = normalized
            return self._state

    async def save_state(self):
        async with self._state_lock:
            if self._state is None:
                return
            state_snapshot = deepcopy(self._state)

        if self._put_kv_data_func is not None:
            try:
                await self._call_maybe_async(self._put_kv_data_func, self._state_kv_key, state_snapshot)
            except Exception as exc:
                self._logger.warning(f"save kv state failed: {exc}")

        try:
            path = await self._state_file_path()
            path.write_text(
                json.dumps(state_snapshot, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self._logger.warning(f"save file state failed: {exc}")

    async def get_session_override(self, key: str) -> Optional[str]:
        async with self._state_lock:
            if not self._state or not key:
                return None
            value = self._state["session_overrides"].get(key)
            if isinstance(value, str):
                return value
            return None

    async def set_session_override(self, key: str, mode: str):
        async with self._state_lock:
            if not self._state or not key:
                return
            self._state["session_overrides"][key] = mode

    async def clear_session_override(self, key: str):
        async with self._state_lock:
            if not self._state or not key:
                return
            self._state["session_overrides"].pop(key, None)

    async def get_mode_conversation_id(self, umo: str, mode: str) -> Optional[str]:
        async with self._state_lock:
            if not self._state or not umo:
                return None
            session_map = self._state["session_conversations"].get(umo, {})
            value = session_map.get(mode)
            if isinstance(value, str):
                return value
            return None

    async def set_mode_conversation_id(self, umo: str, mode: str, conversation_id: str):
        async with self._state_lock:
            if not self._state or not umo:
                return
            session_map = self._state["session_conversations"].setdefault(umo, {})
            session_map[mode] = conversation_id

    async def remove_mode_conversation_id(self, umo: str, mode: str):
        async with self._state_lock:
            if not self._state or not umo:
                return
            session_map = self._state["session_conversations"].setdefault(umo, {})
            session_map.pop(mode, None)

    async def get_memory_injection_cursors(self, umo: str, mode: str) -> Dict[str, int]:
        async with self._state_lock:
            if not self._state or not umo:
                return {"global": 0, "mode": 0, "session": 0}

            root = self._state["memory_injection_cursors"].get(umo, {})
            global_cursor = self._safe_int(root.get("global"), 0)

            mode_map = root.get(mode, {}) if isinstance(root, dict) else {}
            mode_cursor = 0
            session_cursor = 0
            if isinstance(mode_map, dict):
                mode_cursor = self._safe_int(mode_map.get("mode"), 0)
                session_cursor = self._safe_int(mode_map.get("session"), 0)

            return {
                "global": max(0, global_cursor),
                "mode": max(0, mode_cursor),
                "session": max(0, session_cursor),
            }

    async def update_memory_injection_cursors(self, umo: str, mode: str, cursors: Dict[str, int]):
        async with self._state_lock:
            if not self._state or not umo:
                return

            root = self._state["memory_injection_cursors"].setdefault(umo, {})
            if not isinstance(root, dict):
                root = {}
                self._state["memory_injection_cursors"][umo] = root

            if "global" in cursors:
                current = self._safe_int(root.get("global"), 0)
                root["global"] = max(current, self._safe_int(cursors.get("global"), 0))

            if mode:
                mode_map = root.setdefault(mode, {})
                if not isinstance(mode_map, dict):
                    mode_map = {}
                    root[mode] = mode_map

                if "mode" in cursors:
                    current_mode = self._safe_int(mode_map.get("mode"), 0)
                    mode_map["mode"] = max(current_mode, self._safe_int(cursors.get("mode"), 0))

                if "session" in cursors:
                    current_session = self._safe_int(mode_map.get("session"), 0)
                    mode_map["session"] = max(current_session, self._safe_int(cursors.get("session"), 0))

    async def clear_memory_injection_cursors(self, umo: str):
        async with self._state_lock:
            if not self._state or not umo:
                return
            self._state["memory_injection_cursors"].pop(umo, None)

    async def get_mode_period(self, umo: str, mode: str) -> int:
        async with self._state_lock:
            if not self._state or not umo or not mode:
                return 0

            root = self._state["memory_mode_periods"].get(umo, {})
            if not isinstance(root, dict):
                return 0
            return max(0, self._safe_int(root.get(mode), 0))

    async def bump_mode_period(self, umo: str, mode: str) -> int:
        async with self._state_lock:
            if not self._state or not umo or not mode:
                return 0

            root = self._state["memory_mode_periods"].setdefault(umo, {})
            if not isinstance(root, dict):
                root = {}
                self._state["memory_mode_periods"][umo] = root

            current = max(0, self._safe_int(root.get(mode), 0))
            next_period = current + 1
            root[mode] = next_period
            return next_period

    async def ensure_mode_period(self, umo: str, mode: str) -> int:
        async with self._state_lock:
            if not self._state or not umo or not mode:
                return 0

            root = self._state["memory_mode_periods"].setdefault(umo, {})
            if not isinstance(root, dict):
                root = {}
                self._state["memory_mode_periods"][umo] = root

            current = max(0, self._safe_int(root.get(mode), 0))
            if current <= 0:
                current = 1
                root[mode] = current
            return current

    async def get_previous_mode_period(self, umo: str, mode: str) -> int:
        current = await self.get_mode_period(umo, mode)
        return max(0, current - 1)

    async def _load_state_from_kv(self) -> Optional[Dict[str, Any]]:
        if self._get_kv_data_func is None:
            return None

        try:
            data = await self._call_maybe_async(self._get_kv_data_func, self._state_kv_key, None)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            self._logger.warning(f"load kv state failed: {exc}")
        return None

    async def _load_state_from_file(self) -> Dict[str, Any]:
        path = await self._state_file_path()
        if not path.exists():
            return self._default_state()

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception as exc:
            self._logger.warning(f"load file state failed: {exc}")

        return self._default_state()

    async def _state_file_path(self) -> Path:
        candidates = []
        if StarTools is not None:
            for name in ("get_data_dir", "get_data_path", "get_astrbot_data_path"):
                candidate = getattr(StarTools, name, None)
                if callable(candidate):
                    candidates.append(candidate)

        if self._get_data_path_func is not None:
            candidates.append(self._get_data_path_func)

        for candidate in candidates:
            try:
                raw_base = await self._call_maybe_async(candidate)
                if raw_base is None:
                    continue
                base_root = raw_base if isinstance(raw_base, Path) else Path(str(raw_base))
                base = self._normalize_plugin_data_dir(base_root)
                base.mkdir(parents=True, exist_ok=True)
                return base / "state.json"
            except Exception as exc:
                candidate_name = getattr(candidate, "__name__", repr(candidate))
                self._logger.warning(f"resolve data dir via {candidate_name} failed: {exc}")

        # Last-resort fallback for environments where StarTools path helpers are unavailable.
        fallback = Path.cwd() / "data" / "plugin_data" / self._plugin_name
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            self._logger.warning(f"fallback to cwd plugin data dir: {fallback}")
            return fallback / "state.json"
        except Exception as exc:
            raise RuntimeError("unable to resolve plugin data dir from StarTools/get_data_path_func") from exc

    def _normalize_plugin_data_dir(self, base_root: Path) -> Path:
        if base_root.name == self._plugin_name:
            return base_root
        if base_root.name == "plugin_data":
            return base_root / self._plugin_name
        if "plugin_data" in base_root.parts:
            plugin_data_index = base_root.parts.index("plugin_data") + 1
            if plugin_data_index < len(base_root.parts) and base_root.parts[plugin_data_index] == self._plugin_name:
                return base_root
            return base_root / self._plugin_name
        return base_root / "plugin_data" / self._plugin_name

    def _normalize_state(self, raw: Any) -> Dict[str, Any]:
        base = self._default_state()
        if not isinstance(raw, dict):
            return base

        for key in base.keys():
            value = raw.get(key)
            if isinstance(value, dict):
                base[key] = deepcopy(value)
        return base

    def _default_state(self) -> Dict[str, Any]:
        return {
            "session_overrides": {},
            "session_conversations": {},
            "memory_injection_cursors": {},
            "memory_mode_periods": {},
        }

    @staticmethod
    def _safe_int(raw: Any, default: int = 0) -> int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    async def _call_maybe_async(self, func: Any, *args: Any) -> Any:
        if inspect.iscoroutinefunction(func):
            return await func(*args)

        result = func(*args)
        if inspect.isawaitable(result):
            return await result
        return result

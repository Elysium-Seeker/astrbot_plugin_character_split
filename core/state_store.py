import json
from pathlib import Path
from typing import Any, Dict, Optional


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

    async def ensure_state(self) -> Dict[str, Any]:
        if self._state is not None:
            return self._state

        state = await self._load_state_from_kv()
        if state is None:
            state = self._load_state_from_file()

        self._state = self._normalize_state(state)
        return self._state

    async def save_state(self):
        if self._state is None:
            return

        if self._put_kv_data_func is not None:
            try:
                await self._put_kv_data_func(self._state_kv_key, self._state)
            except Exception as exc:
                self._logger.warning(f"save kv state failed: {exc}")

        try:
            path = self._state_file_path()
            path.write_text(
                json.dumps(self._state, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            self._logger.warning(f"save file state failed: {exc}")

    def get_session_override(self, key: str) -> Optional[str]:
        if not self._state or not key:
            return None
        value = self._state["session_overrides"].get(key)
        if isinstance(value, str):
            return value
        return None

    def set_session_override(self, key: str, mode: str):
        if not self._state or not key:
            return
        self._state["session_overrides"][key] = mode

    def clear_session_override(self, key: str):
        if not self._state or not key:
            return
        self._state["session_overrides"].pop(key, None)

    def get_mode_conversation_id(self, umo: str, mode: str) -> Optional[str]:
        if not self._state or not umo:
            return None
        session_map = self._state["session_conversations"].get(umo, {})
        value = session_map.get(mode)
        if isinstance(value, str):
            return value
        return None

    def set_mode_conversation_id(self, umo: str, mode: str, conversation_id: str):
        if not self._state or not umo:
            return
        session_map = self._state["session_conversations"].setdefault(umo, {})
        session_map[mode] = conversation_id

    def remove_mode_conversation_id(self, umo: str, mode: str):
        if not self._state or not umo:
            return
        session_map = self._state["session_conversations"].setdefault(umo, {})
        session_map.pop(mode, None)

    async def _load_state_from_kv(self) -> Optional[Dict[str, Any]]:
        if self._get_kv_data_func is None:
            return None

        try:
            data = await self._get_kv_data_func(self._state_kv_key, None)
            if isinstance(data, dict):
                return data
        except Exception as exc:
            self._logger.warning(f"load kv state failed: {exc}")
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
            self._logger.warning(f"load file state failed: {exc}")

        return self._default_state()

    def _state_file_path(self) -> Path:
        if self._get_data_path_func is not None:
            try:
                raw_base = self._get_data_path_func()
                base_root = raw_base if isinstance(raw_base, Path) else Path(str(raw_base))
                base = base_root / "plugin_data" / self._plugin_name
            except Exception:
                base = Path(__file__).resolve().parent.parent / "data"
        else:
            base = Path(__file__).resolve().parent.parent / "data"

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

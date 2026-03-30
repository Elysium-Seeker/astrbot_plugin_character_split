from typing import Optional, Tuple

from .config import SplitConfig
from .constants import MODE_REST, MODE_SET, MODE_WORK
from .state_store import StateStore


class ModeResolver:
    def __init__(self, config: SplitConfig, state_store: StateStore):
        self._config = config
        self._state_store = state_store

    async def resolve_mode(self, session_id: str, umo: str) -> Tuple[str, str]:
        await self._state_store.ensure_state()

        for key in (session_id, umo):
            override = self._state_store.get_session_override(key)
            if key and override in MODE_SET:
                return override, "override"

        time_mode = self._resolve_mode_from_time()
        if time_mode in MODE_SET:
            return time_mode, "time"

        work_ids = self._config.parse_ids(self._config.get("work_sessions", ""))
        rest_ids = self._config.parse_ids(self._config.get("rest_sessions", ""))

        for key in (session_id, umo):
            if key and key in work_ids:
                return MODE_WORK, "config"
        for key in (session_id, umo):
            if key and key in rest_ids:
                return MODE_REST, "config"

        default_mode = str(self._config.get("default_mode", MODE_REST)).strip().lower()
        if default_mode not in MODE_SET:
            default_mode = MODE_REST
        return default_mode, "default"

    def _resolve_mode_from_time(self) -> Optional[str]:
        if not self._config.get_bool("time_mode_enabled", True):
            return None

        now = self._config.now_in_timezone()
        work_days = self._config.parse_work_days(self._config.get("work_days", "1,2,3,4,5"))

        today = now.weekday() + 1
        if work_days and today not in work_days:
            return MODE_REST

        minute_now = now.hour * 60 + now.minute
        windows = self._config.parse_time_windows(self._config.get("work_time_windows", "09:00-18:00"))
        if not windows:
            return None

        for start_min, end_min in windows:
            if start_min <= end_min:
                if start_min <= minute_now <= end_min:
                    return MODE_WORK
            else:
                if minute_now >= start_min or minute_now <= end_min:
                    return MODE_WORK

        return MODE_REST

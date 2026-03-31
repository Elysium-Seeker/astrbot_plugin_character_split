from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Set, Tuple



class SplitConfig:
    def __init__(self, raw_config: Any):
        self._raw = raw_config or {}

    def get(self, key: str, default: Any) -> Any:
        raw = self._raw
        if isinstance(raw, dict):
            return raw.get(key, default)

        getter = getattr(raw, "get", None)
        if callable(getter):
            return getter(key, default)

        return default

    def get_bool(self, key: str, default: bool) -> bool:
        value = self.get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def get_int(self, key: str, default: int, minimum: int, maximum: int) -> int:
        value = self.get(key, default)
        try:
            num = int(value)
        except (TypeError, ValueError):
            num = default
        return max(minimum, min(maximum, num))

    def parse_ids(self, raw: Any) -> Set[str]:
        text = str(raw or "")
        normalized = text.replace(",", "\n").replace(";", "\n")
        result: Set[str] = set()
        for line in normalized.splitlines():
            v = line.strip()
            if v:
                result.add(v)
        return result

    def parse_work_days(self, raw: Any) -> Set[int]:
        text = str(raw or "")
        normalized = text.replace(";", ",").replace(" ", ",")
        values: Set[int] = set()
        for item in normalized.split(","):
            v = item.strip()
            if not v:
                continue
            try:
                day = int(v)
            except ValueError:
                continue
            if 1 <= day <= 7:
                values.add(day)
        return values

    def parse_time_windows(self, raw: Any) -> List[Tuple[int, int]]:
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

    def now_in_timezone(self) -> datetime:
        offset = self.get_int("timezone_offset_hours", 8, -12, 14)
        tz = timezone(timedelta(hours=offset))
        return datetime.now(tz)

    def current_time_desc(self) -> str:
        now = self.now_in_timezone()
        offset = self.get_int("timezone_offset_hours", 8, -12, 14)
        sign = "+" if offset >= 0 else ""
        return f"{now.strftime('%Y-%m-%d %H:%M:%S')} UTC{sign}{offset}"

    def _parse_hhmm(self, hhmm: str) -> Optional[int]:
        if ":" not in hhmm:
            return None
        hh, mm = hhmm.split(":", 1)
        try:
            h = int(hh)
            m = int(mm)
        except ValueError:
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m

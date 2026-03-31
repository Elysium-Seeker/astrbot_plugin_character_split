# pyright: reportMissingImports=false

from typing import Any

try:
    from astrbot.api import AstrBotConfig, logger
    from astrbot.api.event import AstrMessageEvent, filter
    from astrbot.api.provider import ProviderRequest
    from astrbot.api.star import Context, Star, register
except ImportError:  # pragma: no cover
    class _DummyLogger:
        def info(self, _msg: str):
            return None

        def warning(self, _msg: str):
            return None

        def error(self, _msg: str):
            return None

        def exception(self, _msg: str):
            return None

    logger = _DummyLogger()

    class _DummyCommandGroup:
        @staticmethod
        def command(*_args: Any, **_kwargs: Any):
            def _decorator(func: Any):
                return func

            return _decorator

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

        @staticmethod
        def command_group(*_args: Any, **_kwargs: Any):
            def _decorator(_func: Any):
                return _DummyCommandGroup()

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

    filter = _DummyFilter()
    AstrBotConfig = dict
    ProviderRequest = Any

try:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path
except ImportError:  # pragma: no cover
    get_astrbot_data_path = None

"""pyright: reportMissingImports=false"""

import importlib
from typing import Any

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

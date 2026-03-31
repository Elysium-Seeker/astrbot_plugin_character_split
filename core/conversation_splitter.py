import asyncio
import inspect
from typing import Any, Optional

from .state_store import StateStore


CONVERSATION_OP_TIMEOUT_SECONDS = 8.0


class ConversationSplitter:
    def __init__(self, state_store: StateStore, logger: Any):
        self._state_store = state_store
        self._logger = logger

    async def ensure_mode_conversation(
        self,
        context: Any,
        event: Any,
        mode: str,
        pre_switch_hook: Any = None,
    ) -> bool:
        conv_mgr = getattr(context, "conversation_manager", None)
        if conv_mgr is None:
            return False

        umo = getattr(event, "unified_msg_origin", "")
        if not umo:
            return False

        await self._state_store.ensure_state()
        target_cid = await self._state_store.get_mode_conversation_id(umo, mode)

        curr_cid: Optional[str] = None
        try:
            curr = await self._call_conversation_method(
                conv_mgr.get_curr_conversation_id,
                umo,
                timeout_seconds=CONVERSATION_OP_TIMEOUT_SECONDS,
            )
            curr_cid = str(curr) if curr else None
        except asyncio.TimeoutError:
            self._logger.warning("get_curr_conversation_id timed out")
        except Exception:
            curr_cid = None

        if target_cid:
            try:
                if curr_cid != target_cid:
                    await self._run_pre_switch_hook(pre_switch_hook)
                    await self._call_conversation_method(
                        conv_mgr.switch_conversation,
                        umo,
                        target_cid,
                        timeout_seconds=CONVERSATION_OP_TIMEOUT_SECONDS,
                    )
                    return True
                return False
            except Exception as exc:
                self._logger.warning(
                    f"switch_conversation to existing mode conversation failed: {exc}. "
                    "Will fallback to create a new mode conversation."
                )

        if curr_cid:
            await self._run_pre_switch_hook(pre_switch_hook)

        new_title = f"{mode}:{getattr(event, 'get_sender_name', lambda: 'user')()}"
        new_cid = await self._new_conversation(conv_mgr, umo, new_title)
        if not new_cid:
            return False

        try:
            await self._call_conversation_method(
                conv_mgr.switch_conversation,
                umo,
                new_cid,
                timeout_seconds=CONVERSATION_OP_TIMEOUT_SECONDS,
            )
            switched = True
        except Exception as exc:
            self._logger.warning(f"switch_conversation to new mode conversation failed: {exc}")
            switched = False

        await self._state_store.set_mode_conversation_id(umo, mode, new_cid)
        await self._state_store.save_state()
        return switched

    async def _run_pre_switch_hook(self, hook: Any):
        if hook is None:
            return
        try:
            result = hook()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            self._logger.warning(f"pre-switch hook failed: {exc}")

    async def _new_conversation(self, conv_mgr: Any, umo: str, title: str) -> Optional[str]:
        method = getattr(conv_mgr, "new_conversation", None)
        if not callable(method):
            self._logger.error("new_conversation method not found on conversation_manager")
            return None

        variants = [
            (tuple(), {"unified_msg_origin": umo, "title": title}),
            ((umo,), {"title": title}),
        ]

        last_exc: Optional[Exception] = None
        for args, kwargs in variants:
            if not self._supports_call(method, args, kwargs):
                continue
            try:
                result = await self._call_conversation_method(
                    method,
                    *args,
                    timeout_seconds=CONVERSATION_OP_TIMEOUT_SECONDS,
                    **kwargs,
                )
                if isinstance(result, str):
                    return result
                self._logger.warning("new_conversation returned unexpected result type, continuing")
                continue
            except asyncio.TimeoutError:
                self._logger.error("new_conversation timed out")
                return None
            except Exception as exc:
                last_exc = exc

        if last_exc is not None:
            self._logger.error(f"new_conversation failed: {last_exc}")
        else:
            self._logger.error("new_conversation did not match supported parameter signatures")
        return None

    def _supports_call(self, method: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
        try:
            signature = inspect.signature(method)
            signature.bind(*args, **kwargs)
            return True
        except TypeError:
            return False
        except ValueError:
            return True

    async def _call_conversation_method(
        self,
        method: Any,
        *args: Any,
        timeout_seconds: float,
        **kwargs: Any,
    ) -> Any:
        if inspect.iscoroutinefunction(method):
            return await asyncio.wait_for(method(*args, **kwargs), timeout=timeout_seconds)

        result = await asyncio.wait_for(asyncio.to_thread(method, *args, **kwargs), timeout=timeout_seconds)
        if inspect.isawaitable(result):
            return await asyncio.wait_for(result, timeout=timeout_seconds)
        return result

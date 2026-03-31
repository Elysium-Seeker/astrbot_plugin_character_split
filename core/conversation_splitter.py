from typing import Any, Optional

from .state_store import StateStore



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
    ):
        conv_mgr = getattr(context, "conversation_manager", None)
        if conv_mgr is None:
            return False

        umo = getattr(event, "unified_msg_origin", "")
        if not umo:
            return False

        await self._state_store.ensure_state()
        target_cid = self._state_store.get_mode_conversation_id(umo, mode)
        curr_cid: Optional[str] = None
        try:
            curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        except Exception:
            curr_cid = None

        if target_cid:
            try:
                if curr_cid != target_cid:
                    await self._run_pre_switch_hook(pre_switch_hook)
                    await conv_mgr.switch_conversation(umo, target_cid)
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
        if new_cid:
            try:
                await conv_mgr.switch_conversation(umo, new_cid)
                switched = True
            except Exception as exc:
                self._logger.warning(f"switch_conversation to new mode conversation failed: {exc}")
                switched = False
            self._state_store.set_mode_conversation_id(umo, mode, new_cid)
            await self._state_store.save_state()
            return switched
        return False

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

        result = None
        last_exc: Optional[Exception] = None

        try:
            result = method(unified_msg_origin=umo, title=title)
        except Exception as exc:
            last_exc = exc

        if result is None:
            try:
                result = method(umo, title=title)
            except Exception as exc:
                last_exc = exc

        if result is None and last_exc is not None:
            self._logger.error(f"new_conversation failed: {last_exc}")
            return None

        if hasattr(result, "__await__"):
            try:
                result = await result
            except Exception as exc:
                self._logger.error(f"new_conversation await failed: {exc}")
                return None

        if isinstance(result, str):
            return result

        self._logger.error("new_conversation returned unexpected result type")
        return None

# pyright: reportMissingImports=false

import asyncio
import json
import time
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
    from .core.memory_manager import MemoryManager
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
    from core.memory_manager import MemoryManager  # type: ignore

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.api.star import StarTools


@register("character_split", "Elysium-Seeker", "Split work/rest dialog and manage auto-memory", "1.2.2")
class CharacterSplitPlugin(Star):
    def __init__(self, context: Context, config: Optional[Dict[str, Any]] = None):
        super().__init__(context)
        self.config = config or {}

        self._split_config = SplitConfig(self.config)
        self._state_store = self._create_state_store()
        self._mode_resolver = ModeResolver(self._split_config, self._state_store)
        self._persona_builder = PersonaPromptBuilder(self._split_config)
        self._conversation_splitter = ConversationSplitter(self._state_store, logger)
        self._memory_manager = MemoryManager(StarTools.get_data_dir(), logger)

        self._runtime_state_lock = asyncio.Lock()
        self._mode_dirty_runtime: Dict[str, Dict[str, bool]] = {}
        self._autodream_runtime: Dict[str, Dict[str, Any]] = {}

    async def initialize(self):
        await self._state_store.ensure_state()

    async def terminate(self):
        await self._state_store.save_state()

    @filter.command_group("mode", desc="工作/休息模式控制台")
    def mode(self):
        """Mode command group"""

    @mode.command("help", desc="查看 mode 指令帮助面板")
    async def mode_help(self, event: AstrMessageEvent):
        yield event.plain_result(self._help_text())

    @mode.command("status", desc="查询当前生效模式及触发来源")
    async def mode_status(self, event: AstrMessageEvent):
        session_id, umo = self._get_session_identifiers(event)
        mode, source = await self._mode_resolver.resolve_mode(session_id, umo)

        layers = await self._memory_manager.get_layered_memories(umo, mode)
        mem_count = sum(len(items) for items in layers.values())

        text = (
            f"mode: {mode} ({source})\n"
            f"local_time: {self._split_config.current_time_desc()}\n"
            f"session_id: {session_id or '-'}\n"
            f"umo: {umo or '-'}\n"
            f"memories_attached: {mem_count}"
        )
        yield event.plain_result(text)

    @mode.command("work", desc="锁定当前会话为工作模式")
    async def mode_work(self, event: AstrMessageEvent):
        msg = await self._set_mode_override(event, "work")
        yield event.plain_result(msg)

    @mode.command("rest", desc="锁定当前会话为休息模式")
    async def mode_rest(self, event: AstrMessageEvent):
        msg = await self._set_mode_override(event, "rest")
        yield event.plain_result(msg)

    @mode.command("auto", desc="解除强制锁定，恢复时间规则自动调度")
    async def mode_auto(self, event: AstrMessageEvent):
        msg = await self._set_mode_override(event, "auto")
        yield event.plain_result(msg)

    @mode.command("set", desc="兼容旧版：参数填 work/rest/auto 快速锁定模式")
    async def mode_set(self, event: AstrMessageEvent, target: str = ""):
        target = (target or "").strip().lower()
        if target not in MODE_SET and target != "auto":
            yield event.plain_result("Usage: /mode set work|rest|auto")
            return

        msg = await self._set_mode_override(event, target)
        yield event.plain_result(msg)

    @filter.command_group("csmem", desc="独立多角色记忆管理系统")
    def csmem(self):
        """Memory management group"""

    @csmem.command("list", desc="按三层结构列出当前可用记忆")
    async def mem_list(self, event: AstrMessageEvent):
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

        decay_cfg = self._get_decay_config()
        layers = await self._memory_manager.get_layered_memories(
            umo,
            mode,
            global_limit=10,
            mode_limit=10,
            session_limit=10,
            **decay_cfg,
        )
        total = sum(len(items) for items in layers.values())

        if total == 0:
            yield event.plain_result(f"当前模式 [{mode}] 暂无可用记忆。")
            return

        scope_names = {
            "global": "Layer1-全局",
            "mode": f"Layer2-{mode}",
            "session": "Layer3-会话",
        }
        output = [f"[{mode}] 三层记忆总数: {total}"]
        for scope in ("global", "mode", "session"):
            items = layers.get(scope, [])
            output.append(f"\n[{scope_names[scope]}] ({len(items)})")
            if not items:
                output.append("- (空)")
                continue
            for m in items:
                imp = m.get("importance", 5)
                pid = m.get("period_id", 0)
                output.append(f"- #{m['id']} [⭐{imp}|P{pid}] {m['title']}: {m['content']}")

        yield event.plain_result("\n".join(output))

    @csmem.command("rm", desc="删除指定ID的记忆事实")
    async def mem_rm(self, event: AstrMessageEvent, mem_id: int):
        _, umo = self._get_session_identifiers(event)
        success = await self._memory_manager.remove_memory(umo, int(mem_id))
        if success:
            yield event.plain_result(f"已删除记录 #{mem_id}")
        else:
            yield event.plain_result(f"删除失败：未找到从属于你的记录 #{mem_id}")

    @csmem.command("clear", desc="清空当前会话记忆池")
    async def mem_clear(self, event: AstrMessageEvent):
        _, umo = self._get_session_identifiers(event)
        deleted = await self._memory_manager.clear_memories(umo)
        await self._state_store.clear_memory_injection_cursors(umo)
        await self._state_store.save_state()
        yield event.plain_result(f"已清空当前会话记忆池，共删除 {deleted} 条记忆。")

    @csmem.command("sync", desc="对当前会话历史立即进行记忆总结与提取")
    async def mem_sync(self, event: AstrMessageEvent):
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

        history = await self._read_current_conversation_history(umo)
        if not history or len(history) < 2:
            yield event.plain_result(f"当前模式 [{mode}] 对话历史过短，暂无需提取记忆。")
            return

        period_id = await self._state_store.ensure_mode_period(umo, mode)
        await self._state_store.save_state()

        summary_limits = self._get_summary_limits()
        result = await self._memory_manager.trigger_summary_and_save(
            self.context,
            umo,
            mode,
            history,
            history_limit=summary_limits["history_limit"],
            message_char_limit=summary_limits["message_char_limit"],
            total_char_limit=summary_limits["total_char_limit"],
            period_id=period_id,
            source="manual_sync",
        )
        yield event.plain_result(self._format_summary_result(mode, result, manual=True))

    @filter.command_group("autodream", desc="AutoDream 记忆池整理")
    def autodream(self):
        """AutoDream command group"""

    @autodream.command("status", desc="查看 AutoDream 状态")
    async def autodream_status(self, event: AstrMessageEvent):
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

        cfg = self._get_autodream_config()
        total = await self._memory_manager.get_memory_total(umo)

        async with self._runtime_state_lock:
            state = self._autodream_runtime.get(umo, {})
            running = bool(state.get("running", False))
            last_run = float(state.get("last_run", 0.0) or 0.0)
            last_result = state.get("last_result")

        if last_run > 0:
            age_sec = max(0, int(time.time() - last_run))
            last_run_desc = f"{age_sec}s ago"
        else:
            last_run_desc = "never"

        last_status = "-"
        if isinstance(last_result, dict):
            last_status = str(last_result.get("status", "-") or "-")

        text = (
            f"AutoDream enabled: {cfg['enabled']}\n"
            f"running: {running}\n"
            f"mode: {mode}\n"
            f"memory_total: {total}\n"
            f"threshold: {cfg['total_threshold']}\n"
            f"retain_count: {cfg['retain_count']}\n"
            f"source_limit: {cfg['source_limit']}\n"
            f"interval_seconds: {cfg['interval_seconds']}\n"
            f"last_run: {last_run_desc}\n"
            f"last_status: {last_status}"
        )
        yield event.plain_result(text)

    @autodream.command("run", desc="立即执行一次 AutoDream 整理")
    async def autodream_run(self, event: AstrMessageEvent):
        session_id, umo = self._get_session_identifiers(event)
        mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)
        cfg = self._get_autodream_config()

        async with self._runtime_state_lock:
            state = self._autodream_runtime.setdefault(
                umo,
                {"running": False, "last_run": 0.0, "last_result": None},
            )
            if state.get("running"):
                yield event.plain_result("AutoDream 正在运行中，请稍后再试。")
                return
            state["running"] = True

        started = time.time()
        result: Dict[str, Any] = {"status": "error"}
        try:
            result = await self._memory_manager.autodream_compact(
                context=self.context,
                umo=umo,
                mode=mode,
                retain_count=cfg["retain_count"],
                source_limit=cfg["source_limit"],
            )
        except Exception as exc:
            logger.warning(f"character_split manual autodream failed: {exc}")
            result = {"status": "error", "reason": str(exc)}
        finally:
            elapsed_ms = int((time.time() - started) * 1000)
            async with self._runtime_state_lock:
                state = self._autodream_runtime.setdefault(
                    umo,
                    {"running": False, "last_run": 0.0, "last_result": None},
                )
                state["running"] = False
                state["last_run"] = time.time()
                state["last_result"] = {**result, "elapsed_ms": elapsed_ms}

        yield event.plain_result(self._format_autodream_result(result, elapsed_ms, manual=True))

    @filter.on_llm_request(
        priority=100,
        desc="拦截 LLM 请求前置钩子：根据时间和用户配置判定工作状况并剥离上下文及注入分层记忆",
    )
    async def on_llm_request(self, event: AstrMessageEvent, req: ProviderRequest):
        try:
            session_id, umo = self._get_session_identifiers(event)
            mode, _ = await self._mode_resolver.resolve_mode(session_id, umo)

            switched, switch_meta = await self._sync_mode_conversation(event, mode, umo)

            if switched:
                conv_mgr = await self._get_conversation_manager()
                if conv_mgr:
                    try:
                        new_cid = await self._conversation_splitter._call_conversation_method(
                            conv_mgr.get_curr_conversation_id,
                            umo,
                            timeout_seconds=4.0,
                        )
                        if new_cid:
                            new_conv = await self._conversation_splitter._call_conversation_method(
                                conv_mgr.get_conversation,
                                umo,
                                new_cid,
                                timeout_seconds=4.0,
                            )
                            if new_conv:
                                req.conversation = getattr(new_conv, "inner", new_conv)
                                if hasattr(req.conversation, "history"):
                                    req.contexts = json.loads(req.conversation.history)
                    except Exception as exc:
                        logger.warning(f"character_split failed to sync req context: {exc}")

            self._mark_mode_dirty(umo, mode)
            await self._inject_mode_prompt(req, mode, umo, switched=switched, switch_meta=switch_meta)
            await self._maybe_schedule_autodream(umo, mode)
        except Exception:
            logger.exception("character_split on_llm_request failed")
            raise

    async def _sync_mode_conversation(
        self,
        event: AstrMessageEvent,
        mode: str,
        umo: str,
    ) -> Tuple[bool, Dict[str, Any]]:
        source_mode = await self._get_current_mode_from_conversation(umo)
        switch_meta: Dict[str, Any] = {
            "source_mode": source_mode,
            "source_period_id": 0,
            "target_period_id": 0,
            "target_prev_period_id": 0,
        }

        trigger_summary = False
        old_history: List[Dict[str, Any]] = []
        source_period_id = 0

        if source_mode and source_mode != mode:
            source_period_id = await self._state_store.ensure_mode_period(umo, source_mode)
            switch_meta["source_period_id"] = source_period_id

            skip_without_messages = self._split_config.get_bool("skip_checkpoint_without_messages", True)
            is_dirty = await self._is_mode_dirty(umo, source_mode)
            if not (skip_without_messages and not is_dirty):
                trigger_summary = True
                old_history = await self._read_current_conversation_history(umo)

        switched = await self._conversation_splitter.ensure_mode_conversation(
            self.context,
            event,
            mode,
            pre_switch_hook=None,
        )

        if switched:
            target_period_id = await self._state_store.bump_mode_period(umo, mode)
        else:
            target_period_id = await self._state_store.ensure_mode_period(umo, mode)

        switch_meta["target_period_id"] = target_period_id
        switch_meta["target_prev_period_id"] = max(0, int(target_period_id) - 1)
        await self._state_store.save_state()

        if switched and trigger_summary and old_history and source_mode:
            summary_limits = self._get_summary_limits()
            asyncio.create_task(
                self._run_switch_summary(
                    umo=umo,
                    source_mode=source_mode,
                    source_period_id=source_period_id,
                    old_history=old_history,
                    summary_limits=summary_limits,
                )
            )
            await self._clear_mode_dirty(umo, source_mode)

        return switched, switch_meta

    async def _run_switch_summary(
        self,
        umo: str,
        source_mode: str,
        source_period_id: int,
        old_history: List[Dict[str, Any]],
        summary_limits: Dict[str, Any],
    ):
        result = await self._memory_manager.trigger_summary_and_save(
            self.context,
            umo,
            source_mode,
            old_history,
            history_limit=summary_limits["history_limit"],
            message_char_limit=summary_limits["message_char_limit"],
            total_char_limit=summary_limits["total_char_limit"],
            period_id=max(0, int(source_period_id)),
            source="switch_auto",
        )
        logger.info(
            "[Memory] switch summary finished: "
            f"umo={umo} mode={source_mode} period={source_period_id} "
            f"status={result.get('status')} added={result.get('added', 0)}"
        )

    async def _inject_mode_prompt(
        self,
        req: ProviderRequest,
        mode: str,
        umo: str,
        switched: bool = False,
        switch_meta: Optional[Dict[str, Any]] = None,
    ):
        persona_limit = self._split_config.get_int("persona_prompt_char_limit", 480, 120, 3000)
        persona_prompt = self._truncate_text(self._persona_builder.build(mode), persona_limit)

        mem_str = ""
        if self._split_config.get_bool("inject_layered_memory", True):
            global_limit = self._split_config.get_int("prompt_global_memory_limit", 3, 0, 10)
            mode_limit = self._split_config.get_int("prompt_mode_memory_limit", 3, 0, 10)
            session_limit = self._split_config.get_int("prompt_session_memory_limit", 2, 0, 10)
            item_char_limit = self._split_config.get_int("prompt_memory_item_char_limit", 120, 40, 600)
            total_char_limit = self._split_config.get_int("prompt_memory_total_char_limit", 1200, 120, 8000)

            decay_cfg = self._get_decay_config()
            inject_cfg = self._get_injection_strategy_config()
            cursors = await self._state_store.get_memory_injection_cursors(umo, mode)

            layers: Dict[str, List[Dict[str, Any]]] = {"global": [], "mode": [], "session": []}

            if switched and inject_cfg["switch_period_priority"]:
                global_layers = await self._memory_manager.get_layered_memories(
                    umo,
                    mode,
                    global_limit=global_limit,
                    mode_limit=0,
                    session_limit=0,
                    **decay_cfg,
                )
                target_prev_period_id = 0
                if isinstance(switch_meta, dict):
                    target_prev_period_id = max(0, int(switch_meta.get("target_prev_period_id", 0) or 0))

                period_layers = await self._memory_manager.get_period_layered_memories(
                    umo,
                    mode,
                    period_id=target_prev_period_id,
                    mode_limit=mode_limit,
                    session_limit=session_limit,
                    include_bonus=inject_cfg["switch_bonus_limit"] > 0,
                    bonus_limit=inject_cfg["switch_bonus_limit"],
                    fallback_to_recent=inject_cfg["switch_period_fallback"],
                    **decay_cfg,
                )
                layers["global"] = global_layers.get("global", [])
                layers["mode"] = period_layers.get("mode", [])
                layers["session"] = period_layers.get("session", [])
            else:
                min_global_id = cursors.get("global", 0) if inject_cfg["delta_enabled"] else 0
                min_mode_id = cursors.get("mode", 0) if inject_cfg["delta_enabled"] else 0
                min_session_id = cursors.get("session", 0) if inject_cfg["delta_enabled"] else 0

                layers = await self._memory_manager.get_layered_memories(
                    umo,
                    mode,
                    global_limit=global_limit,
                    mode_limit=mode_limit,
                    session_limit=session_limit,
                    min_global_id=min_global_id,
                    min_mode_id=min_mode_id,
                    min_session_id=min_session_id,
                    surprise_probability=inject_cfg["surprise_probability"],
                    surprise_max_items=inject_cfg["surprise_max_items"],
                    **decay_cfg,
                )

            mem_blocks = [
                self._format_layer_block("Layer1 全局长期", layers.get("global", []), item_char_limit),
                self._format_layer_block(f"Layer2 {mode} 模式", layers.get("mode", []), item_char_limit),
                self._format_layer_block("Layer3 当前会话", layers.get("session", []), item_char_limit),
            ]
            mem_str = "\n\n".join(block for block in mem_blocks if block)
            mem_str = self._truncate_text(mem_str, total_char_limit)

            update_payload: Dict[str, int] = {}
            max_global_id = self._max_memory_id(layers.get("global", []))
            max_mode_id = self._max_memory_id(layers.get("mode", []))
            max_session_id = self._max_memory_id(layers.get("session", []))

            if max_global_id > 0:
                update_payload["global"] = max_global_id
            if max_mode_id > 0:
                update_payload["mode"] = max_mode_id
            if max_session_id > 0:
                update_payload["session"] = max_session_id

            if update_payload:
                await self._state_store.update_memory_injection_cursors(umo, mode, update_payload)
                await self._state_store.save_state()

                used_ids = [
                    item.get("id")
                    for layer_name in ("global", "mode", "session")
                    for item in layers.get(layer_name, [])
                    if item.get("id")
                ]
                await self._memory_manager.mark_memories_used(used_ids)

        old_prompt = getattr(req, "system_prompt", "") or ""
        mode_block = f"[Mode]\nCurrent mode: {mode}\n{persona_prompt}".strip()
        if mem_str:
            mode_block = f"{mode_block}\n\n{mem_str}".strip()

        if old_prompt.strip():
            req.system_prompt = f"{old_prompt.strip()}\n\n{mode_block}".strip()
        else:
            req.system_prompt = mode_block

    def _get_decay_config(self) -> Dict[str, Any]:
        return {
            "global_no_decay_min_importance": self._split_config.get_int(
                "global_no_decay_min_importance",
                9,
                1,
                10,
            ),
            "global_half_life_days": self._split_config.get_int("global_half_life_days", 180, 7, 3650),
            "mode_half_life_days": self._split_config.get_int("mode_half_life_days", 30, 1, 365),
            "session_half_life_days": self._split_config.get_int("session_half_life_days", 3, 1, 90),
            "low_importance_decay_boost": self._split_config.get_int(
                "low_importance_decay_boost_pct",
                100,
                0,
                500,
            )
            / 100.0,
        }

    def _get_injection_strategy_config(self) -> Dict[str, Any]:
        return {
            "delta_enabled": self._split_config.get_bool("memory_delta_injection_enabled", True),
            "switch_period_priority": self._split_config.get_bool("switch_period_priority_injection", True),
            "switch_period_fallback": self._split_config.get_bool("switch_period_fallback_to_recent", True),
            "switch_bonus_limit": self._split_config.get_int("switch_period_bonus_limit", 1, 0, 3),
            "surprise_probability": self._split_config.get_int(
                "memory_surprise_probability_percent",
                8,
                0,
                100,
            )
            / 100.0,
            "surprise_max_items": self._split_config.get_int("memory_surprise_max_items", 1, 0, 2),
        }

    def _get_autodream_config(self) -> Dict[str, Any]:
        return {
            "enabled": self._split_config.get_bool("autodream_enabled", True),
            "interval_seconds": self._split_config.get_int("autodream_interval_seconds", 900, 60, 86400),
            "total_threshold": self._split_config.get_int("autodream_total_threshold", 120, 10, 5000),
            "retain_count": self._split_config.get_int("autodream_retain_count", 60, 5, 500),
            "source_limit": self._split_config.get_int("autodream_source_limit", 180, 20, 3000),
        }

    async def _maybe_schedule_autodream(self, umo: str, mode: str):
        cfg = self._get_autodream_config()
        if not cfg["enabled"] or not umo:
            return

        now = time.time()
        should_run = False
        async with self._runtime_state_lock:
            state = self._autodream_runtime.setdefault(
                umo,
                {"running": False, "last_run": 0.0, "last_result": None},
            )
            if state.get("running"):
                return

            last_run = float(state.get("last_run", 0.0) or 0.0)
            if now - last_run < cfg["interval_seconds"]:
                return

            state["running"] = True
            should_run = True

        if should_run:
            asyncio.create_task(self._run_autodream_job(umo, mode, cfg))

    async def _run_autodream_job(self, umo: str, mode: str, cfg: Dict[str, Any]):
        started = time.time()
        result: Dict[str, Any] = {"status": "error"}

        try:
            result = await self._memory_manager.run_compaction_if_needed(
                context=self.context,
                umo=umo,
                mode=mode,
                enabled=cfg["enabled"],
                total_threshold=cfg["total_threshold"],
                retain_count=cfg["retain_count"],
                source_limit=cfg["source_limit"],
            )
        except Exception as exc:
            logger.warning(f"character_split autodream job failed: {exc}")
            result = {"status": "error", "reason": str(exc)}
        finally:
            elapsed_ms = int((time.time() - started) * 1000)
            async with self._runtime_state_lock:
                state = self._autodream_runtime.setdefault(
                    umo,
                    {"running": False, "last_run": 0.0, "last_result": None},
                )
                state["running"] = False
                state["last_run"] = time.time()
                state["last_result"] = {**result, "elapsed_ms": elapsed_ms}

            logger.info(
                "[AutoDream] background run finished: "
                f"umo={umo} mode={mode} status={result.get('status')} "
                f"before={result.get('before')} after={result.get('after')} elapsed_ms={elapsed_ms}"
            )

    def _format_summary_result(self, mode: str, result: Dict[str, Any], manual: bool = False) -> str:
        status = str(result.get("status", "unknown"))
        added = int(result.get("added", 0) or 0)
        parsed = int(result.get("parsed", 0) or 0)
        skipped_exists = int(result.get("skipped_exists", 0) or 0)

        prefix = "手动提取" if manual else "自动提取"
        if status in {"ok", "no_new"}:
            return (
                f"{prefix}完成 [{mode}]\n"
                f"status: {status}\n"
                f"parsed: {parsed}\n"
                f"added: {added}\n"
                f"skipped_exists: {skipped_exists}"
            )
        if status == "history_too_short":
            return f"{prefix}跳过 [{mode}]：历史文本过短。"
        if status == "no_provider":
            return f"{prefix}失败 [{mode}]：未找到可用模型提供者。"
        if status == "bad_json":
            return f"{prefix}失败 [{mode}]：模型输出不是合法 JSON。"
        return f"{prefix}结束 [{mode}]：status={status}"

    @staticmethod
    def _format_autodream_result(result: Dict[str, Any], elapsed_ms: int, manual: bool = False) -> str:
        status = str(result.get("status", "unknown"))
        before = result.get("before", "-")
        after = result.get("after", "-")
        retained = result.get("retained", "-")
        prefix = "手动 AutoDream" if manual else "自动 AutoDream"

        return (
            f"{prefix}完成\n"
            f"status: {status}\n"
            f"before: {before}\n"
            f"after: {after}\n"
            f"retained: {retained}\n"
            f"elapsed_ms: {elapsed_ms}"
        )

    def _format_layer_block(self, title: str, memories: Any, item_char_limit: int) -> str:
        if not memories:
            return ""

        safe_item_chars = max(40, int(item_char_limit))
        title_chars = max(16, safe_item_chars // 3)
        content_chars = max(24, safe_item_chars - title_chars - 2)

        lines = [f"[{title}]"]
        for mem in memories:
            raw_title = self._normalize_inline_text(str(mem.get("title", "")))
            raw_content = self._normalize_inline_text(str(mem.get("content", "")))
            mem_title = self._truncate_text(raw_title, title_chars)
            mem_content = self._truncate_text(raw_content, content_chars)

            if not mem_title and not mem_content:
                continue
            if mem_title and mem_content:
                lines.append(f"- {mem_title}: {mem_content}")
            elif mem_content:
                lines.append(f"- {mem_content}")
            else:
                lines.append(f"- {mem_title}")

        return "\n".join(lines) if len(lines) > 1 else ""

    def _get_summary_limits(self) -> Dict[str, Any]:
        history_limit_value = self._split_config.get_int("summary_history_limit", 28, 0, 200)
        return {
            "history_limit": None if history_limit_value == 0 else history_limit_value,
            "message_char_limit": self._split_config.get_int("summary_message_char_limit", 220, 60, 1200),
            "total_char_limit": self._split_config.get_int("summary_total_char_limit", 4800, 600, 20000),
        }

    async def _read_current_conversation_history(self, umo: str) -> List[Dict[str, Any]]:
        conv_mgr = await self._get_conversation_manager()
        history: List[Dict[str, Any]] = []
        if not conv_mgr:
            return history

        try:
            cid = await self._conversation_splitter._call_conversation_method(
                conv_mgr.get_curr_conversation_id,
                umo,
                timeout_seconds=4.0,
            )
            if not cid:
                return history

            conv = await self._conversation_splitter._call_conversation_method(
                conv_mgr.get_conversation,
                umo,
                cid,
                timeout_seconds=4.0,
            )
            if conv and hasattr(conv, "history"):
                history = json.loads(conv.history)
        except Exception as exc:
            logger.warning(f"character_split failed to read current history: {exc}")
        return history

    @staticmethod
    def _max_memory_id(memories: List[Dict[str, Any]]) -> int:
        max_id = 0
        for item in memories or []:
            try:
                max_id = max(max_id, int(item.get("id", 0)))
            except (TypeError, ValueError):
                continue
        return max_id

    @staticmethod
    def _normalize_inline_text(text: str) -> str:
        return " ".join((text or "").strip().split())

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        cleaned = (text or "").strip()
        if max_chars <= 0 or len(cleaned) <= max_chars:
            return cleaned
        if max_chars <= 3:
            return cleaned[:max_chars]
        return cleaned[: max_chars - 3].rstrip() + "..."

    async def _get_conversation_manager(self):
        return getattr(self.context, "conversation_manager", None)

    def _mark_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        state = self._mode_dirty_runtime.setdefault(umo, {})
        state[mode] = True

    async def _clear_mode_dirty(self, umo: str, mode: str):
        if not umo or mode not in MODE_SET:
            return
        state = self._mode_dirty_runtime.setdefault(umo, {})
        state[mode] = False

    async def _is_mode_dirty(self, umo: str, mode: str) -> bool:
        if not umo or mode not in MODE_SET:
            return False
        state = self._mode_dirty_runtime.get(umo, {})
        return bool(state.get(mode, False))

    async def _get_current_mode_from_conversation(self, umo: str) -> Optional[str]:
        if not umo:
            return None

        conv_mgr = await self._get_conversation_manager()
        if conv_mgr is None:
            return None

        try:
            curr_cid = await self._conversation_splitter._call_conversation_method(
                conv_mgr.get_curr_conversation_id,
                umo,
                timeout_seconds=4.0,
            )
        except Exception:
            return None

        if not curr_cid:
            return None

        await self._state_store.ensure_state()
        work_cid = await self._state_store.get_mode_conversation_id(umo, "work")
        rest_cid = await self._state_store.get_mode_conversation_id(umo, "rest")
        if curr_cid == work_cid:
            return "work"
        if curr_cid == rest_cid:
            return "rest"
        return None

    def _create_state_store(self) -> StateStore:
        return StateStore(
            plugin_name=str(getattr(self, "name", PLUGIN_NAME) or PLUGIN_NAME),
            state_kv_key=STATE_KV_KEY,
            logger=logger,
            get_data_path_func=StarTools.get_data_dir,
            get_kv_data_func=getattr(self, "get_kv_data", None),
            put_kv_data_func=getattr(self, "put_kv_data", None),
        )

    async def _set_mode_override(self, event: AstrMessageEvent, target: str) -> str:
        session_id, umo = self._get_session_identifiers(event)
        key = session_id or umo
        if not key:
            return "Cannot determine current session key."

        await self._state_store.ensure_state()
        if target == "auto":
            await self._state_store.clear_session_override(key)
            await self._state_store.save_state()
            return "Session mode override cleared."

        if target not in MODE_SET:
            return "Usage: /mode set work|rest|auto"

        await self._state_store.set_session_override(key, target)
        await self._state_store.save_state()
        return f"Session override set to: {target}"

    @staticmethod
    def _get_session_identifiers(event: AstrMessageEvent) -> Tuple[str, str]:
        session_id = ""
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            session_id = str(getattr(message_obj, "session_id", "") or "")
        return session_id, umo

    def _help_text(self) -> str:
        return (
            "Character Split Commands:\n"
            "----- 模式控制 -----\n"
            "/mode help - 帮助面板\n"
            "/mode status - 当前状态及记忆数\n"
            "/mode work - 锁定为工作模式\n"
            "/mode rest - 锁定为休息模式\n"
            "/mode auto - 解除锁定恢复自动\n"
            "/mode set work|rest|auto\n"
            "----- 记忆管理 -----\n"
            "/csmem list - 查看三层记忆\n"
            "/csmem rm <id> - 删除指定记忆\n"
            "/csmem clear - 清空当前会话记忆池\n"
            "/csmem sync - 手动触发三层记忆提取\n"
            "----- AutoDream -----\n"
            "/autodream status - 查看自动整理状态\n"
            "/autodream run - 立即执行一次整理\n"
        )

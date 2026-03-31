# astrbot_plugin_character_split

工作/休息人格分流插件（时间驱动模式）。

定位很单一：

- 只负责把同一会话分成 work / rest 两条对话上下文
- 只负责注入“同一人格核心 + 模式增强”提示词
- 不负责长期记忆写入或检索

长期记忆统一由 `astrbot_plugin_mnemosyne` 处理。

## 工程结构

- `main.py`: 插件薄入口（命令、钩子、模块编排）
- `runtime.py`: AstrBot 运行时导入与无依赖 fallback
- `core/config.py`: 配置读取与时间解析
- `core/state_store.py`: 状态持久化（override + 会话映射）
- `core/mode_resolver.py`: 模式判定（override > time > whitelist > default）
- `core/persona_prompt.py`: 人格提示词拼接（核心人格 + 模式增强）
- `core/conversation_splitter.py`: work/rest 对话切换与创建

## 实际行为

1. 对话分流
- 每次 `on_llm_request` 先判定模式（work/rest），再切到对应 conversation。
- 同一会话会维护两条独立对话：`work` 和 `rest`。

2. 模式判定（默认按时间）
- 判定优先级：手动覆盖 > 时间规则 > 会话白名单 > default_mode。
- 时间规则由工作日 + 工作时间窗决定，默认 `周一到周五` + `09:00-18:00`。
- 不在工作日或工作时间窗内时，自动进入 rest。

3. 人格差异（同一人设）
- `core_persona_prompt`：定义“同一个人”的核心身份与价值观（work/rest 共用）。
- work 增强：偏任务分解、优先级、风险识别、执行建议。
- rest 增强：偏人性化表达、情绪支持、轻松交流。
- 两侧能力和语气有差异，但身份连续。

4. 记忆后端
- 本插件不维护本地长期记忆。
- 推荐并默认与 mnemosyne 搭配，记忆统一由 mnemosyne 注入。

5. 切模式前 checkpoint（best-effort）
- 当 work/rest 会话发生切换时，插件会先尝试触发 mnemosyne 一次即时 checkpoint。
- 默认只在“被切走模式有新消息”时触发；若该时段没有消息，会自动跳过。
- 这是“尽力触发”，失败不会中断对话切换流程。

6. 切模式后强制 recall（best-effort）
- 仅在真的发生会话切换时，插件会再尝试触发一次 mnemosyne memory 读取/注入。
- 目的是避免模式切换后仍沿用旧上下文缓存，降低 work/rest 串线概率。
- 这是“尽力触发”，失败只告警，不阻断本次请求。

7. 后端不可用时的降级
- 若 mnemosyne 未加载或不可用，插件会打 warning 日志，并默认关闭 work/rest 分流。
- 此时回退为单会话，优先保证上下文连续性，避免对话被拆散。

## 指令

- `/mode help` 查看指令帮助
- `/mode status` 查看当前模式与会话标识
- `/mode work` 当前会话固定为工作模式
- `/mode rest` 当前会话固定为休息模式
- `/mode auto` 清除手动覆盖，回到自动判定
- `/mode set work|rest|auto` 兼容旧用法

## 配置项（WebUI）

- `time_mode_enabled`: 是否启用时间判定（默认 true）
- `timezone_offset_hours`: 时区偏移（默认 8）
- `work_days`: 工作日（1=周一，7=周日，默认 `1,2,3,4,5`）
- `work_time_windows`: 工作时间窗（支持多个区间，默认 `09:00-18:00`）
- `default_mode`: 兜底模式（时间规则和白名单都未命中时）
- `work_sessions`: 工作模式白名单（时间规则之后的补充分流）
- `rest_sessions`: 休息模式白名单（时间规则之后的补充分流）
- `flush_mnemosyne_on_mode_switch`: 切模式前是否尝试触发一次 mnemosyne checkpoint（默认 true）
- `require_mnemosyne_for_split`: 是否要求 mnemosyne 可用才开启分流（默认 true）
- `force_mnemosyne_recall_on_mode_switch`: 切模式后是否尝试强制触发一次 mnemosyne 读取（默认 true）
- `skip_checkpoint_without_messages`: 被切走模式在该时段没有新消息时，是否跳过 checkpoint（默认 true）
- `core_persona_prompt`: 同一人格核心设定
- `work_persona_prompt`: 工作模式增强提示词
- `rest_persona_prompt`: 休息模式增强提示词

## 时间配置示例

1. 标准上班时段
- `work_days = 1,2,3,4,5`
- `work_time_windows = 09:00-18:00`

2. 午休拆分
- `work_time_windows = 09:00-12:00,13:30-18:00`

3. 夜班（跨天）
- `work_time_windows = 22:00-02:00`

## 与 mnemosyne 推荐联动

推荐参数：

1. 共享 work/rest 记忆池
- `use_personality_filtering = false`

2. 会话隔离
- `use_session_filtering = true`

3. 群聊防串线（可选）
- `use_participant_filtering = true`

4. 注入方式
- `memory_injection_method = user_prompt`

5. 召回数量
- `top_k = 3~5`

## 使用检查清单

1. 在 mnemosyne 里执行 `/memory init`
2. 用 `/memory get_session_id` 确认会话 ID
3. 在本插件执行 `/mode status`，确认模式与会话标识

## 本地测试建议

1. 先把 `work_time_windows` 设成当前时间命中的区间，再执行 `/mode status`，确认返回 `mode: work (time)`。
2. 再改成不命中当前时间的区间，执行 `/mode status`，确认返回 `mode: rest (time)`。
3. 执行 `/mode work`，确认返回覆盖生效，并再次 `/mode status` 显示 `override`。
4. 执行 `/mode auto` 清除覆盖，确认回到时间判定。
5. 连续在 work/rest 两种模式对话，观察上下文隔离是否生效，同时记忆召回仍由 mnemosyne 统一提供。

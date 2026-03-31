# astrbot_plugin_character_split

✨ 智能人格分流插件 ✨

[License](https://opensource.org/licenses/MIT) [Python 3.10+](https://www.python.org/) [AstrBot](https://github.com/Soulter/AstrBot)

## 📖 介绍

工作与休息模式分离对话，并内置三层记忆管理的智能人格切换插件。

只专注一件事：**根据时间、会话类型自动切换人格与独立的对话上下文，让 AI Bot 更像真实的伴侣 / 同事。**

主要特性：
- **上下文分流**：根据当前模式（工作 / 休息）在同一群聊/私聊中开辟两段独立对话上下文，工作时不闲聊，休息时不谈工作。
- **动态 Prompt 增强**：“核心人格 + 模式增量人格”，同一身份在不同环境展现不同侧面。
- **内置三层记忆**：支持 Layer1(全局偏好) / Layer2(模式规则) / Layer3(会话上下文) 的提取与注入。

## 🆕 最近更新

- v1.1.4
   - 重构本地记忆系统为三层结构（global/mode/session）。
   - 修复主流程中错误 await 同步函数导致的潜在运行时异常。
   - `/csmem list` 改为按三层分组展示，提示词注入改为分层注入。

## 💿 安装

1. 直接在 AstrBot 的插件市场搜索 `astrbot_plugin_character_split`，点击安装，等待完成即可。
2. 或使用命令行安装：`/plugin install https://github.com/yourname/astrbot_plugin_character_split`

## ⚙️ 配置

请在 AstrBot 的插件 WebUI 配置面板查看并修改，支持的配置项：

- 时区与时间窗口：工作日选择、明确的工作时间段（支持跨天）。
- 强制分流名单：将特定会话强制绑定为工作/休息。
- 增强提示词：自定义你的 Work / Rest / Core 提示词片段。
- 记忆联动相关参数及防抖跳跃等高阶配置。

## 🎉 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/mode help` | 所有人 | 查看 mode 指令帮助 |
| `/mode status` | 所有人 | 查看当前模式与判定来源（时间/配置/覆写） |
| `/mode work` | 所有人 | 当前会话覆盖强制为工作模式 |
| `/mode rest` | 所有人 | 当前会话覆盖强制为休息模式 |
| `/mode auto` | 所有人 | 清除历史手动覆写状态，恢复自动时间判定 |
| `/mode set work\|rest\|auto` | 所有人 | 兼容旧版用法 |
| `/csmem list` | 所有人 | 查看当前模式下的三层记忆 |
| `/csmem rm <id>` | 所有人 | 删除指定记忆 |
| `/csmem sync` | 所有人 | 手动触发当前会话记忆提取 |

## 🧠 插件工作流程

每一条发送给 LLM 的请求（LLM Request）经过此插件的流转过程：

1. **会话鉴权与解析**：获取当前 session_id / umo（通用消息来源）。
2. **模式判定解析器 (Mode Resolver)**：
   - 覆写判定 (Override)：用户是否通过指令强制指定了当次模式？
   - 时间判定 (Time)：当前时间是否在工作日的工作时间窗内？
   - 黑白名单 (Whitelist)：会话是否配置为纯工作或纯休息？
   - 降级回落 (Default)：回落至配置的默认模式。
3. **上下文切换与记忆联动**：
   - 根据判定结果确认会话归属。若跨越模式边界，优先触发 `mnemosyne` 的归档存储（Checkpoint）。
   - 载入并关联新模式的上下文 ID，并触发记忆提取（Recall）。
4. **提示词增强合成**：
   - 读取 Core Prompt（稳定身份与价值观）。
   - 根据当前模式叠加 Work/Rest Prompt 增强补丁。
   - 动态合并至发往 LLM 的 System Prompt。

## 🧩 内部结构

本项目为高内聚设计：
- `main.py`: 插件薄入口（命令分配、生命周期钩子、模块编排）。
- `runtime.py`: AstrBot 运行时导入与无感 fallback。
- `core/config.py`: 配置读取与时区时间智能解析。
- `core/state_store.py`: K/V 与文件双机制状态持久化。
- `core/mode_resolver.py`: 状态机分层判定核心。
- `core/persona_prompt.py`: 增量式人格聚合工厂。
- `core/conversation_splitter.py`: 负责处理会话轨道的剥离与并线。

## 🎉 致谢

感谢 [AstrBot](https://github.com/Soulter/AstrBot) 提供高度可扩展的框架底座。
如果你觉得这个插件好用，欢迎点亮 Star 以示支持！🌟

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
- 本插件内置本地三层记忆：
   - Layer1 (global): 跨模式长期偏好/身份信息。
   - Layer2 (mode): 工作或休息模式下的规则和长期上下文。
   - Layer3 (session): 当前任务相关的短期上下文。
- 在每次请求前，会按层级把记忆注入到 System Prompt，优先保证全局稳定性和模式一致性。

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

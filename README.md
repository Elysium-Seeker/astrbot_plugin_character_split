<div align="center">
  <img src="https://count.getloli.com/@astrbot_plugin_character_split?name=astrbot_plugin_character_split&theme=booru-helltaker&padding=6&offset=0&align=top&scale=1&pixelated=1&darkmode=auto" />
</div>

<h1 align="center">astrbot_plugin_character_split</h1>

<div align="center">
  ✨ <i>人格分流插件</i> ✨
</div>

<p align="center">
  <a href="https://opensource.org/licenses/MIT"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License"></a>
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python"></a>
  <a href="https://github.com/Soulter/AstrBot"><img src="https://img.shields.io/badge/AstrBot-4.9.2%2B-eb4d4b.svg" alt="AstrBot"></a>
  <a href="https://github.com/Elysium-Seeker/astrbot_plugin_character_split"><img src="https://img.shields.io/badge/作者-Elysium--Seeker-blue.svg" alt="GitHub"></a>
</p>

## 📖 介绍

一个人格分流插件，它的核心功能是**把群聊/私聊的对话按时间拆分成“工作(Work)”与“休息(Rest)”两个独立上下文**。
这样可以让 Bot 在工作时间专心处理正事，下班后自动切换到闲聊状态，做到工作生活互不干扰。

**🆕 V1.1.0 新特性**：完全移除了外部依赖！内置轻量级 SQLite 实现类似 Claude-Mem 的记忆系统。无需依赖任何长期记忆插件即可使用完整的模式独立记忆隔离设计！
**🆕 V1.1.2 增强**：记忆系统现已支持打分（importance）层级，自动高亮提取强设定记忆，并在对话注入时优先保障高价值记忆的留存。

核心机制：
- **上下文双轨制**：在单一会话里维护 Work 和 Rest 两条消息轨道，聊天记录物理隔离。
- **Prompt 动态拼接**：系统 Prompt 自动组装为 `Core 基础人设` + `当前模式的增强人设`。
- **内置记忆系统**：独立设计本地 SQLite 无依赖记忆库，利用 1-10 重要性打分机制分级，在后台静默提取、存档长效记忆点，并在触发对话时动态检索高价值记忆点给对应人格（完全不增加回答延迟）。

## 💿 安装

1. 在 AstrBot 插件市场中搜索 `astrbot_plugin_character_split` 安装。
2. 或在终端执行：`/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split`

## ⚙️ 配置

可在 AstrBot 的 WebUI 配置面板进行调整：
- **时区与时间窗**：支持配置工作日（1-7）、时区及具体的工作时间段（支持如 `09:00-12:00,13:30-18:00` 大跨度拼接，也支持跨天如 `22:00-02:00`）。
- **黑白名单**：可强制将某些 `session_id` 永远锁定在特定模式。
- **提示词组**：独立配置 Core（全天通用性格）、Work（工作表现倾向）、Rest（生活闲适倾向）三段 Prompt。
- **记忆联动开关**：切换前后的自动存档与提取行为可根据需要开启或跳过。

## 🎉 指令

| 指令 | 权限 | 说明 |
| --- | --- | --- |
| `/mode help` | 所有人 | 查看指令列表 |
| `/mode status` | 所有人 | 查询当前所处模式及其判定来源（比如是被时间触发还是被覆写触发） |
| `/mode work` | 所有人 | 将当前会话强制切到工作模式 |
| `/mode rest` | 所有人 | 将当前会话强制切到休息模式 |
| `/mode auto` | 所有人 | 解除强制指令锁定，恢复时间自动调度 |
| `/mode set [work|rest|auto]` | 所有人 | `/mode` 的快捷写法 |
| `/csmem list` | 管理员 | 查看当前会话的记忆片段列表 |
| `/csmem rm <id>` | 管理员 | 删除指定的记忆片段 |
| `/csmem sync` | 所有人 | 立即对已有对话进行一次历史总结和记忆提取 |

## 🧠 工作流说明

每次接收到 LLM 对话请求时，插件的介入流程：
1. **模式判定**：按严格的优先级顺序（手动指令覆盖 > 分时时间窗规则 > 黑白名单 > 缺省值）确认当前应处于哪种模式。
2. **记忆对接**：如果发生模式切换，插件会异步调用大模型进行对话总结提取，并写入到自带的本地 SQLite 记忆数据库。并在注入对话前查询相关记忆点。
3. **注入上下文**：分配并切换到对应的内部对话轨道，并在最终请求内部强插组装完毕的新 System Prompt 和内置总结出的长效记忆点。

## 🧩 项目结构

- `main.py`: 插件入口，命令监听编排与钩子注册。
- `runtime.py`: 对 AstrBot API 的降级兼容封装层。
- `core/config.py`: WebUI 配置读取及灵活的 Time 解析器。
- `core/state_store.py`: 基于 Kv 存储与本地 json 文件的双路状态持久化。
- `core/mode_resolver.py`: 负责串联优先级的多层判定器。
- `core/persona_prompt.py`: 提示词字符串合并工厂。
- `core/conversation_splitter.py`: 用于处理底层会话的多轨剥离与并线。

## 🎉 致谢

依托于 [AstrBot](https://github.com/Soulter/AstrBot) 扩展机制开发。
如果这正好是你想要的，请顺手点一个 Star ⭐
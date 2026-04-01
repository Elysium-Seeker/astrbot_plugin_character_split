<div align="center">

# AstrBot Plugin Character Split

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-Support-brightgreen.svg)](https://github.com/Soulter/AstrBot)

<img src="https://count.getloli.com/get/@astrbot-plugin-character-split?theme=booru-helltaker" alt="Moe Counter">

专为群聊与私聊设计的上下文隔离与多重人格记忆管理插件。

</div>

## 🆕 更新日志

### v1.2.0
- 新增 `/autodream` 功能：支持按间隔定期检查记忆池，当记忆总量超出阈值时自动触发重整并保留核心内容。
- 新增 `/autodream status` 与 `/autodream run` 指令，用于查看整理状态及手动触发重整。

### v1.1.9
- 优化记忆总结触发逻辑：对话少于 2 条时不强制跳过，交由模型自行判断是否需要沉淀。
- 优化 `/csmem sync` 逻辑：取消最近 40 条的截断限制，改用当前会话全量历史进行总结。

### v1.1.8
- 修复插件加载时 data 目录解析失败导致的启动报错，增加多路径兼容与后备机制。
- 修复状态存储调用中的异步响应问题，避免会话模式下状态读写异常。

### v1.1.7
- 精简部分文档说明，提升内容可读性。

### v1.1.6
- 应用居中排版模板与 Shields UI 徽章，并新增 `booru-helltaker` 主题的统计计数器。

### v1.1.5 & v1.1.4
- 全面优化文案说明与指令描述。
- 重构底层存储，引入纯本地三层记忆架构（Layer 1 全局 / Layer 2 模式 / Layer 3 会话）。

## 🌟 核心特性

- **自动模式分流**：支持按时间段（含跨天）自动切换工作与休息模式。同一会话内开辟独立上下文，确保对话内容互不干扰。
- **动态人设加载**：支持配置核心 (Core)、工作 (Work) 及休息 (Rest) 三组提示词 (Prompt)，并根据当前模式自动组合生效。
- **内置三层记忆**：采用类 Claude-Mem 架构，纯本地 SQLite 存储，无外部依赖：
  - **Layer 1 (全局)**：持久存储长期偏好与核心特征。
  - **Layer 2 (模式)**：存储特定模式下的行为准则与设定。
  - **Layer 3 (会话)**：记录当前跟进的短期任务与上下文。
  - 会话在触发模式切换或达到长度阈值时，将于后台自动执行总结、分类与存储，且不增加回复延迟。

## 💿 安装

1. 在 AstrBot 的插件市场中搜索 `astrbot_plugin_character_split` 并点击安装。
2. 或通过终端指令安装：`/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split`

## ⚙️ 配置说明

请进入 AstrBot WebUI 的插件配置页面进行设置：
1. **时间窗**：支持配置多个生效区间（如 `09:00-12:00,13:30-18:00`）及跨夜区间（如 `22:00-02:00`）。
2. **白名单**：指定特定群组或私聊固定生效工作/休息模式。
3. **提示词设定**：配置 Core / Work / Rest 三组提示词，以在不同模式下体现不同的人设行为。
4. **AutoDream 参数**：通过 `autodream_interval_seconds`、`autodream_total_threshold`、`autodream_retain_count` 及 `autodream_source_limit` 参数控制自动整理的频率与强度。

## 🎉 常用指令

| 指令 | 说明 |
| --- | --- |
| `/mode help` | 查看模式模块的指令帮助 |
| `/mode status` | 查看当前所处模式及判定原因 |
| `/mode work` | 强制当前会话切换至工作模式 |
| `/mode rest` | 强制当前会话切换至休息模式 |
| `/mode auto` | 取消模式锁定，恢复按时间自动切换 |
| `/csmem list` | 查看当前环境的三层记忆池内容 |
| `/csmem rm <id>` | 根据指定 ID 删除特定记忆 |
| `/csmem sync` | 手动提取并保存当前会话记录至记忆池 |
| `/autodream help` | 查看 AutoDream 模块的指令帮助 |
| `/autodream status` | 查看自动整理状态、阈值设置及当前记忆存量 |
| `/autodream run` | 手动触发一次记忆池重整，压缩并保留核心内容 |

*(插件向下兼容部分旧版本指令写法，如 `/mode set auto`。)*
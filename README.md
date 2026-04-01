<div align="center">

# AstrBot Plugin Character Split

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-Support-brightgreen.svg)](https://github.com/Soulter/AstrBot)

<img src="https://count.getloli.com/get/@astrbot-plugin-character-split?theme=booru-helltaker" alt="Moe Counter">

专门给群聊/私聊做上下文隔离的 **人格与记忆多开插件**。

</div>

## 🆕 更新日志

### v1.2.0
- 新增 `/autodream` 能力：按间隔检查记忆池，当记忆总量过高时自动重整并保留重要内容。
- 新增 `/autodream status` 与 `/autodream run`，可查看状态并手动触发重整。

### v1.1.9
- 调整记忆总结触发条件：对话少于 2 条时不再直接跳过，改为交给模型自行判断是否沉淀。
- `/csmem sync` 改为使用当前会话全量历史进行总结，不再截断为最近 40 条。

### v1.1.8
- 修复插件加载时 data 目录解析失败导致的启动报错，增加多路径兼容与 fallback。
- 修复状态存储调用中的异步 await 问题，避免会话模式状态读写异常。

### v1.1.7
- 移除了部分不必要的文档说明，以更加精简的内容呈现。

### v1.1.6
- 套用用户偏好的大字居中模板、Shields UI 徽章，并加入了 `booru-helltaker` 主题的 Moe Counter。

### v1.1.5 & v1.1.4
- 彻底用通俗人话重写所有文案说明与指令描述。
- 重构底层存储，引入纯本地三层记忆（Layer 1 全局 / Layer 2 模式 / Layer 3 会话）。

## 🌟 核心特性

- **自动分流**：到点上班，到点下班（支持跨天设定）。同一会话自动开辟 Work/Rest 两个独立上下文，坚决不串台。
- **动态性格**：支持配置 Core（底色性格）+ Work（打工态）+ Rest（摸鱼态）三段 Prompt，在对应模式下自动拼装。
- **内置三层记忆**：仿 Claude-Mem 架构，纯本地 SQLite，无外部依赖：
  - **Layer 1 (全局)**：你的长期偏好特征雷打不动。
  - **Layer 2 (模式)**：不同模式下专属的规矩（比如工作需用 Python 3.10）。
  - **Layer 3 (会话)**：你当前正在跟进的短期任务。
  - 触发跨模式或长对话时，全自动在后台做总结、分类打分并落库，回复时不增加任何查询延迟。

## 💿 安装

1. 直接在 AstrBot 的插件市场搜索 `astrbot_plugin_character_split`，点击安装。
2. 或直接终端安装：`/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split`

## ⚙️ 配置说明

直接进 AstrBot WebUI 改就完事了：
1. **时间窗**：支持多个区间（如 `09:00-12:00,13:30-18:00`），也支持跨夜（如 `22:00-02:00`）。
2. **白名单**：把某些群或私聊死死焊在工作/休息模式上。
3. **提示词设定**：填好 Core / Work / Rest 三组设定，让它该卷就卷，该摸鱼就摸鱼。
4. **AutoDream 参数**：可配置 `autodream_interval_seconds`、`autodream_total_threshold`、`autodream_retain_count`、`autodream_source_limit` 控制自动整理频率和强度。

## 🎉 常用指令

| 指令 | 说明 |
| --- | --- |
| `/mode help` | 看指令帮助 |
| `/mode status` | 看看当前是工作还是休息，以及为什么这么判 |
| `/mode work` | 强制当前聊天立马切成工作模式 |
| `/mode rest` | 强制切成休息模式 |
| `/mode auto` | 别强求了，取消锁定恢复顺其自然（按时间切） |
| `/csmem list` | 翻一翻当前环境的三层记忆池里都记了啥 |
| `/csmem rm <id>` | 记错了？抄下 list 里的 ID 给删了 |
| `/csmem sync` | 觉得 Bot 脑子跟不上？赶紧手动敲一锤，让它立刻把刚刚聊的总结存起来 |
| `/autodream help` | 看 AutoDream 的指令帮助 |
| `/autodream status` | 看自动整理是否开启、阈值多少、当前记忆量多少 |
| `/autodream run` | 手动触发一次记忆池重整，压缩并保留重要内容 |

*(如有需要，你甚至可以像使用 /mode set auto 这样兼容旧版本的指令写法。感谢使用！)*

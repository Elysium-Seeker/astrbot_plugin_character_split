# astrbot_plugin_character_split

[License](https://opensource.org/licenses/MIT) [Python 3.10+](https://www.python.org/) [AstrBot](https://github.com/Soulter/AstrBot)

专门给群聊/私聊做上下文隔离的 **人格与记忆多开插件**。

解决什么痛点？**白天你让 Bot 帮你写代码查资料，晚上你想找它闲聊，结果它满嘴都是白天的专业术语，上下文全都串味了。**

这个插件就是干这个的：按时间（或手动）把对话分成“工作”和“休息”两条平行宇宙，并且自带了一个纯本地的**三层记忆系统**，确保它在对的时间表现出对的性格，还能记住对的事。

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

*(如有需要，你甚至可以像使用 /mode set auto 这样兼容旧版本的指令写法。感谢使用！)*


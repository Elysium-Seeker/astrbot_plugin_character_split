<div align="center">

# AstrBot Plugin Character Split

[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)
[![AstrBot](https://img.shields.io/badge/AstrBot-Support-brightgreen.svg)](https://github.com/Soulter/AstrBot)

<img src="https://count.getloli.com/get/@astrbot-plugin-character-split?theme=booru-helltaker" alt="Moe Counter">

按时间对群聊私聊拆分工作与休息轨道，自带三层记忆系统，不串台的智能人格插件。

</div>

## 🆕 最近更新

- v1.2.2 (2026-04-02)
   - 接入 AutoDream 自动调度与 /autodream status|run 指令
   - 三层记忆提取升级，强化 global/mode/session 分类并修复 Layer3 偏置
   - 注入策略升级：切换时段优先 + 高分旧记忆补充 + 普通轮次增量注入
   - 新增衰减策略：global 核心不衰减、mode 30 天半衰、session 3 天半衰
   - 新增 /csmem clear，/csmem sync 结束后直接返回整理结果

## 🌟 核心特性
- **双模轨道**：同一目标对象（群/私聊）自动分离 Work / Rest 两套上下文，拒绝记忆污染。
- **三层记忆系统**：全局（Layer1） / 模式（Layer2） / 会话（Layer3） 动态提取注入。
- **AutoDream (自动休眠整理)**：独立触发记忆碎片合并、自动提纯与自适应遗忘衰减。

## 💿 安装说明
在 AstrBot 直接输入：
\\\ash
/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split
\\\

## 🎉 指令速查
| 指令 | 作用 |
| --- | --- |
| /mode [status/work/rest/auto] | 查看或强制切换当前工作/休息模式 |
| /csmem [list/rm ID/clear/sync] | 三层记忆池管理、局部删改与全量同步 |
| /autodream [status/run] | 查看或手动强制执行全量记忆整理与衰减 |

## ⚙️ 插件配置
请在 Web 仪表盘按需管理工作时间窗、Token 增强上限、多级衰减半衰期 (Half-life) 及 AutoDream 触发参数等进阶设定。（详见 _conf_schema.json）

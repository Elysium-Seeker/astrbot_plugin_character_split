# astrbot_plugin_character_split (人格与记忆多开)

按时间对群聊私聊拆分工作与休息轨道，自带三层记忆系统，不串台的智能人格插件。

## 核心特性
- **双模轨道**：同一目标对象（群/私聊）自动分离 Work / Rest 两套上下文，拒绝记忆污染。
- **三层记忆系统**：全局长期记忆(Layer1) / 分轨偏好(Layer2) / 临时线索(Layer3) 动态提取分级注入。
- **自动休眠整理 (AutoDream)**：独立触发记忆碎片合并、自动提纯与自适应遗忘衰减。

## 安装说明
在 AstrBot 直接输入：
\\\ash
/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split
\\\

## 指令速查
| 指令 | 作用 |
| --- | --- |
| /mode [status/work/rest/auto] | 查看或强制切换当前工作/休息模式 |
| /csmem [list/rm ID/clear/sync] | 当前模式跨时段记忆池管理、提纯与同步 |
| /autodream [status/run] | 查看或手动强制执行全量记忆整理与无用碎片衰减 |

## 插件配置
在 Web 仪表盘按需管理工作日、工作时间窗、Token 注入上限、多级衰减半衰期 (Half-life) 及 AutoDream 触发参数等高级选项设定。（参阅内部 _conf_schema.json）

# astrbot_plugin_character_split

Work/Rest 双模式会话分流与三层记忆管理插件。

## 1. 项目定位

这个插件解决两个核心问题：

- 同一会话里工作与休息上下文互相污染。
- 长对话下记忆注入成本越来越高。

对应策略：

- 每个会话维护 work/rest 两条独立对话轨道。
- 记忆分为 Layer1(global) / Layer2(mode) / Layer3(session) 并按策略注入。

## 2. 当前版本能力

- 模式判定：手动覆盖 > 时间窗 > 白名单 > 默认模式。
- 三层记忆提取：切换时自动提取，手动可执行 /csmem sync。
- 注入策略：
  - 切换模式时优先注入目标模式上一时段的 Layer2/Layer3。
  - 同时补 1 条高分旧记忆用于防断档。
  - 普通轮次默认只注入新增记忆（增量注入）。
- 衰减策略：
  - global 中 importance >= 9 默认不衰减。
  - mode 默认 30 天半衰。
  - session 默认 3 天半衰。
  - importance 越低衰减越快。
- AutoDream：按间隔和阈值自动整理记忆池，手动可执行 /autodream run。

## 3. 安装

1. AstrBot 插件市场搜索 astrbot_plugin_character_split 并安装。
2. 或命令安装：

```bash
/plugin install https://github.com/Elysium-Seeker/astrbot_plugin_character_split
```

## 4. 指令速查

| 指令 | 说明 |
| --- | --- |
| /mode help | 查看模式指令帮助 |
| /mode status | 查看当前模式、来源、会话标识与记忆数量 |
| /mode work | 当前会话强制 work |
| /mode rest | 当前会话强制 rest |
| /mode auto | 清除强制覆盖，恢复自动判定 |
| /mode set work\|rest\|auto | 兼容写法 |
| /csmem list | 查看当前模式的三层记忆 |
| /csmem rm <id> | 删除指定记忆 |
| /csmem clear | 清空当前会话记忆池 |
| /csmem sync | 手动提取当前会话记忆并返回结果 |
| /autodream status | 查看 AutoDream 状态 |
| /autodream run | 立即执行一次 AutoDream 整理 |

## 5. 关键配置（建议先看）

### 5.1 模式判定

- time_mode_enabled
- timezone_offset_hours
- work_days
- work_time_windows
- default_mode
- work_sessions
- rest_sessions

### 5.2 记忆注入策略

- inject_layered_memory
- memory_delta_injection_enabled
- switch_period_priority_injection
- switch_period_fallback_to_recent
- switch_period_bonus_limit
- memory_surprise_probability_percent
- memory_surprise_max_items

### 5.3 衰减策略

- global_no_decay_min_importance
- global_half_life_days
- mode_half_life_days
- session_half_life_days
- low_importance_decay_boost_pct

### 5.4 AutoDream

- autodream_enabled
- autodream_interval_seconds
- autodream_total_threshold
- autodream_retain_count
- autodream_source_limit

### 5.5 Token 预算

- persona_prompt_char_limit
- prompt_global_memory_limit
- prompt_mode_memory_limit
- prompt_session_memory_limit
- prompt_memory_item_char_limit
- prompt_memory_total_char_limit
- summary_history_limit
- summary_message_char_limit
- summary_total_char_limit

完整配置定义见 [_conf_schema.json](_conf_schema.json)。

## 6. 工作流简述

1. on_llm_request 进入后先解析当前模式。
2. 若发生模式切换，切换会话轨道并异步提取被切出模式记忆。
3. 按注入策略组装 Layer1/2/3 到 system prompt。
4. 后台按阈值与间隔检查 AutoDream，必要时压缩记忆池。

## 7. 发布

仓库内置 update.py，可自动更新版本并写入日志：

```bash
python update.py --level patch --note "your note"
```

## 8. 变更记录

详见 [CHANGELOG.md](CHANGELOG.md)。

## 9. 许可

MIT

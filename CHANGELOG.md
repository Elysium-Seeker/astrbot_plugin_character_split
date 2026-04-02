# Changelog

## v1.2.2 - 2026-04-02
- 接入 AutoDream 自动调度与 `/autodream status|run` 指令，支持阈值触发的后台记忆整理
- 三层记忆提取提示词升级，新增 scope 后处理，修复记忆长期偏向 Layer3 的问题
- 注入策略升级为“切换时段优先 + 高分旧记忆补充 + 普通轮次增量注入”
- 新增记忆衰减策略：global 核心（importance>=9）不衰减，mode 30 天半衰，session 3 天半衰
- 新增 `/csmem clear` 清空当前会话记忆池；`/csmem sync` 改为完成后返回结构化结果

## v1.2.1 - 2026-04-02
- 新增一键发布脚本，自动递增版本并同步 metadata/main
- 发布时自动写入 CHANGELOG 并更新 README 最近更新


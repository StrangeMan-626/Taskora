# Taskora

Taskora is an AI-powered desktop task notes and work memory app for Windows.

Taskora 是一款 Windows AI 桌面任务便签与个人工作记忆软件。它把桌面便签、任务计时、轻量工作时间线、AI 日报周报和个人知识库合在一起，帮助用户回答一个很朴素但很难的问题：我今天到底做了什么，哪些事情真的推进了？

## Product Positioning

Taskora 不是普通便签，也不是员工监控软件。它的核心定位是：

- 桌面任务便签：任务以可见、可拖动、可操作的小卡片存在于桌面。
- 工作记忆：记录任务开始、暂停、完成、进展、关联软件和时间线。
- 轻量行为记录：只记录前台应用、窗口标题、使用时长、空闲时间，不默认记录键盘内容、聊天内容、截图、录屏、剪贴板。
- AI 复盘：把任务记录和使用时间线变成日报、周报、任务总结和明日计划。
- 本地知识库：任务、进展、总结、项目笔记长期沉淀，可搜索、可导出、可问答。

## MVP Decision

第一版只做一个闭环：

1. 创建桌面任务便签。
2. 开始、暂停、完成任务。
3. 右键添加任务进展。
4. 低开销记录当前前台软件和窗口标题。
5. 统计任务用时和软件使用时间。
6. 生成今日工作统计。
7. 用户确认数据范围后调用 AI 生成今日总结。
8. 任务完成后生成任务总结并归档到本地知识库。
9. 提供基础隐私设置、暂停记录、软件黑名单和记录删除。

## Technical Direction

建议的 MVP 技术栈：

- Runtime: .NET 10 LTS
- UI: WPF
- Storage: SQLite + JSON settings
- Search: SQLite FTS5
- Knowledge Base: SQLite canonical data + Markdown export
- AI: provider adapter for OpenAI-compatible APIs, DeepSeek, Ollama/local models
- Windows Activity Capture: Win32 APIs through P/Invoke

选择 WPF 的原因：Taskora 第一阶段是 Windows-only 常驻桌面软件，重点是低资源占用、桌面悬浮窗口、托盘、Win32 API 访问和快速落地。WinUI 3 更现代，但 MVP 的桌面便签/常驻工具场景会多一些窗口和系统集成摩擦；Electron 更快做 Web UI，但内存基线偏高；Avalonia 适合未来跨平台，不是当前最短路径。

## Documentation

- [PRD 产品需求文档](docs/PRD.md)
- [MVP 功能清单](docs/MVP_SCOPE.md)
- [页面与交互设计](docs/UI_UX.md)
- [技术架构方案](docs/ARCHITECTURE.md)
- [数据库设计](docs/DATABASE.md)
- [AI Prompt 设计](docs/AI_PROMPTS.md)
- [知识库设计方案](docs/KNOWLEDGE_BASE.md)
- [隐私与安全方案](docs/PRIVACY_SECURITY.md)
- [开发里程碑与第一版执行计划](docs/ROADMAP.md)

## Product Language

推荐使用这些表达：

- 工作记录
- 时间线
- 任务追踪
- 个人复盘
- 工作记忆
- 本地优先
- 用户可控

避免这些表达：

- 监控
- 监听
- 追踪员工
- 实时审计
- 后台监察


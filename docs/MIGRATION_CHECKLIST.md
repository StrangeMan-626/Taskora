# 迁移需求清单（Python MVP → .NET 10 / WPF）

## 0. 说明

本清单来自对当前 Python/Tkinter MVP 的代码审查。目的：迁移到 .NET 10 + WPF 时，把已跑通的闭环平移过去，同时**修掉 MVP 里的正确性问题、补齐功能缺口，避免把临时实现的缺陷带入正式版**。

- 目标技术栈、模块划分、里程碑见 [ARCHITECTURE.md](ARCHITECTURE.md) 与 [ROADMAP.md](ROADMAP.md)，本清单不重复，只列「差异点与遗留问题」。
- 模块名沿用 ARCHITECTURE 的 solution 结构（Taskora.Desktop / Core / Platform / Platform.Windows / Activity / Tasks / AI / KnowledgeBase / Storage / Settings）。
- 里程碑代号沿用 ROADMAP（M0–M6）。
- 跨平台：第一版 Windows/WPF；为后续 macOS，OS 相关调用（§3 的 P/Invoke、§4 的密钥存储、§2 托盘/自启）一律走 `Taskora.Platform` 接口（见 [ARCHITECTURE.md](ARCHITECTURE.md) §3.1），业务逻辑层保持平台无关，Mac 版只重写平台实现 + Avalonia UI。

---

## 1. 必须修复的正确性问题（不要带入 WPF）

| 问题 | Python 现状 | 迁移要求 | 模块 | 里程碑 |
| --- | --- | --- | --- | --- |
| 删除任务未清理关联数据 | `delete_task` 只删 `tasks` 行；`activity_spans`/`ai_summaries`/`knowledge_items` 的 `task_id` 仅被置 NULL，留下孤儿数据。但弹窗文案写「删除所有关联记录」 | 在一个事务内删除任务及其全部关联（或明确做出「保留为匿名记录」的产品决策），二选一，并让 UI 文案与实际行为一致 | Tasks / Storage | M1 |
| 存在「删全部关联」的死代码 | `StatsService.delete_task_records` 已写好却从未被调用 | 迁移时把该逻辑正式接入删除流程，或删除该方法，不要再留悬空实现 | Tasks / Storage | M1 |
| `archived` 状态不可达 | DB 定义了 archived，`archive_task` 服务方法存在但无 UI 入口；右键只有「Archive Snapshot」（那是写知识库，是另一回事） | 提供「归档任务」命令 + 归档列表/过滤视图，区分「归档任务」与「归档为知识条目」两个动作 | Tasks / Desktop | M1 |

---

## 2. 必须补齐的功能缺口

| 缺口 | Python 现状 | 迁移要求 | 模块 | 里程碑 |
| --- | --- | --- | --- | --- |
| AI Provider 配置界面 | `ai.provider/endpoint/model/apiKey/timeout` 只能手改 `taskora.settings.json`，无任何 UI | 设置页提供 Provider/Endpoint/Model/Key/Timeout/「AI 前确认」开关；不配置时回退本地离线草稿 | Settings / Desktop | M4 |
| 系统托盘 + 真正常驻 | 关闭主窗 = 停止记录并退出；只有主窗开着才记录，与「桌面常驻」定位不符 | 关闭主窗 = 最小化到托盘并继续记录；托盘菜单含「暂停/恢复记录、打开主窗、退出」 | Desktop / Activity | M6 |
| 开机自启 | 无 | 提供开机自启开关（注册表 Run 或启动项） | Desktop / Settings | M6 |
| 便签能力不全 | 仅可拖动；`note_collapsed`/`note_width/height` 字段存在但无缩放、无折叠；多显示器无边界修正 | 支持缩放、折叠、多显示器工作区坐标保存与边界修正（见 UI_UX.md / ARCHITECTURE §5） | Desktop | M1 |

---

## 3. 健壮性与性能（迁移时按 ARCHITECTURE 既定方案做）

| 项 | Python 现状 | 迁移要求 | 模块 | 里程碑 |
| --- | --- | --- | --- | --- |
| Win32 调用类型安全 | ctypes 未声明 `argtypes/restype`，`HWND/HANDLE` 在 64 位下被截断（靠句柄低位有效碰巧能用） | P/Invoke 显式声明签名，句柄用 `IntPtr`/`SafeHandle`；优先用 .NET `Process.GetProcessById` 取进程名 | Activity | M2 |
| 空闲检测溢出 | `GetTickCount64` 被截成 32 位，与 `GetLastInputInfo.dwTime` 单位不严格匹配，开机超 ~24.8 天会出错 | tick 取值与 `dwTime` 单位一致、用无符号 64 位计算，避免长开机溢出 | Activity | M2 |
| 句柄释放 | `OpenProcess` 句柄在 `finally` 关闭，但全程靠手写 | 用 `using`/`SafeProcessHandle` 保证释放 | Activity | M2 |
| 活动写入批处理 | 每个 activity span 即时单条 INSERT | 内存缓冲 + 批量事务写入（ARCHITECTURE 推荐 FlushInterval=10s、MaxBuffered=50） | Activity / Storage | M2 |
| UI 刷新开销 | 每秒 `tick` 对每个便签调用 `get_task`，单次约 5 条 SQL（N+1） | ViewModel 定时刷新，不每秒重算全量统计；常用聚合做缓存 | Desktop | M3 |
| 隐私规则查询 | 每次采样（默认每 2s）全表查一次 `privacy_rules` | 启动加载并缓存，变更时失效，不在采样热路径查库 | Activity / Settings | M2 |
| 中断恢复 | `recover_interrupted_sessions` 已实现并在启动调用（保留语义） | WPF 端保留：启动时把未关闭 session 标记 interrupted | Core / Storage | M1 |

---

## 4. 隐私与安全

| 项 | Python 现状 | 迁移要求 | 模块 |
| --- | --- | --- | --- |
| API Key 存储 | 明文存 `taskora.settings.json` | 改用 Windows DPAPI / 凭据管理器（见 PRIVACY_SECURITY.md） | Settings |
| 隐私语义 | private 应用只存进程名、标题存 null/`[hidden]`；AI 输入默认排除 private | 全部平移；「AI 前确认」必须有 UI 开关 | Activity / AI |
| 默认隐私规则种子 | 已种子化 WeChat/QQ/Telegram/Signal/密码管理器/incognito 等 | 迁移时一并平移这批默认规则 | Storage / Settings |

---

## 5. UI 与本地化

- **全面中文化**：Python MVP 全英文，但目标用户与 PRD 均为中文。任务状态、标签页、按钮、对话框、提示文案全部中文。（贯穿全程）
- 遵守产品语言规范（README）：用「工作记录 / 时间线 / 复盘 / 工作记忆」，避免「监控 / 监听 / 追踪员工」等表达。
- 便签卡片视觉以 UI_UX.md 为准：状态色块、信息紧凑、可拖动/缩放/折叠。
- 设置页需覆盖：录制开关、采样间隔、空闲阈值、便签置顶、隐私进程/标题名单、AI 配置、AI 前确认、知识库导出目录、开机自启。

---

## 6. 数据 / Schema 迁移

- 当前 SQLite schema 与 DATABASE.md 基本一致，可作为 .NET 端 **migration v1 基线**，包含：`projects / tasks / task_sessions / applications / activity_spans / task_progress / timeline_events / ai_summaries / knowledge_items / knowledge_links / tags / entity_tags / privacy_rules`，外加 FTS5 虚拟表 `knowledge_items_fts` 与三个同步触发器（AFTER INSERT/DELETE/UPDATE）。
- 保留 `schema_migrations` 版本表机制（PRAGMA：WAL、foreign_keys=ON、busy_timeout）。
- 时间统一 UTC 存储、本地时区展示（Python 已如此，务必保持）。
- 老数据迁移：schema 不变时同一份 `taskora.db` 可被 .NET 端直接打开。首版建议不强制迁移，新老数据目录分开或提供导入入口。

---

## 7. 可直接平移、节省工作量的部分

迁移时这些**逻辑与口径已验证可用**，按原语义实现即可，不要重新发明：

- 任务状态机：todo / in_progress / paused / completed / archived；同一时刻仅一个活动任务；切换任务自动暂停上一个；中断 session 恢复为 interrupted。
- 进展记录三段式：done / blocker / next + 采集当前前台 app/window 上下文 + 隐私脱敏。
- 今日统计口径：任务用时、应用用时、时间线、进展、active/idle 总计。
- 无 provider 时的本地离线总结草稿模板；daily/task 两类 prompt 的分节结构与脱敏原则（见 AI_PROMPTS.md）。
- 知识库归档 + Markdown 导出目录结构（Daily/Tasks/Exports + YAML front matter）+ 基于 content_hash 去重。

---

## 8. 验收补充（在 ROADMAP 各里程碑验收之外追加）

- 删除任务后数据库无孤儿记录（或按既定产品决策保留匿名记录，且 UI 文案一致）。
- 不配置 AI 时离线草稿可用；配置后能连真实 provider；失败有清晰提示且不丢草稿输入。
- 关闭主窗后托盘仍在记录；点「暂停记录」后无新 activity span 写入。
- 全中文界面，无遗漏英文文案。
- 连续开机 > 24 小时，空闲检测仍正确（验证 tick 溢出已修复）。
- API Key 不以明文出现在配置文件中。

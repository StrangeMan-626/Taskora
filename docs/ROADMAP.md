# 开发里程碑与第一版执行计划

## 1. 总体路线

先做可用闭环，再做智能增强。

阶段：

- M0: 项目初始化和基础架构。
- M1: 任务与桌面便签。
- M2: 活动记录与空闲检测。
- M3: 今日统计与任务时间线。
- M4: AI 总结。
- M5: 知识库归档和搜索。
- M6: 隐私、设置、打包和稳定性。

## 2. M0 项目初始化

目标：

- 建立 .NET solution。
- 建立模块项目。
- 建立 SQLite migration。
- 建立基本 MVVM 框架。

建议命令：

```powershell
dotnet new sln -n Taskora
dotnet new wpf -n Taskora.Desktop -o src/Taskora.Desktop
dotnet new classlib -n Taskora.Core -o src/Taskora.Core
dotnet new classlib -n Taskora.Activity -o src/Taskora.Activity
dotnet new classlib -n Taskora.Tasks -o src/Taskora.Tasks
dotnet new classlib -n Taskora.AI -o src/Taskora.AI
dotnet new classlib -n Taskora.KnowledgeBase -o src/Taskora.KnowledgeBase
dotnet new classlib -n Taskora.Storage -o src/Taskora.Storage
dotnet new classlib -n Taskora.Settings -o src/Taskora.Settings
dotnet sln add src/*/*.csproj
```

推荐 NuGet：

- CommunityToolkit.Mvvm。
- Microsoft.Data.Sqlite。
- Microsoft.EntityFrameworkCore.Sqlite，可选。
- Microsoft.Extensions.Hosting。
- Microsoft.Extensions.DependencyInjection。
- Microsoft.Extensions.Logging。

验收：

- 应用能启动主窗口。
- 能创建 `taskora.db`。
- 能读取 `taskora.settings.json`。

## 3. M1 任务与桌面便签

实现：

- Task entity。
- Task repository。
- Task state machine。
- Main window task list。
- Create task dialog。
- TaskNoteWindow。
- 便签位置保存。
- 右键菜单。

验收：

- 创建任务后桌面出现便签。
- 开始/暂停/完成状态正确。
- 重启后任务和便签位置恢复。

## 4. M2 活动记录与空闲检测

实现：

- Win32 P/Invoke wrapper。
- ForegroundWindowSnapshot。
- ActivitySampler。
- IdleDetector。
- PrivacyRuleMatcher。
- ActivitySpanAggregator。
- 批量写入 SQLite。

验收：

- 能记录 VS Code、Chrome 等前台应用时间段。
- 空闲超过阈值后标记 idle。
- 命中隐私规则后隐藏窗口标题。
- 运行 8 小时不明显增加资源占用。

## 5. M3 今日统计与时间线

实现：

- TodayView。
- App usage aggregation。
- Task duration aggregation。
- Task timeline。
- Progress notes。
- 删除某天记录。

验收：

- Today 能展示任务用时、应用用时、进展、时间线。
- private 数据显示为隐藏。
- 删除数据后统计刷新。

## 6. M4 AI 总结

实现：

- AI provider config。
- OpenAI-compatible adapter。
- Ollama adapter，可选。
- PromptBuilder。
- Daily summary generation。
- Task summary generation。
- AI input confirm dialog。
- Summary editor。

验收：

- 用户确认数据范围后生成总结。
- 生成结果可编辑和保存。
- AI 失败有清楚错误提示，不丢输入。

## 7. M5 知识库归档和搜索

实现：

- KnowledgeItem repository。
- FTS5 search。
- Task completion archive flow。
- Daily summary archive flow。
- Markdown export。
- Knowledge search view。

验收：

- 完成任务可生成总结并归档。
- 搜索关键词能找到对应知识条目。
- Markdown 文件结构清晰可读。

## 8. M6 隐私、设置、打包

实现：

- First-run onboarding。
- Privacy settings。
- Recording pause/resume。
- Tray icon menu。
- Startup option。
- Error logging。
- Installer 或 self-contained publish。

验收：

- 用户能理解 Taskora 记录什么、不记录什么。
- 托盘可暂停记录。
- 基础打包可在 Windows 机器安装运行。

## 9. 第一版可执行开发计划

建议按 4 周实现可用 MVP：

### Week 1

- 建立 solution。
- 完成 SQLite schema 和 migration。
- 完成任务 CRUD。
- 完成桌面便签基础窗口。
- 完成任务开始/暂停/完成。

### Week 2

- 完成 Win32 前台窗口采样。
- 完成 idle 检测。
- 完成 activity span 聚合和写库。
- 完成隐私黑名单第一版。
- 完成 Today 基础统计。

### Week 3

- 完成添加进展。
- 完成任务详情和任务时间线。
- 完成 AI provider 配置。
- 完成今日总结和任务总结 prompt。
- 完成 AI 输出保存。

### Week 4

- 完成知识库归档。
- 完成 FTS5 搜索。
- 完成 Markdown 导出。
- 完成隐私设置页。
- 完成托盘、暂停记录、基础打包。
- 做整天运行测试和 bug 修复。

## 10. 测试重点

单元测试：

- Task status transitions。
- Task session duration。
- Activity span aggregation。
- Privacy rule matching。
- Prompt builder redaction。

集成测试：

- SQLite migration。
- Repository CRUD。
- FTS search。
- AI provider mock。

手动测试：

- 多显示器便签位置。
- 应用异常退出。
- 隐私软件命中。
- 电脑锁屏/解锁。
- 睡眠/唤醒。
- 长时间常驻。

## 11. 代码实现建议

优先实现这些接口：

```csharp
public interface ITaskService
{
    Task<TaskItem> CreateTaskAsync(CreateTaskRequest request);
    Task StartTaskAsync(string taskId);
    Task PauseTaskAsync(string taskId);
    Task CompleteTaskAsync(string taskId);
    Task AddProgressAsync(AddProgressRequest request);
}

public interface IActivitySampler
{
    ForegroundWindowSnapshot Capture();
}

public interface IActivityRecorder
{
    Task StartAsync(CancellationToken cancellationToken);
    Task StopAsync();
}

public interface IAiSummaryService
{
    Task<AiSummaryDraft> GenerateDailySummaryAsync(DailySummaryScope scope);
    Task<AiSummaryDraft> GenerateTaskSummaryAsync(string taskId);
}

public interface IKnowledgeBaseService
{
    Task<KnowledgeItem> ArchiveTaskSummaryAsync(string taskId, string summaryId);
    Task<IReadOnlyList<KnowledgeSearchResult>> SearchAsync(string query);
}
```

第一版不要过度抽象：

- Repository 可以直接面向 SQLite。
- Activity sampler 只做 Windows。
- AI provider 先支持 OpenAI-compatible。
- Markdown export 先单向导出，不做双向同步。


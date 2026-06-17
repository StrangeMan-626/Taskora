# 知识库设计方案

## 1. 知识库定位

Taskora 的知识库不是单独的文档库，而是从任务工作流自然沉淀出来的个人工作记忆。

来源：

- 任务。
- 任务进展。
- 任务完成总结。
- 每日总结。
- 每周总结。
- 项目笔记。
- 导入文档。
- 软件使用统计和时间线摘要。

## 2. MVP 方案

MVP 推荐：

- SQLite 作为 canonical storage。
- SQLite FTS5 做全文搜索。
- Markdown 文件作为导出和可读备份。
- 暂不强依赖向量数据库。

原因：

- 任务、日期、项目、标签等结构化查询用 SQLite 更自然。
- FTS5 足够支持第一版关键词搜索。
- Markdown 方便用户信任、迁移和备份。
- 向量库会引入 embedding、模型、索引更新和隐私边界，适合第二阶段。

## 3. 知识条目类型

| 类型 | 来源 | MVP 是否做 |
| --- | --- | --- |
| task_summary | 任务完成后的 AI 总结 | 是 |
| daily_summary | 今日复盘 | 是 |
| progress_note | 用户手动进展 | 是 |
| project_note | 用户手动项目笔记 | 可选 |
| weekly_summary | 周报 | 后续 |
| imported_document | 导入文档 | 后续 |

## 4. Markdown 导出结构

建议目录：

```text
Taskora Knowledge Base/
  Daily/
    2026/
      06/
        2026-06-17.md
  Tasks/
    2026/
      06/
        修复登录 Bug.md
  Projects/
    Project A/
      notes.md
  Exports/
```

任务总结文件示例：

```markdown
---
type: task_summary
task_id: "task_..."
project: "Project A"
status: completed
completed_at: "2026-06-17T15:10:00+08:00"
tags: ["bugfix", "login"]
---

# 修复登录 Bug

## 任务结果

...

## 过程时间线

...

## 关键进展

...
```

每日总结文件示例：

```markdown
---
type: daily_summary
date: "2026-06-17"
timezone: "Asia/Shanghai"
---

# 2026-06-17 今日工作总结

...
```

## 5. 搜索设计

MVP 搜索：

- 标题全文搜索。
- 正文全文搜索。
- 类型筛选。
- 日期筛选。
- 项目筛选。
- 任务筛选。
- 标签筛选。

排序：

- 默认相关度。
- 可切换最近更新。
- 可切换日期倒序。

搜索结果展示：

- 标题。
- 类型。
- 日期。
- 来源任务/项目。
- 命中片段。

## 6. 归档流程

任务完成归档：

1. 用户标记任务完成。
2. Taskora 提示生成任务总结。
3. 用户确认 AI 输入范围。
4. 生成总结草稿。
5. 用户编辑保存。
6. 写入 `ai_summaries`。
7. 写入 `knowledge_items`。
8. 更新 FTS。
9. 可选导出 Markdown。

每日总结归档：

1. 用户打开 Today。
2. 点击生成今日总结。
3. 确认数据范围。
4. 保存总结。
5. 写入知识库。

## 7. AI 问答设计

第二阶段实现：

1. 用户提问。
2. FTS5 先检索候选条目。
3. 如果启用向量检索，再合并 embedding 相似结果。
4. 将 top results 传给 AI。
5. AI 只能基于检索结果回答。
6. 输出引用来源。

MVP 可以先做第 2 步，不做问答。

## 8. 向量库扩展

后续可以增加表：

```sql
CREATE TABLE knowledge_embeddings (
  id TEXT PRIMARY KEY,
  knowledge_item_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  content TEXT NOT NULL,
  embedding_model TEXT NOT NULL,
  embedding BLOB NOT NULL,
  created_at TEXT NOT NULL
);
```

向量检索库选型后续再定：

- SQLite 扩展型向量索引。
- 独立本地向量数据库。
- 纯 embedding + brute force，小数据量下也可接受。

MVP 不绑定具体向量技术，避免早期复杂化。


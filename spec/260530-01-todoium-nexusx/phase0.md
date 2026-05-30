# Phase 0: 需求确认

## 实体

### Todo
| 字段 | 类型 | 约束 | 语义 |
|------|------|------|------|
| id | int | PK, auto | 主键 |
| text | str | NOT NULL | 任务标题 |
| desc | str \| None | | 描述（Markdown） |
| done | bool | default False | 完成状态 |
| parent_id | int \| None | FK → todo.id | 父任务（树形结构） |
| pinned | bool | default False | 置顶（仅根节点） |
| created | str | NOT NULL | 创建时间 ISO |
| done_at | str \| None | | 完成时间 |
| deleted_at | str \| None | | 软删除时间 |

### PomodoroSession
| 字段 | 类型 | 约束 | 语义 |
|------|------|------|------|
| id | int | PK, auto | 主键 |
| started_at | str | NOT NULL | 开始时间 |
| finished_at | str | NOT NULL | 结束时间 |
| phase | str | NOT NULL | focus / break / long_break |
| duration_seconds | int | NOT NULL | 持续秒数 |
| completed | bool | default True | 是否完整完成 |

### Audit
| 字段 | 类型 | 约束 | 语义 |
|------|------|------|------|
| id | int | PK, auto | 主键 |
| timestamp | str | NOT NULL | 操作时间 |
| action | str | NOT NULL | 操作类型 |
| todo_id | int | NOT NULL, FK → todo.id | 关联任务 |
| details | str \| None | | JSON 详情 |

## 实体关系

```
Todo ──1:N(self)──→ Todo        (parent_id, 树形结构)
Todo ──1:N──→ Audit            (一个 Todo 有多条审计记录)
PomodoroSession                 (独立，无外键关联)
```

## 聚合根

- **Todo**: 核心业务实体，树形查询入口
- **PomodoroSession**: 独立聚合根

## Service 切分（方案 A：按功能域）

```
todo/     → Todo CRUD + 树操作 + 审计写入/查询
pomodoro/ → 番茄钟会话记录与查询
```

## 用例方法

### todo 域

| 方法 | 意图 | 挂载 | 参数 |
|------|------|------|------|
| list_todos | 列出活跃任务 | Todo @query | filter_done, hide_stale |
| get_todo | 获取单个任务 | Todo @query | todo_id |
| get_children | 获取子任务 | Todo @query | todo_id |
| get_descendants | 递归获取子孙 | Todo @query | todo_id |
| has_children | 是否有子任务 | Todo @query | todo_id |
| add_todo | 添加任务 | Todo @mutation | text, parent_id, desc |
| update_text | 修改标题 | Todo @mutation | todo_id, text |
| update_desc | 修改描述 | Todo @mutation | todo_id, desc |
| toggle_todo | 切换完成状态 | Todo @mutation | todo_id |
| toggle_pin | 切换置顶 | Todo @mutation | todo_id |
| delete_todo | 软删除含子孙 | Todo @mutation | todo_id |
| get_audit | 查询审计记录 | Audit @query | limit, action |

### pomodoro 域

| 方法 | 意图 | 挂载 | 参数 |
|------|------|------|------|
| record_session | 记录会话 | PomodoroSession @mutation | started_at, finished_at, phase, duration_seconds, completed |
| today_sessions | 今日会话 | PomodoroSession @query | — |

## 第三方库

| 领域 | 方案 |
|------|------|
| ORM | SQLModel (nexusx) |
| GraphQL | nexusx GraphQLHandler |
| MCP | nexusx create_mcp_server |
| API | FastAPI + REST router |
| DB | aiosqlite |
| ER 可视化 | nexusx Voyager |
| 认证 | Bearer token (沿用) |

## 本地模式

保留 DirectClient 模式（内存/本地 SQLite），TUI/CLI 无需启动服务器即可使用。

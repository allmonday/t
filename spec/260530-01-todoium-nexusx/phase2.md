# Phase 2: 方法实现 + Entity 挂载

## 验收标准

### todo 域

| # | 方法 | 测试场景 | 预期结果 |
|---|------|----------|----------|
| 1 | list_todos | 无参数 | 返回所有非 deleted 的 todo |
| 2 | get_todo | 正常查询 | 返回指定 todo |
| 3 | get_todo | 不存在 ID | 返回 None |
| 4 | add_todo | 根任务 | 返回新 todo，parent_id=None |
| 5 | add_todo | 子任务 | 返回新 todo，parent_id 正确 |
| 6 | toggle_todo | 叶子节点 | done 状态翻转 |
| 7 | toggle_todo | 有子节点 | 返回 False，不切换 |
| 8 | toggle_pin | 根节点 | pinned 翻转 |
| 9 | toggle_pin | 子节点 | 抛出 ValueError |
| 10 | delete_todo | 含子节点 | 父+子均标记 deleted_at |
| 11 | update_text | 正常修改 | text 更新 |
| 12 | get_children | 有子节点 | 返回直接子任务列表 |
| 13 | get_descendants | 三层树 | 返回所有子孙 |

### pomodoro 域

| # | 方法 | 测试场景 | 预期结果 |
|---|------|----------|----------|
| 14 | record_session | 正常记录 | 返回新 session |
| 15 | today_sessions | 查询 | 返回今日 session 列表 |

### 通用

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 16 | GraphiQL 可执行所有 query/mutation | 启动服务访问 /graphql |
| 17 | seed 数据可通过 list_todos 查询 | GraphiQL query |

## 实现描述

### 产出文件

| 文件 | 内容 |
|------|------|
| `src/service/todo/methods.py` | Todo 域 12 个业务方法（list/get/add/toggle/delete/audit） |
| `src/service/pomodoro/methods.py` | Pomodoro 域 2 个业务方法（record/today） |
| `src/models.py` | 新增 `mount_method()` 挂载到 Entity @query/@mutation |
| `src/main.py` | 新增 GraphiQL + GraphQL endpoint |

### V 升回查

- [x] 1-13. todo 域方法全部通过 GraphiQL 验证（list_todos 返回 10 条 seed 数据，add_todo 成功创建 #11）
- [x] 14-15. pomodoro 域方法：today_sessions 返回 3 条 seed 数据
- [x] 16. GraphiQL `/graphql` GET 返回 HTML 界面，POST 执行 query/mutation 正常
- [x] 17. seed 数据通过 `todoListTodos` 查询返回完整

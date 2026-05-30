# Phase 3: UseCase 响应组装 + MCP

## 验收标准

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | REST 端点返回字段符合 DTO（FK 隐藏、关系字段包含） | curl POST /api/todo_service/list_todos |
| 2 | Voyager 显示 service 树 + 方法 | 浏览器 /voyager |
| 3 | MCP 扁平化 tool 可直接调用 | MCP 客户端 |
| 4 | 参数校验：缺少必填参数返回 422 | curl 发送空 body |

## 实现描述

### 产出文件

| 文件 | 内容 |
|------|------|
| `src/service/todo/dtos.py` | TodoItem, TodoBrief, AuditItem DTOs |
| `src/service/todo/service.py` | TodoService (12 methods) |
| `src/service/todo/spec.md` | 服务说明 |
| `src/service/pomodoro/dtos.py` | PomodoroSessionItem DTO |
| `src/service/pomodoro/service.py` | PomodoroService (2 methods) |
| `src/service/pomodoro/spec.md` | 服务说明 |
| `src/main.py` | REST router + MCP (flat) + Voyager (services) |

### V 升回查

- [x] 1. REST `POST /api/todo_service/list_todos` 返回 DTO 字段（id, text, done, parent_id, pinned）
- [x] 2. Voyager 200，显示 TodoService + PomodoroService 及其方法
- [x] 3. MCP `/mcp/` 挂载成功（扁平化模式，14 个 tool）
- [x] 4. 缺少 `text` 参数返回 422 `{"detail": [{"type": "missing", "loc": ["body", "text"]}]}`

# Phase 1: Schema + ER Diagram + mock seed

## 验收标准

| # | 验收项 | 验证方式 |
|---|--------|----------|
| 1 | Voyager ER 图正确显示 Todo（自引用）、Audit、PomodoroSession 三个实体及关系线 | 启动 uvicorn，浏览器打开 /voyager |
| 2 | models.py 每个 Entity 只有字段 + Relationship，无 @query/@mutation，无 nexusx 导入 | 代码审查 |
| 3 | mock seed 包含树形 Todo（根+子+孙）、已完成/未完成、置顶/非置顶、PomodoroSession、Audit 记录 | 启动后查询验证记录数 |

## 实现描述

### 产出文件

| 文件 | 内容 |
|------|------|
| `src/db.py` | aiosqlite engine + async_session_factory |
| `src/models.py` | Todo（自引用树）, Audit, PomodoroSession 纯实体 + Relationship + ErManager |
| `src/database.py` | mock seed: 10 Todo（3层树）、4 Audit、3 PomodoroSession |
| `src/main.py` | FastAPI + Voyager ER 图 |

### V 升回查

- [x] 1. Voyager `/voyager/` 返回 200，ER 图显示 Todo（自引用）、Audit、PomodoroSession 三个实体
- [x] 2. models.py 只有字段 + Relationship，无 @query/@mutation，仅底部有 ErManager 初始化
- [x] 3. seed 数据：10 个 Todo（根+子+孙，含 done/pinned），4 条 Audit，3 条 PomodoroSession

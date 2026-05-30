# Todoium Nexusx Refactor

## 原始需求

使用 nexusx 四阶段开发模式重构 todoium 项目后端，替换现有 WebSocket server + store 层，保留 TUI/CLI 客户端和本地模式（DirectClient）。

## Overview Design

### 业务流程

```
用户 → TUI/CLI → (本地模式) DirectClient → SQLModel 内存/本地 DB
                 → (远程模式) HTTP Client  → FastAPI REST → UseCaseService → SQLModel DB
                                                    ↓
                                              GraphQL (辅助测试)
                                              MCP (AI 集成)
                                              Voyager (ER 可视化)
```

### 实体关系

```
Todo ──1:N(self)──→ Todo        (parent_id, 树形结构)
Todo ──1:N──→ Audit            (一个 Todo 有多条审计记录)
PomodoroSession                 (独立，无外键关联)
```

### 聚合根

- **Todo**: 核心业务实体，树形查询入口
- **PomodoroSession**: 独立聚合根

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| ORM | SQLModel | nexusx 深度集成 |
| API 层 | GraphQL + REST + MCP | 全覆盖 |
| 本地模式 | 保留 DirectClient | TUI/CLI 无需启动服务器 |
| DB | SQLite (aiosqlite) | 沿用现有方案 |
| 认证 | Bearer token | 沿用现有方案 |
| Service 切分 | 按功能域 (todo / pomodoro) | 业务内聚 |

### 四阶段产出

| Phase | 交付物 |
|-------|--------|
| 1 | SQLModel 实体 + Voyager ER 图 + mock seed |
| 2 | methods.py 实现业务方法 + GraphQL 可查询 |
| 3 | UseCaseService + DTO + REST + MCP |
| 4 | OpenAPI spec → TS SDK |

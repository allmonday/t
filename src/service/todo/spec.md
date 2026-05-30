# Todo Service

## 目的
管理任务（Todo）的 CRUD、树形结构操作和审计日志。

## 方法

| 方法 | 类型 | 说明 |
|------|------|------|
| list_todos | query | 列出活跃任务，支持按完成状态过滤 |
| get_todo | query | 获取单个任务详情 |
| get_children | query | 获取直接子任务 |
| get_descendants | query | 递归获取所有子孙 |
| has_children | query | 是否有子任务 |
| add_todo | mutation | 添加任务（支持指定 parent） |
| update_text | mutation | 修改标题 |
| update_desc | mutation | 修改描述 |
| toggle_todo | mutation | 切换完成状态（仅叶子） |
| toggle_pin | mutation | 切换置顶（仅根） |
| delete_todo | mutation | 软删除含子孙 |
| get_audit | query | 查询审计记录 |

## DTO

- **TodoItem**: 完整任务信息 + children 关系
- **TodoBrief**: 精简任务信息（列表用）
- **AuditItem**: 审计记录

# t

命令行树形 TODO 工具，支持 CLI 和 TUI 两种交互方式。

## 安装

需要 Python >= 3.10，推荐使用 [uv](https://github.com/astral-sh/uv)。

```bash
# 首次安装
uv tool install .

# 代码改动后重新安装（uv 有构建缓存，需要先清缓存再装）
uv cache clean todo_cli && uv tool install --force .
```

安装后 `todo` 命令会放在 `~/.local/bin/todo`，确保 `~/.local/bin` 在 `$PATH` 中。

## 使用

```bash
t                        # 进入 TUI 交互界面
t -l                     # 树形列出所有任务
t -l --pending           # 仅未完成
t -l --done              # 仅已完成
t 任务内容                # 添加根任务
t 子任务 -p <id>         # 添加子任务
t -x <id>                # 切换完成状态
```

## TUI 快捷键

| 键 | 操作 |
|---|---|
| `j` / `k` | 上下移动 |
| `Space` | 切换完成状态（仅叶子节点） |
| `h` / `l` | 折叠 / 展开 |
| `m` | 全部折叠 / 展开 |
| `a` | 添加根任务 |
| `Tab` | 添加子任务 |
| `d` | 删除任务 |
| `f` | 切换过滤：All -> Pending -> Done |
| `q` | 退出 |

过滤状态显示在顶部标题栏。过滤按根任务的完成状态生效，子任务跟随根任务显示。

## 数据存储

数据库文件：`~/.todo.db`（SQLite，首次运行自动创建，自动执行数据库迁移）。

## 开发

```bash
# 首次：初始化开发数据库
uv run alembic upgrade head

# 修改 ORM model 后生成迁移
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head

# 使用开发数据库运行
TODO_DB=dev.db uv run t

# 重置开发数据库
rm dev.db && uv run alembic upgrade head
```

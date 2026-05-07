# todoium

命令行树形 TODO 工具，支持 CLI 和 TUI 两种交互方式，内置番茄钟，支持 C/S 架构远程同步。

## 安装

需要 Python >= 3.10。

```bash
# 从 PyPI 安装
pip install todoium

# 或使用 pipx 隔离安装（推荐）
pipx install todoium

# 或使用 uv
uv tool install todoium
```

安装后 `t` 命令即可使用。

### 从源码安装（开发）

```bash
git clone https://github.com/allmonday/todoium.git
cd todoium
uv tool install .

# 代码改动后重新安装
uv cache clean todo_cli && uv tool install --force .
```

## 使用

```bash
t                        # 进入 TUI 交互界面
t -l                     # 树形列出所有任务
t -l --pending           # 仅未完成
t -l --done              # 仅已完成
t 任务内容                # 添加根任务
t 子任务 -p <id>         # 添加子任务
t -x <id>                # 切换完成状态
t --desc <id> -m "描述"  # 为任务添加描述
```

### Server 模式

可以作为独立 HTTP 服务部署，供多端同步：

```bash
t --server --token <your-secret> --port 8000
```

### 远程连接

客户端通过配置文件 `~/.todoiumrc` 或命令行参数连接远程 server：

```bash
# 命令行参数
t --remote https://your-server.com --token <token>

# 或写入配置文件 ~/.todoiumrc
remote=https://your-server.com
token=your-secret
```

也可以通过环境变量：`TODO_REMOTE_URL`、`TODO_REMOTE_TOKEN`。

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
| `t` | 切换过滤：All -> Pending -> Done |
| `q` | 退出 |

TUI 内置番茄钟功能（25 分钟专注 / 5 分钟休息 / 15 分钟长休息）。

## 数据存储

数据库文件默认 `~/.todo.db`（SQLite，首次运行自动创建并执行迁移）。

可通过 `--db` 参数指定自定义路径：

```bash
t --db /path/to/my.db
```

## 开发

```bash
# 首次：初始化开发数据库
uv run alembic upgrade head

# 修改 ORM model 后生成迁移
uv run alembic revision --autogenerate -m "描述"
uv run alembic upgrade head

# 使用开发数据库运行
TODO_DB=dev.db uv run t

# 运行测试
uv run pytest

# 重置开发数据库
rm dev.db && uv run alembic upgrade head
```

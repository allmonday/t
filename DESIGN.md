# Plan: `todo` CLI + TUI 命令行工具（树形嵌套版）

## Context

构建一个 Python 命令行 todo 工具，支持嵌套树形任务、CLI 快捷操作和 **Textual TUI** 交互界面。用 `uv tool install` 管理安装。**UI 与数据分离**，方便后续切换 TUI 组件库。包含 **audit 审计日志**，**软删除**，**SQLite 存储**（支持万级数据 + 内置并发锁 + ACID 事务）。

## 项目结构

```
/home/tangkikodo/todo/
├── pyproject.toml
└── todo_cli/
    ├── __init__.py          # 暴露 main(), argparse 入口
    ├── models.py            # 数据模型 (dataclass)
    ├── store.py             # 数据层 — SQLite, 纯逻辑，无 UI 依赖
    ├── tree.py              # 树操作 (flatten, 宽字符处理)
    ├── cli.py               # CLI 视图 (rich)
    └── tui.py               # TUI 视图 (curses) — 可替换
```

### 分层架构

```
┌──────────────────────────────────────────┐
│            main() / argparse             │  __init__.py
├──────────┬───────────────────────────────┤
│  cli.py  │          tui.py              │  视图层（可替换）
│  (rich)  │        (textual)              │
├──────────┴───────────────────────────────┤
│       store.py + models.py               │  数据层（SQLite, UI 无关）
│             tree.py                      │  树操作（UI 无关）
└──────────────────────────────────────────┘
```

**关键原则**: `store.py` 和 `tree.py` 不 import 任何 UI 库。视图层通过公开 API 操作数据。切换 TUI 库时只需替换 `tui.py`。

**为什么用 SQLite 而非 JSON**:
- 万级数据无性能问题（增量更新，不需全量序列化）
- 内置文件锁（无需 `lock.py`，WAL 模式支持并发读）
- ACID 事务（崩溃安全，无需 signal handler 保数据）
- `sqlite3` 是 Python 内置模块，零额外依赖
- audit 日志与 todo 数据放同一个 DB，原子写入

### pyproject.toml

```toml
[project]
name = "todo-cli"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = ["rich", "textual"]

[project.scripts]
todo = "todo_cli:main"
```

安装: `uv tool install .`
更新: `uv tool install . --force`

---

## 数据库设计

文件: `~/.todo.db`

```sql
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    done INTEGER NOT NULL DEFAULT 0,    -- 0/1 boolean
    parent INTEGER REFERENCES todos(id),
    created TEXT NOT NULL,              -- ISO 8601
    deleted_at TEXT                     -- NULL=active, ISO 8601=软删除
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,            -- ISO 8601
    action TEXT NOT NULL,               -- 'add'|'toggle'|'delete'
    todo_id INTEGER NOT NULL,
    details TEXT                        -- JSON string
);

CREATE INDEX IF NOT EXISTS idx_todos_parent ON todos(parent);
CREATE INDEX IF NOT EXISTS idx_todos_active ON todos(deleted_at) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit(timestamp);
```

**连接配置:**
```python
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL")        # 并发读不阻塞
conn.execute("PRAGMA foreign_keys=ON")          # 外键约束
conn.execute("PRAGMA busy_timeout=5000")        # 写冲突等 5s
conn.row_factory = sqlite3.Row                  # 按列名访问
```

**WAL 模式并发行为:**
- TUI 持有长连接：读写自由
- CLI `-l`：读操作，不阻塞 TUI
- CLI `-a`/`-x`：写操作，SQLite 自动排队（busy_timeout=5s）
- 无需手动文件锁

---

## 模块详细设计

### models.py — 数据模型

```python
@dataclass
class Todo:
    id: int
    text: str
    done: bool
    parent: int | None
    created: str
    deleted_at: str | None

@dataclass
class FlatRow:
    """树扁平化后的一行，供 TUI/CLI 渲染"""
    todo: Todo
    depth: int
    prefix: str              # 树形连线前缀
    has_children: bool
    is_last_child: bool
```

### store.py — 数据层 (SQLite)

```python
class TodoStore:
    def __init__(self, db_path="~/.todo.db"):
        self.db_path = os.path.expanduser(db_path)
        self.conn = None

    def connect(self) -> None
        """打开连接，建表，WAL 模式。首次运行插入引导数据。"""

    def close(self) -> None

    # ── 查询 ──
    def list_active(self) -> list[Todo]         # WHERE deleted_at IS NULL
    def get(self, todo_id: int) -> Todo | None
    def get_children(self, todo_id: int) -> list[Todo]  # active children
    def get_descendants(self, todo_id: int) -> list[Todo]
    def has_children(self, todo_id: int) -> bool

    # ── 修改（每个操作一个事务，自动写 audit）──
    def add(self, text: str, parent_id: int | None = None) -> Todo
    def toggle(self, todo_id: int) -> bool      # 仅叶子可 toggle + bubble_up
    def delete(self, todo_id: int) -> int        # 软删除 + 级联子孙
    def bubble_up(self, todo_id: int) -> None    # 内部调用

    # ── Audit ──
    def _log_audit(self, action: str, todo_id: int, details: dict) -> None
    def get_audit(self, limit=50, action=None) -> list[dict]

    # ── Context manager ──
    def __enter__(self): ...
    def __exit__(self): ...
```

**关键实现细节:**

```python
def add(self, text, parent_id=None):
    with self.conn:  # 自动 commit/rollback
        cur = self.conn.execute(
            "INSERT INTO todos (text, done, parent, created) VALUES (?, 0, ?, ?)",
            (text, parent_id, datetime.now().isoformat())
        )
        todo_id = cur.lastrowid
        self._log_audit("add", todo_id, {"text": text, "parent": parent_id})
        return self.get(todo_id)

def toggle(self, todo_id):
    todo = self.get(todo_id)
    if not todo:
        return False
    if self.has_children(todo_id):
        return False  # 父节点不可手动 toggle
    with self.conn:
        new_done = not todo.done
        self.conn.execute("UPDATE todos SET done=? WHERE id=?", (new_done, todo_id))
        self._log_audit("toggle", todo_id, {"done": new_done})
        self.bubble_up(todo_id)
    return True

def delete(self, todo_id):
    now = datetime.now().isoformat()
    descendants = self.get_descendants(todo_id)
    ids = [todo_id] + [d.id for d in descendants]
    with self.conn:
        placeholders = ",".join("?" * len(ids))
        self.conn.execute(
            f"UPDATE todos SET deleted_at=? WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            [now] + ids
        )
        self._log_audit("delete", todo_id, {"subtasks_count": len(descendants)})
    return len(ids)

def bubble_up(self, todo_id):
    """从当前节点向上冒泡，更新祖先的 done 状态"""
    todo = self.get(todo_id)
    if not todo or not todo.parent:
        return
    parent = self.get(todo.parent)
    if not parent:
        return
    children = self.get_children(parent.id)
    all_done = all(c.done for c in children) and len(children) > 0
    if parent.done != all_done:
        self.conn.execute("UPDATE todos SET done=? WHERE id=?", (all_done, parent.id))
        self._log_audit("auto_toggle", parent.id, {"done": all_done, "triggered_by": todo_id})
        self.bubble_up(parent.id)  # 递归向上
```

**Audit 合并到 store.py**: 不再需要独立的 `audit.py`。审计记录和 todo 数据在同一事务中写入，保证一致性。

### tree.py — 树操作

```python
def build_tree(todos: list[Todo]) -> dict[int | None, list[Todo]]
    """构建 parent_id → children 映射"""

def get_roots(todos: list[Todo]) -> list[Todo]
    """获取根任务列表"""

def flatten_tree(todos: list[Todo], collapsed: set[int]) -> list[FlatRow]
    """扁平化，CLI -l 输出用"""

def display_width(s: str) -> int
def truncate_to_width(s: str, max_w: int) -> str
def format_time(iso_str: str) -> str       # → "MM/DD HH:MM"
```

注: `strikethrough` 不再需要 — Textual 和 Rich 都原生支持 `strike` 样式。
`flatten_tree` 主要供 CLI 使用；TUI 由 Textual Tree 控件自行管理树结构。

### tui.py — Textual TUI（可替换）

使用 Textual 框架的内置控件，大幅简化 TUI 实现：

```python
from textual.app import App, ComposeResult
from textual.widgets import Tree, Header, Footer, Input
from textual.binding import Binding

class TodoApp(App):
    """TUI 主应用"""
    BINDINGS = [
        Binding("a", "add_root", "Add"),
        Binding("tab", "add_child", "Sub-task"),
        Binding("d", "delete", "Delete"),
        Binding("space", "toggle", "Toggle"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, store: TodoStore):
        super().__init__()
        self.store = store

    def compose(self) -> ComposeResult:
        yield Header()
        yield TodoTree(self.store)     # 自定义 Tree 子类
        yield Footer()

    # action methods...

class TodoTree(Tree):
    """基于 Textual Tree 控件的 todo 树"""
    # 利用 Tree 内置的展开/折叠/导航
    # 自定义节点渲染 (checkbox, strikethrough, time)

def run_tui(store: TodoStore) -> None:
    app = TodoApp(store)
    app.run()
```

**Textual 带来的简化:**
- **Tree 控件**: 内置展开/折叠、键盘导航、滚动，无需手动实现
- **Input 控件**: 内置文本输入+中文支持，无需手动 `get_wch()` 循环
- **Footer**: 自动显示快捷键绑定
- **CSS 样式**: 用 TCSS 文件或内联 CSS 控制颜色/布局
- **事件系统**: 装饰器绑定按键事件，比 curses 主循环清晰
- **自动 resize**: Textual 自动处理终端大小变化
- **鼠标支持**: 点击节点、滚轮免费获得

**自定义渲染:**
```python
# 节点标签格式
def render_label(todo: Todo, has_children: bool) -> Text:
    mark = "[✓]" if todo.done else "[ ]"
    time = format_time(todo.created)
    text = Text()
    text.append(f"{mark} ", style="green" if todo.done else "")
    text.append(f"#{todo.id}  ", style="cyan")
    if todo.done:
        text.append(todo.text, style="strike dim")
    else:
        text.append(todo.text)
    text.append(f"  {time}", style="yellow")
    return text
```

### cli.py — rich CLI

```python
def cli_list(store: TodoStore) -> None
def cli_add(store: TodoStore, text: str, parent_id: int | None) -> None
def cli_toggle(store: TodoStore, todo_id: int) -> None
```

---

## 交互方式

| 命令 | 功能 |
|---|---|
| `todo` | 进入 TUI |
| `todo -a '文本'` | 添加根任务 |
| `todo -a '文本' -p <id>` | 添加子任务 |
| `todo -l` | 树形列出（rich） |
| `todo -x <id>` | toggle 完成状态 |

## 初始引导数据

首次连接 DB（表为空）时自动插入 8 条引导数据：

```
▼ [ ] #1  快速上手 Todo CLI
├── [ ] #2  按 Space 切换完成状态
├── [ ] #3  按 Tab 添加子任务
└── [ ] #4  按 ←→ 折叠/展开树节点
▼ [ ] #5  示例项目
├── [✓] #6  设计方案
└── [ ] #7  编码实现
  [ ] #8  按 d 删除此任务试试
```

在 `store.connect()` 中: 建表后检查 `SELECT COUNT(*) FROM todos` = 0 → 插入引导数据。

## 自动完成（仅向上冒泡）

- 叶子 toggle → `bubble_up()` 逐级检查
- 同级 active 子任务全完成 → 父 `done=1` → 递归向上
- 取消子任务 → 父 `done=0` → 递归向上
- 父节点不可手动 toggle（`has_children` 返回 True 时拒绝）
- Space 在父节点 → 折叠/展开

## TUI 线框图（Textual）

### 正常状态

```
╭─ TODO ──────────────────────────────────────────── 8 items ─╮
│                                                              │
│  ▼ [ ] #1  项目重构                           04/27 14:30   │
│  ├── [ ] #2  重写认证模块                     04/27 14:31   │
│  ├── [✓] #3  更新数据库                       04/27 14:32   │
│  └── ▼ [ ] #4  写测试                         04/27 14:33   │
│       ├── [ ] #5  单元测试                    04/27 14:34   │
│       └── [✓] #6  集成测试                    04/27 14:35   │
│  ▶ [✓] #7  日常事务                           04/27 15:00   │
│  [ ] #8  独立任务                              04/27 16:00   │
│                                                              │
╰──────────────────────────────────────────────────────────────╯
 a Add  Tab Sub-task  Space Toggle  d Delete  q Quit
```

注: Textual 的 Tree 控件自带 ▶/▼ 折叠指示器和树形缩进连线。
Header 显示标题+计数，Footer 自动显示 BINDINGS 快捷键。
高亮行由 Textual 的 cursor 机制自动处理（无需手动 `A_REVERSE`）。

### 添加任务（弹出 Input）

```
╭─ TODO ──────────────────────────────────────────── 8 items ─╮
│  ...树形内容...                                              │
╰──────────────────────────────────────────────────────────────╯
╭─ New todo ───────────────────────────────────────────────────╮
│ 写周报_                                                      │
╰──────────────────────────────────────────────────────────────╯
```

### 删除确认

```
╭─ Confirm ────────────────────────────────────────────────────╮
│ Delete "#4 写测试" and 2 subtasks?         [Yes]    [No]     │
╰──────────────────────────────────────────────────────────────╯
```

## TUI 快捷键（Textual Bindings）

| 键 | 操作 | 备注 |
|---|---|---|
| `↑` / `k` | 上移 | Tree 控件内置 |
| `↓` / `j` | 下移 | Tree 控件内置 |
| `Space` | 叶子: toggle; 父: 折叠/展开 | 自定义 action |
| `Enter` | 折叠/展开 | Tree 控件内置 |
| `Tab` | 添加子任务 | 弹出 Input 控件 |
| `a` | 添加根任务 | 弹出 Input 控件 |
| `d` | 删除（确认对话框） | 弹出 confirm |
| `t` | 切换过滤: All → Pending → Done | 循环切换 |
| `q` | 退出 | App.quit() |

## 过滤功能

三种过滤模式循环切换（按 `t`），**仅按根任务的 done 状态过滤**，子树整体跟随：

| 模式 | 显示内容 | Header 指示 |
|---|---|---|
| `All` | 所有根任务及其子树 | `TODO (8 items)` |
| `Pending` | 仅 `done=false` 的根任务 + 完整子树 | `TODO (5 pending)` |
| `Done` | 仅 `done=true` 的根任务 + 完整子树 | `TODO (3 done)` |

**CLI 支持**:
- `todo -l` — 所有任务
- `todo -l --pending` — 仅未完成根任务
- `todo -l --done` — 仅已完成根任务

**store.py**:
```python
def list_roots(self, filter_done: bool | None = None) -> list[Todo]:
    """获取根任务，可按 done 过滤"""
    # WHERE parent IS NULL AND deleted_at IS NULL
    # + optional: AND done = ?
```

**tree.py**:
```python
def filter_roots(todos: list[Todo], filter_done: bool | None) -> list[Todo]:
    """按根任务 done 状态过滤，返回匹配的根及其所有子孙"""
```

## TUI 视觉（Textual CSS）

```css
TodoTree {
    height: 1fr;
}
TodoTree > .tree--cursor {
    background: $accent;       /* 高亮选中行 */
}
.done-label {
    text-style: strike;
    color: $text-muted;
}
.check-done {
    color: green;
}
.todo-id {
    color: cyan;
}
.todo-time {
    color: yellow;
}
```

## CLI 输出（rich Tree）

```
📋 TODO (8 items)
├── [ ] #1  项目重构                          04/27 14:30
│   ├── [ ] #2  重写认证模块                  04/27 14:31
│   ├── [✓] #3  更新数据库                    04/27 14:32
│   └── [ ] #4  写测试                        04/27 14:33
│       ├── [ ] #5  单元测试                  04/27 14:34
│       └── [✓] #6  集成测试                  04/27 14:35
├── [✓] #7  日常事务                          04/27 15:00
│   ├── [✓] #8  买菜                          04/27 15:01
│   └── [✓] #9  寄快递                        04/27 15:02
└── [ ] #10 独立任务                          04/27 16:00
```

## 边界情况

| 场景 | 处理 |
|---|---|
| DB 不存在 | `connect()` 自动建库建表 |
| DB 损坏 | sqlite3 报错，打印提示退出 |
| `-x` 父节点 | "Has subtasks, complete them instead" |
| 删除父节点 | 软删除节点+所有子孙，确认显示子任务数 |
| `-x` 已软删除的节点 | "Todo #N not found" |
| 并发写冲突 | SQLite `busy_timeout=5s` 自动重试 |
| TUI + CLI 同时运行 | WAL 模式: 读不阻塞，写排队 |
| 终端太小 | Textual 自动处理 |
| 深嵌套 | Tree 控件自动缩进 |
| CJK | Rich/Textual 原生支持 CJK 宽字符 |
| resize | Textual 自动处理 |
| SIGKILL | SQLite WAL 自动恢复，事务级数据安全 |

## 实现顺序

1. `pyproject.toml` + 包骨架 (`__init__.py`, `models.py`)
2. `store.py` — SQLite 连接 + 建表 + CRUD + bubble_up + audit + 引导数据
3. `tree.py` — flatten_tree + 显示辅助
4. `cli.py` — rich tree 输出 + CLI 命令
5. `__init__.py` — argparse + main()
6. `uv tool install .` 验证 CLI 可用
7. `tui.py` — Textual App 骨架: Header + TodoTree + Footer + quit
8. `tui.py` — TodoTree 自定义渲染 (checkbox, strikethrough, time)
9. `tui.py` — Space toggle + 数据刷新
10. `tui.py` — Input 弹出 (a 添加根任务, Tab 添加子任务)
11. `tui.py` — 删除确认对话框
12. 收尾: 空状态提示, 边界处理

## 验证

```bash
cd /home/tangkikodo/todo
uv tool install .

# CLI 测试（首次运行自动建库+引导数据）
todo -l                       # 树形展示引导数据
todo -a '新任务'
todo -a '子任务' -p 9
todo -x 10                    # toggle 叶子
todo -l                       # 确认变更

# TUI 测试
todo                          # 导航、toggle、折叠、添加、删除

# 并发测试
todo &                        # 后台 TUI
todo -l                       # 应正常读取（WAL 不阻塞读）
todo -a 'concurrent'          # 应正常写入（排队等待）
fg                            # 回到 TUI 确认新任务可见

# 审计
sqlite3 ~/.todo.db "SELECT * FROM audit ORDER BY id DESC LIMIT 10"

# 首次运行
rm ~/.todo.db
todo                          # 自动建库 + 引导数据
```

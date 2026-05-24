# Changelog

## 0.5.0

- 新增 remote 模式版本检查：client 连接 server 后自动对比版本，不一致时弹出 warning 提示具体版本号

## 0.4.3

- 修复 desc 展开面板鼠标滚轮滚动无效的问题（Static 替换为 ScrollableContainer）
- desc 面板高度从 60% 调整为 30%

## 0.4.1

- 修复连续按 e/A 等快捷键导致多层对话框叠加的问题
- 编辑 todo（e）简化为只编辑 text，去掉 desc 二次弹框

## 0.4.0

- REST API 完全替换为 WebSocket 协议，支持多客户端实时同步和服务端推送
- 本地模式：DirectClient 直接调用 TodoStore，零网络开销，不再启动 embedded server
- 远程模式：RemoteClient 通过 WebSocket 连接远程 server，支持广播变更通知
- 移除 REST 路由文件（routes_todo.py、routes_pomodoro.py、schemas.py、client.py、runner.py）
- Pinned 和普通 TODO 合并为同一列表显示，pinned 排前面（★ 标记区分）
- 修复：失败的 mutation 不再触发跨客户端广播
- 修复：WebSocket 断连后 pending 请求立即失败，不再等到超时
- 修复：broadcast 遍历连接表时快照防并发修改
- 修复：请求字段缺失返回 `bad_request` 而非 `internal_error`

## 0.3.1

- 修复 ModalScreen 中快捷键被 App 层 priority 绑定拦截的问题（override `_check_bindings`，让 priority 绑定也尊重 modal 边界）
- Pin 快捷键从 `s` 改为 `p`

## 0.3.0

- 新增 Pin 功能：按 `s` 键可置顶根级别 todo，被 pin 的 todo 显示 ★ 标记
- TUI 双区域显示：`★ Pinned TODO` 和 `TODO` 分区展示
- 非 root todo 不允许 pin，操作时会提示

## 0.2.0

- 新建子 todo 时，自动将已完成的祖先 todo 回溯为 pending 状态
- 修复 `--remote ""` 无法覆盖 ~/.todoiumrc 中 remote 配置的问题
- 番茄钟结束提示增强：macOS 系统通知 + 声音、模态弹窗确认、进度条闪烁
- 支持通过 `~/.todoiumrc` 自定义番茄钟时长（`pomo_focus`/`pomo_break`/`pomo_long_break`，单位分钟）
- 番茄钟进度条已完成部分改用空心圆圈显示

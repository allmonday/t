# Changelog

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

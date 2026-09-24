# S-UI-01 — Tauri v2 窗口能力 Spike 报告（报告型）

- 日期：2026-09-23（Asia/Shanghai）
- 归属：PR-023 附件（计划 §8.3）；正式实现进入 PR-030/031
- 性质：**报告型 spike，不合并 spike 代码**（本报告未产生新 spike 代码）
- 总体结论：**部分验证** —— 7 项中 2 项源码级已实现但无 GUI 交互实证（标 未验证）；1 项 N/A（单显示器环境）；3 项真实缺口（geometry restore、WebView2 reload、事件重连）；另发现 1 项**阻断级缺陷 R11**（capability 未授予窗口写权限，前端窗口操作静默失效）

---

## 0. 环境与版本

| 项 | 值 | 取证方式 |
|---|---|---|
| OS | Windows 11 build 26200.7462，DisplayVersion 25H2（注册表 ProductName 仍写 "Windows 10 Home China"） | HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion |
| WebView2 Runtime | 153.0.4234.48 | HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5} |
| Tauri（Rust crate） | tauri 2.11.5 / tauri-build 2.6.3 / tauri-runtime-wry 2.11.4 | Cargo.toml + C:\Users\a.gide\.cargo\registry\src\index.crates.io-1949cf8c6b5b557f\ |
| @tauri-apps/api（JS） | 2.11.1 | apps/desktop-ui/node_modules/@tauri-apps/api/package.json |
| Rust 工具链 | rustc 1.98.1 (48a229cea 2026-09-01)，host x86_64-pc-windows-gnu | rustc --version --verbose |
| 显示器 | 1 台：\\.\DISPLAY5，bounds {X=0,Y=0,Width=1707,Height=1067}，primary=True；workarea 1707x1019 | [System.Windows.Forms.Screen]::AllScreens |
| 缩放 | AppliedDPI=144（150%）；Graphics.DpiX=96 | HKCU\Control Panel\Desktop\WindowMetrics |
| 构建验证 | cargo check EXIT=0（CARGO_TARGET_DIR=X 盘，--offline，PATH 前置 w64devkit） | 本会话实测 |

---

## 1. 逐项能力矩阵（§8.3 七项）

### 1.1 transparent + always-on-top —— 未验证（源码级已实现）

证据：apps/desktop-shell/src-tauri/src/tray.rs:345-358

    WebviewWindowBuilder::new(app, "main", WebviewUrl::App("index.html".into()))
      .title("LocalVoiceAgent Pet")
      .inner_size(360.0, 520.0)
      .resizable(false)
      .fullscreen(false)
      .transparent(true)
      .decorations(false)
      .always_on_top(true)
      .skip_taskbar(false)
      .shadow(false)

另有 tray.rs:180 / :224 / :268 三处窗口构造（settings/chat/memory 类窗口）同样带 skip_taskbar(false)。

构建验证：cargo check 通过。**未做 GUI 交互实证**（本会话无 GUI 自动化能力：无法截图、无法驱动窗口），因此透明与置顶的运行时表现标 未验证，不回填 PASS。

复现命令（需 GUI）：启动 apps\desktop-shell\src-tauri\target\debug\lva-pet.exe（2026-09-18 20:32，269,856,718 B），观察窗口是否无边框、是否始终位于其他窗口之上。

### 1.2 click-through toggle —— 失败（静默失效）

前端实现：apps/desktop-ui/src/composables/window/useWindowGeometry.ts:15

    await win.setIgnoreCursorEvents(isClickThrough.value);   // 失败仅 console.warn

根因（硬证据）：apps/desktop-shell/src-tauri/capabilities/default.json（218 B）只授予

    "permissions": ["core:default"], "windows": ["main"]

而 gen/schemas/acl-manifests.json 中 core:window:default 的权限集合实测**只含只读 API**，共 28 项：
allow-get-all-windows、allow-scale-factor、allow-inner-position、allow-outer-position、allow-inner-size、allow-outer-size、allow-is-fullscreen、allow-is-minimized、allow-is-maximized、allow-is-focused、allow-is-decorated、allow-is-resizable、allow-is-maximizable、allow-is-minimizable、allow-is-closable、allow-is-visible、allow-is-enabled、allow-title、allow-current-monitor、allow-primary-monitor、allow-monitor-from-point、allow-available-monitors、allow-cursor-position、allow-theme、allow-is-always-on-top、allow-activity-name、allow-scene-identifier、allow-internal-toggle-maximize。

**不含**写类权限。逐项校验输出（scratch/acl_check.py）：

    allow-set-ignore-cursor-events: False
    allow-start-dragging:           False
    allow-set-position:             False
    allow-set-always-on-top:        False

影响：点击穿透在真实 Tauri 环境下被 ACL 拒绝，catch 分支只 console.warn → 用户无任何错误提示，功能静默失效。

修复归属：PR-030/031（集中 window logic）。R04 不修（不在切片范围）。

备注：acl-manifests.json 中确实**存在** allow-set-ignore-cursor-events / allow-start-dragging / allow-set-position / allow-set-always-on-top 四个权限项，因此修复只需在 capability 中显式列出，不需要自定义权限。

### 1.3 multi-monitor DPI/scale —— N/A

本机只有 1 台显示器（\\.\DISPLAY5 1707x1067，primary=True）。跨显示器拖动时的 scale factor 变化、第二显示器上的位置/尺寸换算、monitor work area 差异**无法在本环境验证** → 标 N/A，不是 PASS。

可验证的相邻事实：core:window:default **已授予**只读探测能力 allow-current-monitor / allow-primary-monitor / allow-available-monitors / allow-monitor-from-point / allow-scale-factor；写类 allow-set-position **未授予**（见 1.2）。

计划要求（§8.3 + L1704）：位置恢复前先 clamp 到当前 monitor work area，并提供 Reset Position。**当前实现无 clamp**（全仓无 available_monitors / current_monitor 调用）。

### 1.4 drag/lock —— 失败（静默失效）

拖动：useWindowGeometry.ts:39-50 startDragging()；UI 入口 CharacterView.vue:10（锁定）。
重置位置：useWindowGeometry.ts:26-37 resetPosition() → setPosition(new LogicalPosition(100, 100))；UI 入口 CharacterView.vue:21（"重置窗口位置"）。
锁定：useWindowGeometry.ts:22 toggleLock() 只翻转前端 ref isLocked，**不调用任何 Tauri API**；startDrag 在 :40 检查 isLocked 后 return。

与 1.2 同根因：allow-start-dragging 与 allow-set-position 未授予 → 真实环境下拖动与重置位置静默失效。
语义缺陷：锁定仅是前端行为约定，未反映到窗口属性（未移除拖动区、未改 setIgnoreCursorEvents）。

### 1.5 crash/restart geometry restore —— 失败（未实现）

- apps/desktop-shell/src-tauri/src/settings.rs 的 AppSettings / PublicAppSettings **无** geometry/position/monitor/dpi 字段（字段仅 llm/asr/tts/character/vram/dormancy 相关）。
- 全仓 Rust 源码检索 set_position | outer_position | current_monitor | available_monitors | clamp：**零命中**（本会话重新检索确认）。
- 窗口重建路径 tray.rs:336 show_or_create_pet_window() 只设固定 .inner_size(360.0, 520.0)，不读取任何持久化位置。

结论：崩溃/重启后窗口位置必然回到默认，且无 clamp 逻辑 → 计划 §8.3 的 "crash/restart geometry restore" 与 "位置恢复前 clamp 到当前 monitor work area" **均为真实缺口**，归 PR-030/031。

### 1.6 taskbar/tray behavior —— 部分实现（静态证据），交互 未验证

- 托盘：tray.rs:85 TrayIconBuilder::with_id("lva-tray")；菜单项（tray.rs:47-59）含 显示/休眠、Chat、Memory、Model、Settings、Live、Screenpipe 状态、服务状态、显示风格、退出。
- 任务栏：四处窗口构造均 skip_taskbar(false)（tray.rs:180 / :224 / :268 / :357）→ 宠物窗会出现在任务栏。
- 休眠语义：tray.rs:317-320 真正 window.destroy()（销毁 WebView2 实例），唤醒时 show_or_create_pet_window 重建 —— 真休眠，不是隐藏。
- 未验证：托盘图标在任务栏溢出区的实际显示、右键菜单实际弹出、多显示器下托盘行为 → 需 GUI 实证，标 未验证。

### 1.7 WebView2 reload and event reconnection —— 失败（未实现）

- Tauri 2.11.5 Rust 侧**有** reload API：src/webview/webview_window.rs:2389 WebviewWindow::reload()、src/webview/mod.rs:1694 Webview::reload()。
- 但 @tauri-apps/api 2.11.1 的 JS 侧**不导出 reload**：对 node_modules/@tauri-apps/api/**/*.d.ts 全量检索 "reload" 零命中（仅 mocks.js / core.js 的错误文案含 "reloaded" 字样）→ 前端无 reload API 可用。
- 前端亦未使用：apps/desktop-ui/src 全量检索 reload | setIgnoreCursorEvents | startDragging | setPosition | setAlwaysOnTop | listen( → 仅 useWindowGeometry.ts 三处 + App.vue:68 的 unlisten()。
- 事件重连：tauri-bridge.ts:274-284 listenEvent() 用 listen("lva://event", ...) 并返回 unlisten；App.vue:20-69 在 onMounted 订阅、onUnmounted 取消。**无重连/退避/断线检测**。

结论：WebView2 reload 与事件重连**均未实现** → 归 PR-030/031（若需 reload，须由 Rust command 暴露）。

---

## 2. 阻断级发现 R11 —— capability 未授予窗口写权限

事实：
1. capabilities/default.json（218 B）：permissions = ["core:default"]，windows = ["main"]。
2. core:window:default 只含 28 项只读权限（见 1.2）。
3. windows 列表只有 "main" → settings / chat / memory / services 窗口**不被任何 capability 覆盖**。

影响：
1. 宠物窗（main）的 click-through / drag / reset-position 全部静默失效（catch 只 warn）。
2. 其余窗口在 Tauri 2 capability 模型下无 capability 覆盖 → 其依赖 core:* 权限的前端调用同样会被拒。

修复归属：PR-023（capability 骨架）与 PR-030/031（窗口能力落实）；**不在 R04 范围**。本报告只记录事实与证据，未修改 capability。

建议验证方式（供 PR-030/031）：在真实 GUI 环境调用 getCurrentWebviewWindow().setIgnoreCursorEvents(true) 并断言无 PermissionDenied；同时检查 capabilities/default.json 是否显式列出 core:window:allow-set-ignore-cursor-events 等。

---

## 3. 结论与降级策略符合性

| §8.3 项 | 状态 | 归属 |
|---|---|---|
| transparent + always-on-top | 源码已实现 / 运行时 未验证 | PR-030/031 复验 |
| click-through toggle | 失败（capability 未授予，静默失效） | PR-023 + PR-030/031 |
| multi-monitor DPI/scale | N/A（单显示器环境） | 需多显示器环境 |
| drag/lock | 失败（同根因）；lock 仅前端 ref | PR-030/031 |
| crash/restart geometry restore | 失败（未实现，无 clamp） | PR-030/031 |
| taskbar/tray | 静态已实现 / 交互 未验证 | PR-030/031 复验 |
| WebView2 reload + event reconnection | 失败（未实现） | PR-030/031 |

降级策略（计划 §8.3 与 L1704）要求：继续 Tauri v2；Character 降级为有明确锁定状态、可拖动、非 click-through 的小窗口；不换 Electron；位置恢复前 clamp 到当前 monitor work area 并提供 Reset Position。

逐条对照：
- 不换 Electron：**遵守**，无框架切换。
- 非透明、非 click-through 小窗：当前实现**仍是** transparent(true) + always_on_top(true)，且 click-through 入口存在但静默失效 → 若采用降级 UX，PR-030 需显式关闭透明并移除/禁用 click-through 入口。
- 可拖动：startDragging 路径存在但被 ACL 拒绝 → 降级前必须授予 allow-start-dragging，否则"可拖动"不成立。
- clamp + Reset Position：Reset Position 按钮存在（CharacterView.vue:21）但 setPosition 被拒；**clamp 完全缺失**。

判定：降级策略目前**不可直接执行**，需先修 capability（PR-023/030）并实现 clamp（PR-030/031）。

---

## 4. 证据索引

- 源码：tray.rs:336-358、tray.rs:85、tray.rs:47-59、tray.rs:180/224/268/357、tray.rs:317-320、useWindowGeometry.ts:1-60、CharacterView.vue:10,21、App.vue:20-69、tauri-bridge.ts:274-284、settings.rs:15-59、capabilities/default.json
- 生成物：apps/desktop-shell/src-tauri/gen/schemas/acl-manifests.json（68,612 B）
- 工具：X:\Codex\State\visualizations\2026\09\23\01a0cd49-18d6-79c1-afd6-41261b729efe\scratch\acl_check.py（ACL 逐项校验）
- 构建：cargo check EXIT=0（CARGO_TARGET_DIR=X 盘，--offline）
- 环境取证：PowerShell Screen / WindowMetrics / EdgeUpdate 注册表读取




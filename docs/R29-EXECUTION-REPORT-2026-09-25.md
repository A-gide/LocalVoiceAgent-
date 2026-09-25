# R29 执行报告 — PR-023 / PR-024 / PR-025（UI 基础、Controls Island、Settings 契约）

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「然后开始 PR-023/024 和 PR25」
- 计划条文：L1362-1390（PR-023/024/025）、§8.4 UX rules（L987-995）、§8.3 降级策略

---

## 0. 开工前的实际状态（避免重复已完成的工作）

三片的 **UI 骨架此前已经存在**，逐项核对如下：

| 计划要求 | 开工前实况 | 判定 |
|---|---|---|
| PR-023 `apps/desktop-ui/**` root/app/router | 在档：`app/{App.vue,main.ts,router.ts}`、`vite.config.ts`、`tsconfig.json` | ✓ |
| PR-023 消费 codegen types | 在档：`src/generated/lva-ipc.ts`（17,134 B）+ `tools/generate-ipc.mjs` | ✓ |
| PR-023 预注册 routes | 在档：`/`（character）、`/chat`、`/memory`、`/settings`、`/services` | ✓ |
| PR-023 state snapshot / event gap | 在档：`stores/runtime.ts` 有 `lastSequence` gap 检测 + `fetchSnapshot` | ✓ |
| PR-023 window context | 在档：`App.vue` 读 `win.label` 并 `router.replace` 到对应路由 | ✓ |
| PR-024 Controls Island 五项 | 在档：Chat / Mode / Output Mute / Privacy Pause / More | ✓ |
| PR-024 状态 1 秒可辨 | 在档：状态徽章含 icon + 文字 + 颜色（非仅颜色） | ✓ |
| PR-024 unverified privacy 可见 | 在档：`unverified-banner` + tooltip 四分支 | ✓ |
| PR-025 分层 Settings | 在档：6 个 section（General/Model/Hearing/Speech/Privacy/Diagnostics） | ✓ |
| PR-025 write-only secret UX | 在档：`ModelSection` password 输入 + 保存/清除 + configured 状态 | ✓ |
| PR-025 public DTO | Rust `PublicAppSettings` 在档，含 `settings_revision` | ✓ |

**因此本轮不做重复实现**，只处置逐行核对后发现的**三处真实缺口**。

---

## 1. 缺口一：capability 未授予窗口写权限（S-UI-01 的 R11）—— 已修

### 1.1 事实

`docs/S-UI-01-Tauri-Window-Capability-Report-2026-09-23.md` 将此项列为**阻断级发现 R11**：

- `capabilities/default.json`（218 B）只授予 `permissions: ["core:default"]`；
- 而 `core:window:default` 实测**只含 28 项只读权限**（`allow-get-*` / `allow-is-*`）；
- 三个写类权限 `allow-set-ignore-cursor-events` / `allow-start-dragging` / `allow-set-position` **均未授予**；
- `windows` 列表只有 `"main"`，而 `tray.rs` 还创建 `settings` / `chat` / `memory` 窗口 —— **未被任何 capability 覆盖**。

**后果**：`useWindowGeometry.ts` 的三处调用被 ACL 拒绝，而调用点的 `catch` 只 `console.warn`，所以点击穿透、拖动、重置位置**静默失效**；§8.3 的降级策略因此不可执行。

### 1.2 修复

重写 `capabilities/default.json`：

| 项 | 修复前 | 修复后 |
|---|---|---|
| `windows` | `["main"]` | `["main", "settings", "chat", "memory", "services"]` |
| `permissions` | `["core:default"]`（12 → 1 项） | `core:default` + 11 项显式窗口权限 |

新增的 11 项权限**逐条对应 UI 的实际调用**，而非笼统放开：

| 权限 | 对应调用点 |
|---|---|
| `core:window:allow-start-dragging` | `useWindowGeometry.startDrag()` |
| `core:window:allow-set-position` | `useWindowGeometry.resetPosition()` |
| `core:window:allow-set-ignore-cursor-events` | `useWindowGeometry.toggleClickThrough()` |
| `core:window:allow-set-always-on-top` | 置顶切换 |
| `core:window:allow-current-monitor` / `-primary-monitor` / `-available-monitors` | PR-030 的 monitor clamp 需要读取工作区 |
| `core:window:allow-scale-factor` | DPI 换算 |
| `core:window:allow-inner-size` / `-outer-position` | 几何恢复 |
| `core:window:allow-set-focus` | 窗口唤起 |

### 1.3 一个被构建抓出的错误（记录在案）

我第一版把说明写在自定义的 `"comment"` 数组键里。PowerShell 的 `ConvertFrom-Json` **接受**该文件（含尾随逗号），但 Tauri 的解析器**拒绝**：

```
failed to parse JSON: trailing comma at line 16 column 3
```

**教训**：本地用 PowerShell 校验 JSON 不足以证明 Tauri 能读。已改为合法 JSON，并把说明并入 `description` 字符串。新增 RED 含尾随逗号检测以固化此点。

### 1.4 验证

- `cargo check --offline` **Finished**（EXIT=0）—— 证明 capability 被 Tauri 接受；
- `cargo test --lib` → **67 passed / 0 failed / 1 ignored**，`stray_ping=0`（无回归）；
- 新增 `tests/red_v121/test_red_window_capability.py`（5 项，全绿）。

### 1.5 仍未验证（诚实边界）

**运行时行为未验证**：本环境无 GUI 自动化能力，无法断言「真实 Tauri 环境下 `setIgnoreCursorEvents` 返回成功」。ACL 层面已不再拒绝，但运行时表现仍需 GUI 实证。S-UI-01 报告 §1.1/§1.6 的「未验证」项同理。

---

## 2. 缺口二：前端 settings DTO 与 Rust 契约漂移 —— 已修

### 2.1 事实（本轮发现）

`get_public_settings` 是 Tauri 命令，**WebView 看不到它的 schema**，TypeScript 只能对照手写 interface 检查。Rust 实际返回：

```
cloud_api_key_configured / asr_api_key_configured / tts_api_key_configured
settings_revision, llm_mode, active_character, ...
```

而前端 `tauri-bridge.ts` 声明的是：

```
has_openai_key / has_screenpipe_key / autostart
```

**这三个字段线上都不存在**。后果：

1. `ModelSection.vue` L49-50 读 `settings?.has_openai_key` **恒为 `undefined`** → **无论配置了多少密钥，UI 永远显示「未配置」**；
2. `autostart` 恒为 `undefined`（实际来自独立的 `get_autostart_status` 命令，`settings.ts` L23 已正确调用，故该字段在 DTO 里纯属多余）；
3. `settings_revision` 未暴露 → 前端**无法**为 settings 写操作提供 CAS precondition（计划 L397）。

这正是 PR-025 要求呈现的「configured flag」（L1387）——配置了的密钥与未配置的在 UI 上**不可区分**。

### 2.2 修复

- `tauri-bridge.ts` 的 `PublicAppSettings` 改为**逐字段镜像** Rust DTO（17 个字段，含 3 个 `*_configured` 布尔与 `settings_revision`）；
- mock 分支同步（`mockInvoke` 的 `get_public_settings` 返回值）；
- `ModelSection.vue` 改读 `cloud_api_key_configured`；
- 加注释说明该接口必须与 Rust 保持一致、以及为何 `autostart` 不在此 DTO 内。

### 2.3 验证

- 新增 `tests/red_v121/test_red_settings_dto_parity.py`（4 项，全绿）；
- `vue-tsc --noEmit` EXIT=0；
- `vite build` EXIT=0（88 modules transformed）。

**该 RED 修复前 4 项全红**（确认缺陷真实存在），修复后全绿。

---

## 3. 缺口三：Output Mute 只改前端本地状态 —— 未修，记录待裁决

### 3.1 事实

`stores/runtime.ts` 的 `setMuted()` 只写 `state.value.playback.muted = muted`（**本地 ref**），不发送任何命令；`ControlsIsland.vue` 的 `toggleMute()` 调用它。

后端**没有任何 mute 通道**：

- `contracts/commands.py` 无 mute/playback 命令；
- `pipeline.py` 的 `self.muted` 只在构造时由 `C.MUTE`（环境变量）决定，**运行时不可改**；
- 全仓 `.muted` 写入点仅 `pipeline.py` L221（构造）与 L297（上报）。

**后果**：点击 Output Mute 只改变 UI 图标与 `playback.muted` 字段，**实际播放不停止**。计划 L1377 要求「Output Mute 立即 stop/suppress playback」，L321 要求「只立即停止并抑制 speaker playback」。

### 3.2 为何本轮不修

修复需要**新增命令类型**（例如 `playback.set_muted`）→ 改 `contracts/commands.py` → 重跑 codegen → **三个生成制品哈希变化** → 触发**硬约束 5**，需用户单独授权。这与 PR-020 的 `capture.ack` 是同一类闸门。

**现有 RED（`test_red_output_mute.py`）已全绿**，因为它只断言「handler 不调用 setMode」「标签是 Output Mute」「tooltip 说明 mic 不变」「store 有 setMuted」——**没有断言音频真的停止**。这是第四次同型现象（测试绕过了真实行为路径），记录在案。

**待裁决**：是否授权新增 playback mute 命令（动契约 + codegen）。

---

## 4. 验证汇总（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 新增 capability RED | `pytest tests/red_v121/test_red_window_capability.py` | **5 passed** |
| 新增 DTO parity RED | `pytest tests/red_v121/test_red_settings_dto_parity.py` | **4 passed**（修复前 4 failed） |
| red_v121 全套 | `pytest tests/red_v121 -q` | **289 passed / 0 failed**（R28 为 280，+9） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 47 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| 前端 typecheck | `npx vue-tsc --noEmit` | EXIT=0 |
| 前端 build | `npx vite build` | EXIT=0，88 modules |
| Rust 单测 | `cargo test --lib`（manifest 脚本） | **67 passed / 0 failed / 1 ignored**，stray_ping=0 |
| Rust 编译 | `cargo check --offline` | Finished（capability 被接受） |

**逐文件哈希（SHA256）**：

| 文件 | 字节 | SHA256 |
|---|---|---|
| `apps/desktop-shell/src-tauri/capabilities/default.json` | 1,010 | 见提交 |
| `apps/desktop-ui/src/bridge/tauri-bridge.ts` | 9,714 | 见提交 |
| `apps/desktop-ui/src/features/settings/ModelSection.vue` | 4,381 | 见提交 |
| `tests/red_v121/test_red_window_capability.py` | 4,467 | 见提交 |
| `tests/red_v121/test_red_settings_dto_parity.py` | 4,160 | 见提交 |

**零契约改动**：`contracts/` 未触碰，三个生成制品字节未变（已核 `git status` 无 gen 变更）。

---

## 5. 未闭环 / 待裁决

| 项 | 状态 |
|---|---|
| **Output Mute 真实停播** | **未修**。需新增命令 → 契约 + codegen → 硬约束 5 授权（见 §3） |
| **capability 运行时实证** | 未验证（无 GUI）。ACL 层已通，运行时行为需真实 GUI |
| **PR-030 monitor clamp** | 未实现。权限已授予，`clamp` 逻辑仍缺失（S-UI-01 §1.3 记录）；归 PR-030 |
| **PR-031 窗口几何持久化** | 未实现（`AppSettings` 无 geometry 字段，S-UI-01 §1.5）；归 PR-031 |
| **WebView2 reload / 事件重连** | 未实现（S-UI-01 §1.7）；归 PR-030/031 |
| **PR-025 L463 全合规** | 仍挂起（`settings_revision` 进 command 签名需硬约束 5 授权） |
| **`_enc` 密钥轮换** | 仍挂起 |

---

## 6. 提交范围

- `apps/desktop-shell/src-tauri/capabilities/default.json`（R11 修复）
- `apps/desktop-ui/src/bridge/tauri-bridge.ts`（DTO 对齐）
- `apps/desktop-ui/src/features/settings/ModelSection.vue`（读正确字段）
- `tests/red_v121/test_red_window_capability.py`（新增 5 项）
- `tests/red_v121/test_red_settings_dto_parity.py`（新增 4 项）
- 本报告

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪）、`apps/desktop-ui/dist/**`（构建产物，已 gitignore）。


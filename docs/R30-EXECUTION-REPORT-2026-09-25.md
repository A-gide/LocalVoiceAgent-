# R30 执行报告 — Output Mute 端到端 + 窗口几何（PR-024 / PR-030 / PR-031）

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「直接做完吧」（含契约改动与 codegen 授权）
- 计划条文：L989 / L321 / L1377（Output Mute）、L1432-1440（PR-030）、L1442-1450（PR-031）、§8.3 / 风险 L1704

---

## 1. Output Mute 端到端（此前只改前端本地状态）

### 1.1 问题（R29 记录）

`setMuted()` 只写 Pinia 本地 ref；`contracts/commands.py` 无 mute 命令；`pipeline.py` 的 `self.muted` 只在构造时由环境变量决定。**点击 Output Mute 音频实际不停**，违反 L1377「立即 stop/suppress playback」。既有 RED 全绿，因为它只断言 handler 不调 `setMode`、标签正确，**从未断言声音停止**。

### 1.2 契约改动（硬约束 5，已获授权）

新增 `PlaybackSetMutedPayload`（`type: "playback.set_muted"`，字段 `muted: bool`），并加入 `CommandPayload` union。

- `codegen.py` 的 `EXPECTED_SCHEMA_SHA256` **按设计流程重新 pin**：`050a260d…` → `cdfc93e0…`，注释记录了变更原因（PR-024 授权）；
- 重跑 `python -m lva.contracts.codegen`，三个制品全部重写：

| 制品 | 旧 | 新 |
|---|---|---|
| `schemas/lva-ipc-v1.json` | 56,691 B / `63842843…` | 57,730 B / `363331DD735CE6204C791AC12CF3BFDDDBEF2EE0C1A445285D9ADE19174DB354` |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 17,134 B / `CF20FA5D…` | 17,733 B / `3F1C99B1B79F81BD2D0034AE4B4DFCAEAAB660CCF7C1A45B59439CC1BB7A06FF` |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 79,775 B / `7EB7D033…` | 80,980 B / `764CC19E8D7DE20519C10FBA907EDA2991E534157E29F1AE3E4281CF41FAE59D` |

- `codegen --verify` 三制品 **verified**（确认制品与生成器一致，非手改）。

### 1.3 三处实现

**契约**：`PlaybackSetMutedPayload`，docstring 记录「只停扬声器播放，不动采集」。

**Core 派发**（`runtime.py`）：新增 `on_playback_mute` 回调（与 `on_interrupt_action` 同形——Core 持有意图但不持有 player 引用），新增 `playback.set_muted` 分支。

- **任何模式都不禁止**（它是输出控制，不是模式控制）；
- 回调抛异常 → 返回 `rejected` + `PROVIDER_DISCONNECTED`，**且不写 `_playback.muted`**（沿用 L1338「不报告未达成的状态」）；
- 成功才写状态并递增 `snapshot_version`。

**player**（`audio.py`）：`Player` 与 `NullPlayer` 各加 `set_muted` / `muted`：

- 进入 mute **先 flush**（generation bump 才是真正停声的机制，drain 只释放内存）；
- **mute 期间 `play()` 直接丢弃而非入队**——入队会让后续 unmute 播放用户已经静音掉的语音，是意外行为；
- `NullPlayer` 保持与真实 player 相同语义，使测试走产品路径而非测试专用简化路径。

**接线**（`server.py`）：`_set_playback_muted` 施加到真实 player，注入 `RuntimeController`。

**前端**（`stores/runtime.ts`）：`setMuted` 改为发送 `playback.set_muted`，本地赋值降级为乐观回显；命令被拒或抛错时**回滚本地状态并记 `lastError`**（不显示未发生的静音）。

### 1.4 RED 登记

`test_red_contract_cas.py` 的三处冻结清单（`CAS_FREE` / `PAYLOAD_CLASS` / `MINIMAL_PAYLOAD`）登记 `playback.set_muted`，注释说明为何**无需 CAS**：它是输出控制，没有会被并发覆盖的 aggregate。这三项修复前正是失败项（`extra=['playback.set_muted']`），是契约变更的登记点。

### 1.5 验证

新增 `tests/red_v121/test_red_playback_mute_command.py`（**10 项**，修复前因缺 payload 类而收集失败）：

| 覆盖 | 断言 |
|---|---|
| 命令而非本地 ref | 意图到达 dispatcher |
| 状态来自 Core | `playback.muted` 双向可读 |
| 幂等 | 重复 mute 仍 applied |
| **不动采集** | mode / mic_capture / privacy_scope / managed_capture 全部不变 |
| 四模式均可 | standby/passive/live/privacy_pause 都不拒绝 |
| **音频真停** | mute 后 `pending() == 0`；unmute 不重放 |
| 通知 owner | 回调按序收到 `[True, False]` |
| **失败不谎报** | 回调抛异常 → `rejected` 且 `playback.muted` 保持 False |
| UI 发送命令 | store 的 `setMuted` 含 `sendCoreCommand` + `playback.set_muted` |

---

## 2. PR-030 窗口几何 clamp（此前完全缺失）

### 2.1 问题

S-UI-01 §1.3 记录：「计划要求位置恢复前先 clamp 到当前 monitor work area……**当前实现无 clamp**（全仓无 available_monitors / current_monitor 调用）」。风险 L1704 把「DPI/恢复失败」列为需 PR-030/031 集中处置项。

### 2.2 实现

新增 `apps/desktop-ui/src/composables/window/geometry.js`（纯 ESM，Node 可执行）+ `geometry.d.ts` 类型声明：

| 函数 | 语义 |
|---|---|
| `clampToWorkArea` | 窗口**整体**留在工作区内（不是仅相交——只剩几像素的窗口可达但不可用）；窗口大于工作区时**钉到原点**（两端都 clamp 会在边界间振荡） |
| `isInsideWorkArea` | 判断是否需要 clamp，使健康位置**逐字节还原**而非被取整微调 |
| `chooseWorkArea` | 优先窗口所在显示器 → 相交显示器 → primary → 首个 |
| `resolveRestoredPosition` | 恢复决策 + `clamped`/`reason` |
| `parseSavedGeometry` | 防御性解析：畸形记录**降级为 null** 而非抛错（配置文件是用户数据，损坏不应导致启动无窗口） |

`useWindowGeometry.ts` 接线：monitor 查询走 `@tauri-apps/api/window` 的模块级函数（`availableMonitors` / `primaryMonitor`——**不在 `WebviewWindow` 上**，这是 typecheck 抓出的）；`placeClamped` 统一 clamp 路径；`resetPosition` 也走 clamp（固定 100,100 在工作区起点非 0 的显示器上会出屏）。

### 2.3 验证

`tests/red_v121/test_red_window_geometry.py`（**12 项**，修复前 12 全红）：含左/右出屏、区内不动、**负坐标副显示器不被推到 0**、超大窗口钉原点、显示器消失回落 primary、健康位置不调整、六种畸形记录全部降级、composable 确实引用该模块。

**一个实现错误由测试抓出**：初版用 `import * as g from "E:/…"` 绝对路径，Node 报 `ERR_UNSUPPORTED_ESM_URL_SCHEME`——Windows 上绝对 ESM specifier 必须是 `file://` URL。已改用 `Path.as_uri()`。

---

## 3. PR-031 窗口几何持久化

### 3.1 实现

新增 `apps/desktop-shell/src-tauri/src/geometry.rs` + 三个命令：

| 命令 | 用途 |
|---|---|
| `get_window_geometry` | 返回已保存几何或 `null` |
| `set_window_geometry` | 持久化；**拒绝退化记录**（存了会让下次启动恢复出看不见的窗口） |
| `clear_window_geometry` | 忘记记录（Reset Position 用） |

**为何独立文件而非塞进 `AppSettings`**：窗口几何不是设置 UI 编辑的偏好；放进 `AppSettings` 会让每次移动窗口都成为一次 settings 写入，**递增 `settings_revision` 并作废用户正在进行的设置编辑**。这是与既有 settings CAS 语义的直接冲突，故独立。

**写入位置**：`paths::get_app_dir()`（PR-003 建立的每用户运行时根），与 `settings.json` 同级。

**容错**：读取失败/畸形/非有限值一律返回 `None`（回落默认位置），**绝不因便利文件损坏而让启动失败**。

### 3.2 前端接线

- `tauri-bridge.ts` 新增 `SavedWindowGeometry` 类型与三个方法；
- `useWindowGeometry` 新增 `restoreSavedGeometry` / `persistCurrent`；**clamp 发生时回写修正后的位置**（否则下次启动会重复同一次 clamp）；
- `resetPosition` 调 `clear_window_geometry`（否则保存的位置会立刻把窗口放回原处，重置不生效于重启）；
- `CharacterView.vue` 在 `onMounted` 先恢复几何再取快照。

### 3.3 验证

Rust 新增 4 项单测（正常记录可用、非有限/零尺寸不可用、**负坐标仍合法**（左侧显示器）、退化记录拒绝写入）。

---

## 4. 验证汇总（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 新增 mute RED | `pytest tests/red_v121/test_red_playback_mute_command.py` | **10 passed**（修复前收集失败） |
| 新增几何 RED | `pytest tests/red_v121/test_red_window_geometry.py` | **12 passed**（修复前 12 failed） |
| red_v121 全套 | `pytest tests/red_v121 -q` | **311 passed / 0 failed**（R29 为 289，+22） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 47 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| codegen | `python -m lva.contracts.codegen --verify` | 三制品 **verified** |
| 前端 typecheck | `npx vue-tsc --noEmit` | EXIT=0 |
| 前端 build | `npx vite build` | EXIT=0 |
| Rust 单测 | `cargo test --lib`（manifest 脚本） | **71 passed / 0 failed / 1 ignored**（R29 为 67，+4），stray_ping=0 |

---

## 5. 未闭环 / 诚实边界

| 项 | 状态 |
|---|---|
| **Output Mute 真实音频** | **未在真实声卡上验证**。测试用 `NullPlayer`（与真实 player 同语义）与真实 dispatcher；没有对真实扬声器断言静音 |
| **窗口几何运行时行为** | **未验证**。clamp 算术由 Node 实测、Rust 持久化由单测覆盖；真实 Tauri 下的 `setPosition`/monitor 查询结果需 GUI 实证（S-UI-01 的「未验证」项同理） |
| **多显示器场景** | 本机单显示器，`chooseWorkArea` 的多显示器分支只有 Node 级证据 |
| **WebView2 reload / 事件重连** | 仍未实现（S-UI-01 §1.7）；归 PR-030/031 的剩余面 |
| **拖动结束后的位置回写** | 未接。`persistCurrent` 已就绪，但没有挂到窗口 move 事件 |
| **capability 运行时实证** | 仍未验证（无 GUI） |
| **L463 全合规** | 仍挂起。settings CAS 属 Rust 边界（既有 RED 已裁定），需在 Rust 命令签名加 revision 参数 |
| **`_enc` 密钥轮换** | 仍挂起 |

---

## 6. 提交范围

**契约与生成物**：`src/lva/contracts/commands.py`、`src/lva/contracts/codegen.py`（重新 pin）、三个生成制品。

**实现**：`src/lva/core/runtime.py`、`src/lva/audio.py`、`src/lva/server.py`、`apps/desktop-shell/src-tauri/src/geometry.rs`（新）、`lib.rs`、`apps/desktop-ui/src/stores/runtime.ts`、`bridge/tauri-bridge.ts`、`composables/window/{geometry.js,geometry.d.ts,useWindowGeometry.ts}`、`features/character/CharacterView.vue`。

**测试**：`tests/red_v121/test_red_playback_mute_command.py`（新）、`test_red_window_geometry.py`（新）、`test_red_contract_cas.py`（登记新命令）。

**报告**：本文件。

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪）、`apps/desktop-ui/dist/**`（构建产物）。


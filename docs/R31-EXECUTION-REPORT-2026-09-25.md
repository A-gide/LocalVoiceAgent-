# R31 执行报告 — 窗口持久化 / 事件重连 / L463 全合规

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「直接做完吧」
- 计划条文：§8.3 / 风险 L1704（窗口）、L463（settings 写命令 revision）、L1173（PR-004）、L1442-1450（PR-031）

---

## 1. 窗口位置回写（S-UI-01 §1.5 的剩余面）

### 1.1 问题

R30 教会了 shell **恢复**位置，但**从未写回**位置——即使有恢复逻辑也没有东西可恢复。用户精心摆好的窗口每次重启都回到默认点。

### 1.2 实现

`useWindowGeometry` 新增：

| API | 语义 |
|---|---|
| `watchPosition()` | 订阅 `onMoved` + `onResized`，返回 unlisten |
| `persistCurrentDebounced(400ms)` | **防抖**写入——拖动每帧发一次 move 事件，逐次写会在一秒内重写配置文件数百次 |
| `persistCurrent()` | 立即写入当前位置 |

`CharacterView.vue` 在 `onMounted` 恢复几何后启动 `watchPosition`，并立即 `persistCurrent()` 一次（**崩溃重启不会产生 move 事件**，没有这次写入就没有可用记录）；`onUnmounted` 释放订阅。

**为何存原始位置而非 clamp 后的位置**：clamp 需要当前显示器列表，而那是**下一次启动**才知道的事；在本次会话里预先 clamp 会丢失用户的真实意图。

---

## 2. 事件重连（S-UI-01 §1.7 的剩余面）

### 2.1 问题

`listenEvent` 是**一次性**订阅：WebView 一旦重载（开发服务器刷新、渲染进程崩溃），订阅静默消失，UI 继续渲染陈旧状态且**没有任何错误可察觉**。

### 2.2 实现

`tauri-bridge.ts` 新增模块级 `eventSubscription` 与 `ensureEventSubscription(callback)`：

- **幂等**：再次调用先释放旧监听器，再建立新的——否则每次重载都会叠加一个监听器，**每个事件被处理两次**；
- 返回 unlisten，归调用方管理生命周期；
- `App.vue` 改走该路径。

---

## 3. L463 全合规（settings 写命令带 revision precondition）

### 3.1 权威判定（沿用既有 RED 裁定）

`test_red_contract_cas.py::test_settings_commands_are_boundary_owned_not_core_enforced` 已裁定：settings CAS **属 Rust 边界**，不进 Core 全局 RuntimeState CAS（§4.2 L397 + 权威矩阵 L293）。因此 L463 的正确实现位置是 Rust 命令层，不是 Python dispatcher。

### 3.2 实现

`settings.rs`：

- `set_secret_checked(secret_type, secret_value, expected: Option<u64>)` —— **先 `check_revision` 再写入**；
- `clear_secret_checked(secret_type, expected)` —— 同一守卫；
- 原有 `set_secret` / `clear_secret` 保留为 `expected = None` 的薄封装（不破坏既有测试）。

`lib.rs`：`set_secret` / `clear_secret` 命令新增 `settings_revision: Option<u64>` 参数。

`tauri-bridge.ts` + `stores/settings.ts`：写入时引用 UI 最后读到的 `settings_revision`；未读过时传 `null`（文档化的首写情形）。

### 3.3 验证

新增 2 项 Rust 单测：

| 测试 | 断言 |
|---|---|
| `a_secret_write_is_guarded_by_the_revision_it_quotes` | 陈旧 revision → `STALE_REVISION` **且值未被替换**；引用当前 revision 则成功 |
| `clearing_a_secret_is_guarded_the_same_way` | 被拒的清除**保留原密钥** |

---

## 4. 验证汇总（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 新增持久化/重连 RED | `pytest tests/red_v121/test_red_window_persistence_and_reconnect.py` | **6 passed**（修复前 4 failed） |
| red_v121 全套 | `pytest tests/red_v121 -q` | **317 passed / 0 failed**（R30 为 311，+6） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 47 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| 前端 typecheck | `npx vue-tsc --noEmit` | EXIT=0 |
| 前端 build | `npx vite build` | EXIT=0 |
| Rust 单测 | `cargo test --lib`（manifest 脚本） | **73 passed / 0 failed / 1 ignored**（R30 为 71，+2），stray_ping=0 |

**零契约改动**：本轮未触碰 `contracts/`，三个生成制品字节未变。

---

## 5. 一处测试断言修正（记录在案）

我最初的 RED 断言 `CharacterView.vue` 必须出现 `onMoved`/`onResized`。实际订阅在 composable 中（Tauri API 调用属于那里），视图的职责是**启停**该订阅。断言改为检查 `watchPosition` + `persistCurrent`——测试应断言职责归属，而非实现细节的落点。

---

## 6. 未闭环 / 诚实边界

| 项 | 状态 |
|---|---|
| **窗口几何运行时行为** | **未验证**。clamp 算术经 Node 实测、持久化经 Rust 单测；真实 Tauri 下的 `setPosition`/monitor 查询/`onMoved` 触发需 GUI 实证 |
| **多显示器场景** | 本机单显示器，多显示器分支只有 Node 级证据 |
| **WebView2 主动 reload** | 未实现。重连路径已就绪（重载后重新订阅即可），但触发 reload 本身需 Rust 暴露命令（S-UI-01 §1.7 指出 JS 侧无 reload API） |
| **L463 的 UI 层冲突提示** | 未做。`STALE_REVISION` 会冒泡到 `lastOpMessage`，但没有「刷新后重试」的引导 UI |
| **Output Mute 真实音频** | 未在真实声卡上验证（R30 边界延续） |
| **capability 运行时实证** | 仍未验证（无 GUI） |
| **`_enc` 密钥轮换** | 仍挂起（需密钥所有者判断） |
| **Hub 放行路径探针** | 仍未运行（需用户在沙箱外启动 Hub） |

---

## 7. 提交范围

**实现**：`apps/desktop-ui/src/composables/window/useWindowGeometry.ts`、`features/character/CharacterView.vue`、`bridge/tauri-bridge.ts`、`app/App.vue`、`stores/settings.ts`、`apps/desktop-shell/src-tauri/src/settings.rs`、`lib.rs`。

**测试**：`tests/red_v121/test_red_window_persistence_and_reconnect.py`（新）。

**报告**：本文件。

**明确排除**：21 项 ` D` 删除类、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`、`apps/desktop-ui/dist/**`。


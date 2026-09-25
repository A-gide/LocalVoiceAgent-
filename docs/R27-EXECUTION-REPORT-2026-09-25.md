# R27 执行报告 — PR-021 LVA-managed Screenpipe capture executor

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「继续」；冻结计划 L1340-1348（PR-021）

---

## 1. 计划条文与开工前实况

### 1.1 权威条文（逐字核验）

| 行 | 内容 |
|---|---|
| L1342 | Branch / owner: `shell/managed-capture-executor` / B |
| L1343 | Current → target: Screenpipe 状态与 Privacy 模式无闭环 → **仅对 Spawned/受支持 Adopted 实例执行并回执** |
| L1344 | Files/new: `managed_capture.rs`；service registry/bridge integration |
| L1345 | Steps: **capability probe**；按 Standby/Passive/Live setting/Privacy Pause 执行 pause/stop/resume；**operation id ack**；**External/Unknown 只报告不可控** |
| L1346 | Dependencies: PR-005/007/020；与 UI feature 并行 |
| L1347 | Tests: Standby/Privacy managed 实例成功停录，Passive 成功恢复，Live 尊重 setting；**external 实例不 kill**；**ack timeout/失败准确反映** |
| L1348 | Rollback: **禁用 executor 后保持 `UNVERIFIED`**；**不自动杀 Screenpipe** |

### 1.2 开工前实况

`managed_capture.rs` 是 **2026-09-21 的遗留 stub**（2,131 B）：只有一个 `pause_managed_capture()`，无 capability、无 intent、无 operation id、无 resume，且 **全库零调用方**——R08 审查时已记录为「无写者无读者」。

与计划要求的差距：

| 计划要求 | 开工前 | 判定 |
|---|---|---|
| capability probe | 无。只按 `get_ownership` 分派 | ✗ |
| pause / stop / resume | 只有 pause（= stop）；**无 resume** | ✗ |
| operation id ack | 无 operation 概念 | ✗ |
| External/Unknown 只报告不可控 | External 报 `managed=None` + `external=true`（方向对）；Unknown 报 `managed=None` + `external=false`，**与「无实例」不可区分** | 部分 |
| 失败准确反映 | 有 `error` 字段，但 `managed_screenpipe_stopped` 在 `Ok(false)` 分支被填 `Some(false)`，未区分「拒绝停」与「停失败」 | 部分 |
| 接线 | 零调用方（死代码） | ✗ |

---

## 2. 实现

### 2.1 三个显式类型替代布尔组合

| 类型 | 取值 | 用途 |
|---|---|---|
| `CaptureCapability` | `Controllable` / `Uncontrollable` / `Unknown` | LVA 能否驱动这个实例 |
| `CaptureIntent` | `Stop` / `Resume` | Core 要求的目标状态 |
| `CaptureExecutionStatus` | `Applied` / `Uncontrollable` / `Failed` | 实际结果 |

`CaptureExecutionResult` 携带 `operation_id`（回显 Core 的 id）、`intent`、`status`、`managed_screenpipe_stopped`、`external_screenpipe_detected`、`error`。

**关键语义**：`managed_screenpipe_stopped = None` 是 fail-closed 答案。Core 不得把它读成成功——这直接对应 PR-020 侧 `unsettled_stop_operations()` 压住 verified 的判定。

### 2.2 capability 判定（L1343/L1345）

```
Spawned              -> Controllable   （LVA 自己启动的，按定义可控）
Adopted + 已证明通道   -> Controllable
Adopted + 未证明通道   -> Uncontrollable
External             -> Uncontrollable（只报告，绝不 kill）
Unknown              -> Unknown        （无实例可识别）
```

`CaptureProbe { reachable, version_known }` 的 `controllable()` 要求**两者同时成立**：REST 可达**且**版本已知。只有可达性时判为不可控——因为「能连上」不等于「有受控通道」，把可达当可控正是计划 L1709 要求避免的猜测。

### 2.3 operation-driven，不镜像 mode

executor 接收 `operation_id` + `intent`，**自己不读当前 mode**。理由：Core（PR-020）已经拥有该决策；若 Rust 再按 mode 自行判断，就出现了第二个权威，两者可能漂移——与 R20/R25 修掉的「Hub 端口六处副本」是同一缺陷类。

### 2.4 实现中发现并修正的两个真实缺陷

**缺陷 1（我的设计错误，被测试抓出）**：`Supervisor::stop_spawned()` 成功后会把所有权条目**移除**（既有 supervisor 测试依赖此语义：重复 stop 返回 `Ok(false)`）。因此停掉 Spawned 实例后，supervisor 报 `Unknown`——**与从未见过的实例无法区分**，LVA 永远无法恢复自己停掉的 recorder。这直接违反 L1347「Passive 成功恢复」。

修正：新增 `stopped_by_us` 标志。`capability()` 首判该标志——**LVA 停掉的实例始终是 LVA 自己的**，即使 ownership 条目已被消费。

**缺陷 2（初始实现的谎报）**：Resume 原本无条件返回 `Applied`。若实例是 LVA 停掉的但没有 spawner，这会**宣称一个不存在的 recorder 正在运行**。修正为三分支：

| 情形 | 结果 |
|---|---|
| LVA 从未停过它 | `Applied`（已在运行 / 不归 LVA 管，无需动作，**不 spawn**） |
| LVA 停过它 + 有 spawner | 调 spawner；成功 `Applied`，失败 `Failed` |
| LVA 停过它 + 无 spawner | **`Failed`**（不谎报运行中） |

### 2.5 接线（消除死代码）

- `lib.rs` 新增 `ManagedCaptureExecutor` 到 Tauri state；
- 新增两个命令：`get_capture_capability`（报告 capability + 最近结果）、`execute_capture_operation`（执行一次操作）；
- 新增 `probe_screenpipe_capability()`：3030 可达性检查 + 版本读取。**当前固定返回 `version_known: false`**，理由见 §4；
- `CaptureSpawner` 为注入式 `Arc<dyn Fn() -> Result<(), String>>`：spawn 是 `ProcessManager` 的能力，executor 不得长出第二条 spawn 路径（避免 R25 刚消除的重复）。

---

## 3. 验证（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| Rust 单测 | `cargo test --lib --offline`（经 manifest 修复脚本） | **67 passed / 0 failed / 1 ignored**，`stray_ping=0`，**连跑 2 次稳定** |
| 新增 Rust 测试 | `managed_capture` 过滤 | **12 passed**（含真实 spawn/stop/恢复路径） |
| red_v121 | `pytest tests/red_v121 -q` | **275 passed / 0 failed**（R26 为 274，+1 为新增跨语言守卫） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 43 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| 编译 | `cargo test --lib --no-run` | Finished，**无警告** |

**逐文件哈希（SHA256）**：

| 文件 | 字节 | SHA256 |
|---|---|---|
| `apps/desktop-shell/src-tauri/src/managed_capture.rs` | 22,531 | `8D0369B281CED72E4C88F9550AFD86CEF707CD3048D7F150DA75DCCBB160632A` |
| `apps/desktop-shell/src-tauri/src/supervisor.rs` | 10,759 | `05A749A84DCFCB943083D8766B97C0D08841F959451AE88BB4DAE975F2E386E5` |
| `apps/desktop-shell/src-tauri/src/lib.rs` | 23,663 | `A05F1EE8B904A56A933A78DE36B8CB9BA2342AF6BA9675F972F681CE34489ABD` |
| `tests/red_v121/test_red_cross_language_consistency.py` | 9,185 | `987A885F1BB586AD009E974BED7DA0C27DAA4C77469B566A7491A249181FDBBF` |

**零契约改动**：`contracts/` 未触碰，三个生成制品字节未变。

**新增跨语言守卫**：`test_the_screenpipe_port_agrees_across_languages` —— Rust executor 与 Python importer 必须指向**同一个** Screenpipe 端点。两者不一致会导致「停掉自认为在跑的那个 recorder，却从另一个导入」，与 Hub 端口的双源缺陷同型。

---

## 4. 两处刻意的保守判定（需审查方知悉）

1. **`probe_screenpipe_capability()` 恒返回 `version_known: false`**，故 Adopted 实例**当前一律判为不可控**。理由：executor 尚无 pinned Screenpipe 版本契约（计划 L1709 要求 versioned adapter + capability probe）。在拿到真实 Screenpipe 的 `/version` 响应形状前把版本判定写成「总是已知」，就是又一次用错误假设写夹具（R14 version 信封事故同型）。**真实 Adopted 实例的受控路径因此尚未打通**，属已知边界。
2. **`CaptureSpawner` 未注入**（`ManagedCaptureExecutor::new`，非 `with_spawner`）。故「LVA 停掉 → 恢复」在当前生产接线中会返回 `Failed` 而非真的重启。spawner 注入需要 `ProcessManager::ensure_service_running` 的 `Arc` 共享（它目前归 `tray.rs` 使用），属集成面决定；`with_spawner` 的语义与测试已就绪，接线留待授权。

---

## 5. 未闭环 / 未验证（诚实边界）

| 项 | 状态 |
|---|---|
| **operation id 跨进程回执** | **未接**。executor 已能回显 id 并返回结果，但 Rust→Core 的 `capture.ack` 命令面需新增命令类型 → 改 `contracts/` → 三制品哈希变化 → **硬约束 5，需单独授权** |
| **真实 Screenpipe 实例停止** | **未运行**。测试用 `ping.exe` 哨兵验证真实 spawn/stop/恢复路径；没有对真实 Screenpipe 执行过 stop |
| **真实 Adopted 实例受控** | 未打通（见 §4.1） |
| **ack timeout 端到端** | 未验证。PR-020 侧的 timeout→UNKNOWN 已由 Python 测试覆盖；跨进程的 ack 超时需命令面就绪 |
| **`ProcessManager` 重复所有权模型** | 未处理。`process_manager.rs` 与 `supervisor.rs` 各有一套 ownership 模型（前者仍有 `unload_vram`/`cold_start_llm`/`switch_model` 空壳）。计划 L1288/L1500 将旧 lifecycle 归 PR-015/PR-037 闸门，本片不动 |
| **UI 消费** | 未接。`get_capture_capability` 已暴露，Vue 侧消费属 PR-024（Character/Controls Island，L1377「unverified privacy 可见」） |

---

## 6. 提交范围

本次提交只含 PR-021 相关文件：

- `apps/desktop-shell/src-tauri/src/managed_capture.rs`（重写，2,131 → 22,531 B）
- `apps/desktop-shell/src-tauri/src/supervisor.rs`（新增 `take_child_for_test`）
- `apps/desktop-shell/src-tauri/src/lib.rs`（executor 接线 + 两个命令）
- `tests/red_v121/test_red_cross_language_consistency.py`（新增 Screenpipe 端点守卫）
- 本报告

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪）。


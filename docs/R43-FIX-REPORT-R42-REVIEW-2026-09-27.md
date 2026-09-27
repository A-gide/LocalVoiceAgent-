# R43 修复报告 — R42 复审四项（2026-09-27）

- 执行者：Codex（经用户授权实施、提交、推送）
- 基线：`db943eb`（R42 复审前）→ 当前 `b29aecd`（`main` = `origin/main`，工作树干净）
- 依据：用户 R42 复审裁决的四项发现
- 性质：**执行报告**。不自行宣布总体 GREEN；实机/硬件门禁按事实保持关闭

---

## 1. 四项发现与修复

### P0 — 未知的停止结果被判为隐私 VERIFIED

| 项 | 内容 |
|---|---|
| 问题 | `request_managed_capture_off` 乐观置 `managed_screenpipe_stopped=True`；`acknowledge` 只在 `managed_stopped is not None` 时覆盖，于是 `null`（未知）ack 保留了这个 True，隐私范围被抬到 `VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF` |
| 修复 | `CaptureCoordinator.acknowledge` 一律写入**观测值**（含 `null`）。请求阶段的乐观值会被 ack 的未知覆盖，范围回到未验证 |
| 位置 | `src/lva/core/capture.py` |
| 证据 | `test_red_r43_review_fixes.py::test_an_unknown_stop_result_keeps_the_scope_unverified`；探针：null ack → `scope=LVA_CORE_OFF_EXTERNAL_CAPTURE_UNKNOWN`、`managed=None` |
| 反向 | `test_a_definite_stop_ack_still_verifies_the_scope`：肯定 ack 仍 VERIFIED |

### P1 — 旧 Core 的延迟 ack 可命中新 Core 的同号请求

| 项 | 内容 |
|---|---|
| 问题 | operation id 每次启动从 `cap-1` 重新计数，回传时不带 runtime 身份；两个不同实例可产生同名 `cap-2`，旧请求的 ack 被新 runtime 接受并使范围 VERIFIED |
| 修复 | `CaptureCoordinator` 新增 `instance_token`，由 `RuntimeController` 传入 `runtime_instance_id`；operation id 变为 `<instance>-cap-N`，跨实例不再碰撞 |
| 位置 | `src/lva/core/capture.py`、`src/lva/core/runtime.py` |
| 证据 | `test_an_ack_from_a_previous_runtime_is_refused`；探针：两实例 id 不同，旧 id 的 ack 返回 `rejected` 且范围保持未验证 |

### P2 — FIX-003 空错误消息仍报成功

| 项 | 内容 |
|---|---|
| 问题 | `run_default_turn` 用真值判断 `outcome.failed`；执行器抛出无消息的 `RuntimeError()` 时 `failed == ""`，判定落空，Turn 已取消但命令仍返回 `applied` |
| 修复 | 改为 `if outcome.failed is not None:` |
| 位置 | `src/lva/server.py` |
| 证据 | `test_a_failure_with_an_empty_message_is_still_rejected` |

### FIX-007 — 解析失败不触发子进程清理

| 项 | 内容 |
|---|---|
| 问题 | `core_supervisor.rs` 的 `serde_json::from_str(...)?` 在 READY JSON 非法时直接返回，未走子进程清理（与"每条失败路径均已清理"的主张不符） |
| 修复 | 读取与解析抽成 `await_ready_payload()`：解析失败调用 `on_failure()` 再返回错误；`spawn_core` 经它统一在失败时 `child.kill()` |
| 位置 | `apps/desktop-shell/src-tauri/src/core_supervisor.rs` |
| 证据 | Rust 测试 `a_malformed_ready_payload_fails_and_invokes_cleanup`（连同无输出超时、EOF 前半行、ready 前杂散输出、立即 EOF、成功路径共 6 项） |

---

## 2. 门禁（本轮实测）

```ini
新增 RED tests/red_v121/test_red_r43_review_fixes.py                4 passed
目录集合 pytest tests/{red_v121,unit,invariants,contract,integration,migration,ux,fault}
                                                                  555 passed
九组门禁 tests/run_groups.py --all
  contract 5 / invariants 23 / unit 47 / fault 7 / integration 11
  migration 2 / ux 11 / harness 43 / red-v121 449
  expected-red groups failing: []      all groups passed
ruff check（本轮改动文件）                                          All checks passed
cargo check --offline --lib --tests                                Finished（类型检查通过）
```

---

## 3. 未运行 / 未闭合（诚实记录）

| 项 | 状态 | 原因 |
|---|---|---|
| FIX-007 Rust 行为测试 | **未运行** | 本机 GNU toolchain 的 `dlltool.exe` 是无法创建 import library 的桩（`CreateProcess` 失败），MSVC 缺 `link.exe`；`cargo test --no-run` 在链接阶段失败。`cargo check --lib --tests` 通过，但执行未验证 |
| T05 实机 Screenpipe | **关闭** | 服务未运行 |
| T06 真实 Hub 身份锚点 | **关闭** | 服务未运行 + 需所有者确认实例 |
| T08 硬件性能门禁 | **关闭** | 无设备 / live 模型 |
| 远端 CI 结论 | **未读取** | 本机 `gh` 未认证 |

---

## 4. 本轮环境事件（照实）

实施中途，对 `E:` 仓库的 `apply_patch` 与 `require_escalated` 命令被**自动审批审查**拒绝，返回 `HTTP 402 Payment Required: Insufficient balance`（审查服务余额不足）。该动作未执行，也未绕过审查；期间仅完成了两处已授权的仓库编辑（`capture.py` / `runtime.py`）并做了实测。用户重启审查服务后，其余修复、测试、提交与推送全部完成。

---

## 5. 结论

R42 复审的四项发现均已在代码层修复，其中三项（P0/P1/P2）由走真实入口的 Python RED 覆盖并通过；FIX-007 的解析失败清理已实现并有 Rust 测试，但**该 Rust 测试在此环境无法执行**。

**不宣布总体 GREEN**：FIX-007 的 Rust 行为测试、T05/T06 实机、T08 硬件门禁均未运行。远端 CI 通过也不改变这一结论。

---

## 6. 勘误与补充（2026-09-27，复审 P2）

复审指出：(a) §1 FIX-007 行「`spawn_core` 经它统一在失败时 `child.kill()`」的表述过宽，
应立即收窄到当时只覆盖的 READY 等待与解析路径；(b) `core_supervisor.rs` 在子进程已启动后、
向 stdin 写 bootstrap 失败时直接返回，未终止子进程（P2 待验证）。两条均成立。

### 6.1 已修复的生命周期缺口

`write_bootstrap()` 抽为一个可测试的写入助手：写失败（或 flush 前管道断开）时调用 `on_failure()`，
`spawn_core` 用它 `child.kill()`；`stdout` 管道获取失败同样 `kill`。新增 Rust 测试
`a_bootstrap_write_failure_invokes_cleanup`（用返回 `BrokenPipe` 的假 writer 断言清理回调被调用）。

### 6.2 收窄后的表述（替换 §1 的过宽说法）

`spawn_core` 在**子进程存在之后**的每条失败路径都调用 `child.kill()`，具体为：stdin 管道获取失败、
bootstrap 写入失败、stdout 管道获取失败、READY 等待超时、READY 前 EOF、READY 前杂散输出、
READY JSON 解析失败、`protocol_version` 不符、`nonce` 不符。`spawn` 本身失败时尚无子进程，无需清理。

以上均由 `cargo check --lib --tests` 证实可编译并有对应 Rust 测试；与前几轮相同的限制是：
这些 Rust 测试在本机**无法执行**（toolchain 的 `dlltool` 是不可用的桩、缺 `link.exe`），
因此本条从「类型检查通过」到「行为已验证」仍未完成。

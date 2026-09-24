# R16 执行报告 — PR-012 Rust 侧 attestation 发送端（通道两端齐备）

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第十一片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 范围来源：R15 §5.1 的未完成项（「Rust 侧发送端未实现」）+ 获批设计稿（`docs/PR-012-ATTESTATION-CHANNEL-DESIGN.md`，方案 A）

---

## 0. 本轮闭合了什么

**PR-012 的 attestation 通道现在两端齐备。** R15 完成了 Core 侧接收与门控，本轮补上 Rust 侧发送端——**运行时不再「永远没有 attestation 到达」**。

| 项 | R15 末态 | 本轮末态 |
|---|---|---|
| Rust 侧发送 | **不存在** | `send_bind_attestation()` + `start_attestation_reporter()` |
| 运行时 attestation | 永不送达，门永闭 | 每 30 s 重新报送，门可开启 |
| `tests/red_v121` | 2 failed / 197 passed | **2 failed / 204 passed** |

剩余 2 项红仍全部属 **PR-015（Wave 5）**：`test_rust_exposes_no_direct_model_lifecycle_commands`、`test_legacy_1234_default_is_gone`。

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `apps/desktop-shell/src-tauri/src/lib.rs` | 新增 `REATTEST_INTERVAL = 30s` 常量；新增 `send_bind_attestation(&CoreBridge)`（构造 `hub.attest_bind` 命令、复用 `observe_hub_bind_attestation()` 的 verdict、映射 `AttestationStatus`/`HubBindReason` 到契约字符串、给出 `revalidate_after`、发送并记录结果）；新增 `start_attestation_reporter(Arc<CoreBridge>)`（独立命名线程，周期调用）；在 `setup` 中接线 | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_attestation_sender.py` | **新增 RED 套件**（7 项） | 见 §5 | 见 §5 |

未修改：三个生成制品（**本轮零契约改动**——`hub.attest_bind` 已在 R15 落入契约）、`Cargo.toml`/`Cargo.lock`（**零新增依赖**，`chrono` 与 `uuid` 已在）、`src/lva`（Python 侧在 R15 已完成）、冻结计划与历史报告。

---

## 2. 实现要点

### 2.1 传输路径（与设计稿一致）

```text
lib.rs::start_attestation_reporter   (独立线程, 每 30s)
        |
        +--> send_bind_attestation(&bridge)
                  |
                  +-- observe_hub_bind_attestation()   <- 复用 PR-008 观察器, 不另写探测
                  |
                  +-- bridge.send_command({type:"hub.attest_bind", payload:{type, attestation}})
                            |
                            +--> 既有 authenticated WS --> Core /ws --> RuntimeController
```

**关键点**：发送端**复用** `observe_hub_bind_attestation()`，不写第二套探测逻辑——否则两处结论可能分叉。RED 的 `test_sender_reuses_the_observation_it_already_produces` 断言这一点。

### 2.2 为什么必须周期报送

R15 的门控把 `revalidate_after` 当**截止时刻**。因此**一次性报送是不够的**——verdict 到期后门会自行关闭并保持关闭。本轮以 30 s 周期报送，并给 `VERIFIED_LOOPBACK` 的 verdict 一个 **3 倍周期（90 s）** 的截止时间，使单次丢包不会立刻关门。

**未验证的 verdict 不给任何宽限**（`revalidate_after: None`）：一个无法证明 loopback 的结论不应被允许短暂地授权控制。

RED 的 `test_attestation_is_refreshed_not_sent_once` 守护周期性。

### 2.3 线程与阻塞

`bridge.send_command` 会**阻塞到收到 correlated result**（最长 `COMMAND_TIMEOUT = 10s`）。因此：

- 发送由**独立命名线程** `lva-attestation-reporter` 驱动；
- **不在任何 `#[tauri::command]` handler 内调用**（那会在 WebView IPC 线程上阻塞 UI）。

RED 有两条断言分别守护这两点：`test_sender_does_not_block_the_ui_thread`（存在 spawn 驱动的调用点）与 `test_sender_is_not_called_from_a_tauri_command_handler`（遍历所有 Tauri command 检查）。

### 2.4 失败必须可见

发送失败经 `log::warn!` 记录。**理由**：一个被静默丢弃的 attestation 在 Core 端与「门合法关闭」**不可区分**，会极难诊断。RED 的 `test_sender_failure_is_reported_not_silent` 守护这一点。

---

## 3. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_attestation_sender.py` | 改前 **5 failed / 1 passed** → 改后 **7 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **2 failed / 204 passed**（起始 2F/197P；+7 全为本轮转绿，**无新增红**） |
| Rust 编译 | `cargo check --offline` | **EXIT=0**（1m17s） |
| **Rust 单测全量** | `rusttest.ps1 -SourceExe <test exe>` | **`55 passed; 0 failed; 1 ignored`**，EXIT=0，`stray_ping=0`（与 R11 末态相同，**无回归**） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0 |
| codegen zero-diff | `python -m lva.contracts.codegen --verify` | 三制品全部 `verified`（R15 的新哈希未变） |
| ruff | `ruff check src/lva tests/run_groups.py` | All checks passed |

---

## 4. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| **真实端到端：Rust 发出 -> Core 收到 -> 门开启** | **未验证** | 需真实 Core 进程 + 真实 WS 连接；本轮验证的是**发送端的存在性与形状**，不是它实际送达。R07 的互操作探针模式可复用于此，但需另起探针 |
| 真实 Hub 的 bind 判定（`VERIFIED_LOOPBACK` / `HUB_CONTROL_UNSAFE`） | 未验证 | 本机未运行 llama.cpp-hub；`observe_hub_bind_attestation()` 的真实 `netstat` 路径未在真实 Hub 上取证 |
| `revalidate_after` 的运行时行为（到期后门确实关闭） | **逻辑已测，运行时未测** | Core 侧四态（无/UNVERIFIED/新鲜 VERIFIED/过期 VERIFIED）由 RED 覆盖；Rust 侧的周期与截止时间只在源码层断言 |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

### 4.1 必须说清的边界

**「通道两端齐备」指代码齐备，不指端到端已验证。** 当前状态：Rust 会周期构造并发送 `hub.attest_bind`；Core 能接收并按三条件判定；`cargo check` 与 55 项单测证明 Rust 侧可编译、既有行为无回归。但**没有一次真实送达被观测到**——这需要真实 Core 进程与真实 WS 连接。**不得读作「Hub 控制已端到端可用」。**

---

## 5. 差异报告（只报告，未自行修正）

1. **本轮我自己的一处测试缺陷（已修）**：初版 `_sender_body()` 用 `fn\s+\w*attest\w*` 定位发送函数，结果**先匹配到 `observe_hub_bind_attestation`（观察器）**，导致三条断言在错误的函数体上求值。已改为**按命令字面 `"hub.attest_bind"` 定位**，并在 docstring 中记录了这个陷阱。
2. **另一处测试缺陷（已修）**：初版 `test_sender_does_not_block_the_ui_thread` 断言 `spawn` 出现在**发送函数体内**，这实际上会强迫一个无意义的嵌套 spawn。**正确性质在调用点**——发送函数可以是普通函数，只要有人 spawn 线程驱动它。已改为断言「存在 spawn 驱动的调用点」+「不在 Tauri command handler 内」。
3. **`HUB_CONTROL_PORT = 8089` 仍是硬编码**（R08 §6 已记录）：发送端沿用该常量。若 Hub 端口可配置，此处应改为从配置读取。
4. **`REATTEST_INTERVAL = 30s` 是新增的硬编码常量**：其合理性依赖 Core 侧 `revalidate_after = 3 倍周期` 的配合。两者都是常量而非配置；若将来调整，需同时改两处（Rust 的周期与 Rust 给出的截止时间）——**它们目前都在 `lib.rs` 内相邻定义，便于一并修改**。
5. **发送端不检查 `bridge.get_state().connected`**：未连接时 `send_command` 直接返回 `Err`，由 `log::warn!` 记录。这是刻意的——在未连接时静默跳过会让「Core 从未收到 attestation」难以发现。

---

## 6. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言（§5.1/5.2 的两处修正都是**修正我自己测试的错误定位**，不是放宽产品断言）；未手改三个生成制品（本轮未触碰契约）；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/`；**未执行任何 git 写操作**。**本轮零契约改动、零新增依赖、未申请网络授权、未提权。**

## 7. 下一片

`tests/red_v121` 剩余 **2 项红**，均属 **PR-015（Wave 5）**：

| 项 | 内容 |
|---|---|
| `test_rust_exposes_no_direct_model_lifecycle_commands` | Rust 仍有 `scan_models`/`refresh_models`/`switch_llm_model`/`unload_vram`/`cold_start_llm` |
| `test_legacy_1234_default_is_gone` | `config.py` L47/L60 默认 `127.0.0.1:1234` |

**另有一项建议优先**：**端到端验证 attestation 通道**（起真实 Core + 真实 WS，观测 Rust 发出的 verdict 被 Core 接收并开门）。这是 R15/R16 两轮留下的唯一未验证环节，且它决定「PR-012 是否真的可用」而非仅仅「两端代码齐备」。

PR-013（Hub inference provider）仍待做，且 PR-014 依赖 PR-012/013。

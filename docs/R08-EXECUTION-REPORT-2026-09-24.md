# R08 执行报告 — Wave 2 / PR-008 Service identity and readiness

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第四片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 工作树：`status --porcelain=v1` = **87 行**（起始 85，本轮 +1 新 RED 文件 +1 本报告）；`-uall` = **246 行**（起始 243）
- 范围来源（四处独立一致）：冻结计划 §8.1（L932-944）+ PR-008（L1208-1216）、`tests/red_v121/README.md` 映射表（`test_red_snapshot.py` → §8.1 / PR-008 → Fix slice R08）、`CONTEXT-HANDOFF-2026-09-22.md` 第 5 条、独立审查报告 §四 V1/V2/V3
- 冻结验收原文（L1215）：重启换 PID 不误判；Unknown 不提供 stop；`127.0.0.1-only` / `0.0.0.0` / `::` / 无法映射四类 fixture 分类正确；观测 PID/port 不产生 kill authority；UI/Core 收到 typed service/bind state

---

## 0. 范围判定（为何 R08 不只是 snapshot DTO）

`tests/red_v121/README.md` 把 `test_red_snapshot.py` 映射到「§8.1 / PR-008」，但 PR-008 的标题是 **Service identity and readiness**，不是 snapshot DTO。独立审查报告已用 V1 指出：PR-008 的验收面（service identity、Windows listener table、typed bind attestation、crash reason、redacted diagnostic snapshot）**没有实现、也没有 RED 覆盖**。

因此本轮把 R08 拆成两半：

1. **snapshot DTO 一致性**——`test_red_snapshot.py`（3 项）与 `test_bridge_mock_and_snapshot_version.py`（6 项）在 R03b/R04/R07 期间已顺带转绿，本轮**只复验，不重造**。
2. **PR-008 的 service identity/readiness 面**——本轮的真实工作，见 §2。

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `apps/desktop-shell/src-tauri/src/network_attestation.rs` | **新增**。`BindClass`（四类 listener）、`HubBindReason`、`AttestationStatus`、`HubBindAttestation`（脱敏）、`ListenerRow`、`parse_listener_table()`、`split_host_port()`、`classify()`、`attest_from_rows()`、`attest_for_port()`，含 **10 项单测** | 12,147 | `F621332BA7D2CBBB931923DF80C496E2F79C92F06D625A2D574ED034266271BA` |
| `apps/desktop-shell/src-tauri/src/service_registry.rs` | 由**死代码 stub** 扩为真实实现：新增 `Readiness`（Unknown/Starting/Ready/Degraded/Exited）、`CrashReason`、`ServiceIdentity`（含 `instance_token`、`can_stop()`）、`observe()`、`record_crash()`、`get_identity()`、`get_all_identities()`、`reobserve_after_restart()`；`update_status` 改为兼容投影；`get_all_services` 保留为 PR-038 前的 legacy 投影；含 **10 项单测** | 11,362 | `F1256746DFB13C1A5813F4809406E4FD551E3FB924D0B2111649757140DA5288` |
| `apps/desktop-shell/src-tauri/src/lib.rs` | 新增 `pub mod network_attestation;`、`use serde::Serialize;`；新增 `get_service_identity_status` Tauri command + `ServiceIdentityReport` 类型；新增 `observe_hub_bind_attestation()`（只读 `netstat -ano -p tcp`）与 `HUB_CONTROL_PORT = 8089`；启动时 `observe("lva_core", Starting, Unknown, …)`；`spawn_core` 成功分支写 `Ready/Spawned/instance.runtime_instance_id/port`，失败分支写 `Exited` + `record_crash(HandshakeFailed)`；command 注册进 `generate_handler!` | 15,986 | `5452C2E87DA624210D59D711FD1E7CB3C399564F8AAE5F3864939337BB06A194` |
| `src/lva/bootstrap.py` | 新增 `_announced_instance_id` 单源、`announce_runtime_instance_id()`、`get_announced_runtime_instance_id()`；`emit_lva_ready()` 现在会登记该 id。**复验后追加**：`runtime_instance_id` 默认值由 `= uuid4()` 改为 `field(default_factory=uuid4)`（修潜伏共享默认值 bug，见 §3.4） | 3,396 | `7D82833456C34232B1BD3A7935CAFD9743AE46ABB89532E910749DF1F8BD085A` |
| `src/lva/server.py` | `get_runtime()` 采纳 `get_announced_runtime_instance_id()`，不再让 `RuntimeController` 自己 mint 第二个 id（修 B18） | 17,959 | `9465DE51D8F13052CC6AAE4E427F10D42F5CA8598FA3A39F0817F1FF94E9A853` |
| `tests/red_v121/test_red_service_identity.py` | **新增 RED 套件**（9 项） | 6,698 | `CA3AC81ACA45CA0D8F693CF7D2ED7312411EF3DFED88AD0E3E54EADAF217251A` |

未修改：三个生成制品（SHA256 与 R03b 收口时逐字节一致，见 §4）、冻结计划与历史报告、任何既有 RED 断言、`Cargo.toml`/`Cargo.lock`（**本轮零新增依赖**——`windows-sys` 未使用，listener table 走 `netstat` 子进程解析）、`supervisor.rs`（其 I04 语义已正确，本轮只读它）、前端 `apps/desktop-ui/src`。

---

## 2. PR-008 验收条逐项处置

| 冻结要求（L1213 Steps / L1215 Tests） | 本轮实现 | 判定 |
|---|---|---|
| 服务状态映射 | `ServiceRegistry::observe()` 写入 typed `ServiceIdentity` | **PASS** |
| runtime instance tracking | `instance_token` 字段 + `reobserve_after_restart()` 返回 token 是否变化 | **PASS** |
| 重启换 PID 不误判 | 单测 `a_restart_with_a_new_token_is_detected_even_when_the_pid_repeats`：同 PID、新 token → 判定为不同进程 | **PASS** |
| crash reason | `CrashReason`（None/HandshakeFailed/ExitedNonZero/Vanished/Requested）+ `record_crash()` 联动 `Readiness::Exited` | **PASS** |
| 读取 Windows IPv4/IPv6 listener table | `parse_listener_table()` 解析 `netstat -ano`，只保留 `LISTENING` 的 tcp/tcpv6 行；畸形行跳过不猜 | **PASS** |
| 把 control port 关联到已识别 Hub process | `attest_for_port(rows, port, id)` 返回 `(attestation, Option<u32> owner)`；`HUB_CONTROL_PORT = 8089` | **PASS** |
| 发布 typed bind attestation | `HubBindAttestation` 经 `get_service_identity_status` 命令返回 | **PASS** |
| redacted diagnostic snapshot | 该结构体不含 pid/port/addr/endpoint/token（有 RED 断言 `test_attestation_is_redacted` 守护） | **PASS** |
| 四类 listener 分类正确 | 单测 `four_fixture_classes_classify_correctly` + `only_rows_for_the_requested_port_are_evidence`：LoopbackOnly / AllInterfacesV4 / AllInterfacesV6 / Unmappable 各自命中 | **PASS** |
| 观测 PID/port 不产生 kill authority | `network_attestation.rs` 全文不含 kill/terminate/taskkill（RED 断言守护）；`ServiceIdentity::can_stop()` 只看 ownership；单测 `observing_a_pid_and_port_confers_no_authority` 断言「有 PID 有 port 但仍拒绝 stop」 | **PASS** |
| Unknown 不提供 stop | 单测 `unknown_offers_no_stop`、`adopted_and_external_offer_no_stop`；`can_stop()` 的 match 显式列出四个变体，只有 Spawned 为 true | **PASS** |
| UI/Core 收到 typed service/bind state | `get_service_identity_status` 已注册进 `generate_handler!`（RED 断言守护） | **PASS** |
| snapshot DTO 一致性（§8.1） | `test_red_snapshot.py` 3 项 + `test_bridge_mock_and_snapshot_version.py` 6 项复验通过，未改代码 | **PASS（复验）** |

### 2.1 关键设计决策

**为什么用 `netstat` 子进程而不是 `windows-sys`/`iphlpapi`。** 离线 registry 里 `windows-sys` 0.59/0.60/0.61 与 `ipnet` 都在，技术上可加依赖直接调 `GetExtendedTcpTable`。但本轮**零新增依赖**更符合 PR-008 的「read-only effective-bind attestation」定位：`netstat` 是查询命令，不持有任何进程句柄，因此**结构上不可能**把观测变成 kill authority。代价是解析文本（已用 11 项单测覆盖畸形输入）。若后续 PR-032（Services/Diagnostics）要求更低延迟或更细字段，可在此模块内部替换实现而**不动**对外类型。

**为什么 attestation 脱敏。** 该结构经 Tauri command 进入 WebView，与硬约束 4（WebView 不接触 Core/Hub 凭证和端点）直接相关。原始证据（地址、端口、PID）留在 Rust 侧，只以 `attestation_id` 关联。这与 R03b 已冻结的 `HubBindAttestation`（Python 侧，`src/lva/contracts/state.py`）语义一致：两侧都只传判决与粗粒度来源。

**为什么 fail-closed。** 空表 → `UnverifiedBind` + `HubInfoUnavailable`；`netstat` 执行失败 → `ProbeFailed`。**「没有证据」不等于「loopback 已证明」**——这与计划 L665「仅 `VERIFIED_LOOPBACK` 允许控制」一致。

---

## 3. 本轮实测通过

| 项 | 命令要点 | 结果 |
|---|---|---|
| **R08 RED 套件** | `pytest tests/red_v121/test_red_service_identity.py` | 改前 **9 failed**；改后 **9 passed**，EXIT=0 |
| **Rust 单测全量** | `rusttest.ps1 -SourceExe <test exe>`（mt.exe 内嵌 Common-Controls 6.0 清单） | **`49 passed; 0 failed; 1 ignored`**，EXIT=0，`stray_ping=0`（起始 29 passed，本轮 +20） |
| Rust 编译 | `cargo check --offline`（`CARGO_TARGET_DIR` 指 X 盘，PATH 前置 w64devkit） | EXIT=0 |
| **B18 单源行为验证** | 进程内脚本：`announce_runtime_instance_id(x)` → `get_runtime()` | `IDENTICAL = True`（改前实测为 `False`），`B18_SINGLE_SOURCE_OK` |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0（contract 5 / invariants 23 / unit 8 / fault 7 / integration 11 / migration 2 / ux 11） |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **5 failed / 145 passed**（起始 5F/136P；+9 全为本轮新套件转绿，**无新增红**） |
| codegen zero-diff | `python -m lva.contracts.codegen --verify` | 三制品全部 `verified`，EXIT=0 |
| ruff | `ruff check src/lva tests/run_groups.py`（E4/E7/E9） | All checks passed |

### 3.1 Rust 单测增量明细（29 → 49）

- `network_attestation.rs`：**10 项**（listener table 解析、四类分类、IPv6 loopback、loopback-only 验证、全接口拒绝、混合拒绝、空表 fail-closed、垃圾输入、畸形行跳过、按端口取证据）
- `service_registry.rs`：10 项（仅 Spawned 可停、Unknown 不可停、Adopted/External 不可停、有 PID/port 仍无权限、换 PID 同 token 检测、同 token 非重启、crash reason 联动 Exited、稳定排序、legacy 投影、未知服务无记录）

**注意**：起始 29 项里已含 R04 的 `supervisor.rs`(5) + `process_manager.rs`(5)，本轮未改动这两个文件。逐模块清点（`--list` 实测）：`autostart` 1 + `crypto` 1 + `bridge` 9 + `ws` 9 + `supervisor` 5 + `process_manager` 5 + `network_attestation` 10 + `service_registry` 10 = **50 项**（49 项执行 + 1 项 `#[ignore]`）。

### 3.2 勘误 E-R08-1（2026-09-24 独立复验后修正）

本报告初版在 §1 表与 §3.1 把 `network_attestation.rs` 的单测数写成 **11 项**，独立审查指出应为 **10 项**。复核确认：`Select-String '^\s*#\[test\]'` 计数为 **10**，`--list` 实测 `network_attestation = 10`。**审查方正确，已就地修正**。

总数仍然自洽（29 + 10 + 10 = 49 执行 + 1 ignored = 50 listed），因此该错误**不影响任何结论**，只是模块级计数笔误。

### 3.3 勘误 E-R08-2 —— Rust 测试二进制的启动前置条件（**重大，来自独立审查**）

独立审查发现：`cargo test --lib` 产出的测试二进制在**裸 shell 下根本无法启动**，并在验证时遇到 `0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND`。本轮**已独立复现并确认**，实测矩阵：

| 配置 | 结果 |
|---|---|
| 裸 exe（无内嵌 manifest），**无** `WebView2Loader.dll` 旁置 | `HUNG_TIMEOUT_15s`——**不是崩溃退出，是挂起**（模态错误对话框，见下） |
| 裸 exe，**有** `WebView2Loader.dll` 旁置 | `EXITED code=-1073741511`（`0xC0000139`） |
| mt.exe 内嵌清单的 exe，**无** `WebView2Loader.dll` 旁置 | `HUNG_TIMEOUT_20s` |
| mt.exe 内嵌清单的 exe，**有** `WebView2Loader.dll` 旁置 | **`EXITED code=0`**，`--list` 正常输出 |

**两个前置条件都是必要的**：manifest（或宿主已激活的 comctl32 v6 上下文）**且** `WebView2Loader.dll` 与 exe 同目录。缺任一即无法启动。

**一个必须记录的观察差异**：独立审查报告的是 `0xC0000139` 崩溃退出，而我这边在**无 manifest 且无 loader** 时观察到的是**挂起**（15 s 无输出、无 stderr、无 WerFault 进程、`Application Error` 日志无对应条目）。两者指向同一根因（comctl32 v5.82 无 `TaskDialogIndirect` 导出），但呈现不同——挂起形态更像错误对话框在等待交互。**这意味着裸 shell 下的 Rust 复跑可能表现为「卡住」而非「报错」**，排查时应先看进程是否存活、是否有模态框，而不是只找退出码。

**结论**：R07 报告中的「29 passed ×3」与 R08 的「49 passed」**都只能在满足上述前置条件的宿主下复现**。handoff 的验证配方**确实缺了这两条**（该配方只写了 `PATH` 前置 w64devkit + `CARGO_TARGET_DIR`），任何新会话照抄都会失败。这是本报告交付范围内**最值得记录的缺陷**。

### 3.4 勘误 E-R08-3 —— `bootstrap.py` 的 dataclass 共享默认值（潜伏 bug，已修）

独立审查发现：`BootstrapConfig.runtime_instance_id: UUID = uuid4()` 在**类定义时只求值一次**，任何省略该参数的构造都会共享同一个 UUID。当前 `read_bootstrap_from_stdin()`（L73）总是显式传参，故**未被触发**，但这是一条随时可能引爆的回归面——尤其与本轮刚修的 B18（单源）直接相关。

已改为 `field(default_factory=uuid4)`。实测两次独立构造得到不同 UUID（`DEFAULT_FACTORY_OK`）。

### 3.5 独立复验的总体结论

审查者独立验证了本报告的 11 项声明（报告哈希、6 个文件 SHA256、HEAD 与工作树计数、red_v121 分布、v12 层、三制品哈希、B18 源码、Rust 单测 49/49、`lib.rs` 接线、W 盘清理），**全部一致**。发现的 3 项（E-R08-1/2/3）已全部就地处置，**无一影响 R08 的实质结论**。

审查者另报告：其首次 v12 层复跑出现 `integration` + `migration` 失败，经隔离复跑确认为**重型 cargo 全量编译与 pytest 并发导致的资源争抢 flake**，非 R08 回归——与本轮实测（integration 11 passed / migration 2 passed / 整层 7/7 绿）一致。

**副产物（本轮发现）**：运行 Rust 测试脚本时，`rusttest.ps1` 会 `Start-Process` 运行 `ping.exe` 哨兵。若脚本被中途打断，**哨兵 `ping.exe` 进程可能残留**（本轮观察到残留）。清理方式：`Get-Process ping -ErrorAction SilentlyContinue | Stop-Process`。这不是产品缺陷，但会污染 `stray_ping` 计数（该计数用于判断「Adopted/External 进程未被误杀」，残留会让它虚高）。


---

## 4. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| 真实 Tauri 应用内的 `get_service_identity_status` 调用 | 未验证 | 需可启动的 GUI 应用；本轮只验证了 command 已注册与类型可序列化（`cargo check` + 单测） |
| 真实 Hub 进程的 bind attestation（`VERIFIED_LOOPBACK` 实测） | 未验证 | 本机未运行 llama.cpp-hub；`observe_hub_bind_attestation()` 读真实 `netstat` 的路径**未在真实 Hub 上取证**。四类分类由 fixture 单测覆盖，**不得**据此宣称已对真实 Hub 完成 attestation |
| 前端消费 `get_service_identity_status` | 未实现/未验证 | 属 PR-032（Services/Diagnostics）；本轮只交付 typed Rust 面 |
| 多显示器 DPI、GUI 交互类 | N/A / 未验证 | 沿用 R04/R05/R07 状态（本机仅 1 台显示器 1707x1067 @144DPI） |
| soak `--duration 7200`、Tauri release 构建、三个 workflow 的 CI 实跑、真实声学验收 | 未运行 | 沿用既有状态 |

---

## 5. 基线与末态

| 项 | 起始 | 末态 |
|---|---|---|
| HEAD | `cf1c96752ffb752de1581860968d5189cd6e2a2c` | 同（未变） |
| `status --porcelain=v1` | 85 行 | **87 行**（+1 新 RED 文件 +1 本报告） |
| `status --porcelain=v1 -uall` | 243 行 | **246 行**（+3 = 新 RED 文件 + 本报告 + `network_attestation.rs`；后者在 `v1` 口径下计入既有 `?? apps/desktop-shell/src-tauri/src/` 聚合项，故 `v1` 只 +2） |
| `tests/red_v121` | 5 failed / 136 passed | **5 failed / 145 passed** |
| Rust 单测 | 29 passed / 1 ignored | **49 passed / 1 ignored** |
| 三生成制品 | EC6F…/C836…/D307… | **逐字节一致，未变** |

**三个生成制品的字节与 SHA256（末态复核）**：

| 制品 | 字节 | 文件字节 SHA256 |
|---|---|---|
| `schemas/lva-ipc-v1.json` | 55,463 | `EC6F3BB46B6A37402CA8E5ECCC71DDA479B6BA54216C249ABAC46751CC310C8C` |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 16,319 | `C836F691743D3074E49354EDE8AF3E67F320430BBFAA9A8C312CBD19C6AE5B5D` |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 78,138 | `D307E1C519368E19395FA2F4EDA972A37AD5B3221764E00F951E321DAF012185` |

---

## 6. 差异报告（只报告，未自行修正）

1. **R08 的 RED 映射与 PR-008 的验收面不一致**：`tests/red_v121/README.md` 把 `test_red_snapshot.py` 标为「§8.1 / PR-008」，但 PR-008 的实质是 service identity/readiness。本轮新增的 `test_red_service_identity.py` 才是 PR-008 的 RED；**建议更新 README 映射表**（未改，属既有文件）。
2. **`hub_bind_attestation` 在 Python 侧与 Rust 侧各有一份同义类型**：`src/lva/contracts/state.py::HubBindAttestation`（随 `RuntimeState` 进 WebView）与新的 `network_attestation.rs::HubBindAttestation`（经 Tauri command 进 WebView）。两者字段语义一致但**未共享 schema**，且都不在 `schemas/lva-ipc-v1.json` 里。**建议在 PR-008 后续或 PR-032 决定是否把 bind attestation 纳入 IPC 契约**（纳入需重跑 codegen，会动三个制品）。
3. **`HUB_CONTROL_PORT = 8089` 是硬编码常量**：来自既有 `process_manager.rs` 对 Hub 的观察端口。若 Hub 端口可配置，该常量应改为从配置读取（未改）。
4. **`service_registry.rs` 的 legacy 投影 `get_all_services()` 已无调用方**（`lib.rs` 用的是 `get_service_identity_status`）。保留它是为了满足冻结计划 L1216「旧状态显示暂留 compatibility mapping，PR-038 删除」。
5. **本轮未触碰 `scripts/start-all.ps1`（审查 V6）**：它属既有工作树内容且是用户脚本，硬约束 10 禁止擅自修改，**仍需用户授权**才能处置。
6. **`config.py` 的 1234 默认值（审查 V4/R22）未改**：属 R09/R10 范围（`test_red_authority.py::test_legacy_1234_default_is_gone` 仍是红的）。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/` / `scripts/soak_report.json`；未执行任何 git 写操作（无 add/commit/push/reset/checkout/clean）。所有 E 盘写入均经 `apply_patch`。未宣称「全量 lint 通过」——Ruff 仅覆盖 E4/E7/E9 且范围限 `src/lva` + `tests/run_groups.py`。**本轮零新增 Rust 依赖**，未申请网络授权。

## 8. 下一片

R08 已闭环（RED 9/9、Rust 单测 49/49、v12 全绿、无回归、无新增红）。`tests/red_v121` 剩余 **5 项红全部在 `test_red_authority.py`**，属 **R09（I21，Hub control 只能来自 Core）/ R10（I22，所有入口统一 dispatcher）**：

- `test_rust_exposes_no_direct_model_lifecycle_commands`（`lib.rs` 仍有 `scan_models`/`refresh_models`/`switch_llm_model`/`unload_vram`/`cold_start_llm`）
- `test_core_actually_wires_a_hub_saga`（`server.py` 未传 `hub_saga=`）
- `test_legacy_1234_default_is_gone`（`config.py` L47/L60）
- `test_no_route_bypasses_the_command_dispatcher`（route 直调 provider/journal 副作用）
- `test_ask_route_adapts_into_a_command`（`/api/ask` 未走 `execute_command`）

进入 R09/R10 前需要用户裁决的既有项（本片未处置）：R07 §5.1（丢弃无 `sequence` 事件是否为最终行为）、R07 §5.3（R06 报告是否补写）、R07 §5.4 / 审查 V6（`scripts/start-all.ps1` 归属与授权）、R05 遗留（`require_auth` 旁路是否收紧、`lva ask` 认证通道方向）。

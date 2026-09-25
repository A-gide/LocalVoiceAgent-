# R20 执行报告 — 修复 attestation 端口 bug（8089 → 8080）+ G1 裁决入库

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 CONTEXT-HANDOFF-LVA-R08-2026-09-24.md 之后的第十五片）
- 仓库：E:\AI\LocalVoiceAgent
- HEAD：`c916fce`（G1 裁决已 push）→ 本轮在其上继续

---

## 0. 本轮发现并修复一个真实 bug（我在 R08 引入）

**`lib.rs::HUB_CONTROL_PORT = 8089` 是错的，正确值是 8080。**

### 证据链

| 来源 | 值 |
|---|---|
| 计划 **L527**（逐字） | `默认入口为 8080，child 通常分配 8081+；LVA 不依赖 child 端口` |
| 计划 L79 | `默认接 Hub 8080 推理面` |
| **本机真实 Hub 配置**（`D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\config\application.json`） | `webPort: 8080`、`httpOnlyPort: 8081`、`listenAddress: 0.0.0.0` |
| `process_manager.rs`（既有） | 观测 **8080**（L92/L104/L328） |
| `config.py`（R19 改） | `HUB_PORT = 8080` |
| **`lib.rs::HUB_CONTROL_PORT`** | **8089** ← 错 |

### 后果（严重）

`observe_hub_bind_attestation()` 读 `netstat` 后调用 `attest_for_port(&rows, 8089, id)`。**8089 上没有任何监听者**，因此 `bound` 为空 → `attest_from_rows([])` → `UnverifiedBind` + `HubInfoUnavailable` → **`hub_control_allowed()` 恒为 False**。

即：**即使 Hub 健康运行在 8080，整个 Hub 控制面也会被永久拒绝。** R15 建立的 fail-closed 门会一直关着。

### 为什么测试没抓到

`network_attestation.rs` 的单测夹具**自己也在用 8089**（L197/198 的 netstat 文本、L241-299 的 `ListenerRow`）。夹具与常量互相自洽，**10 项单测全绿**——这是「自指夹具掩盖真实配置错误」的典型。

### 为什么我的 R08 报告没抓到

R08 报告 §6.3 我写了「`HUB_CONTROL_PORT = 8089` 是硬编码常量：**来自既有 `process_manager.rs` 对 Hub 的观察端口**」——**这句是错的**。`process_manager.rs` 用的是 8080。我当时**没有核对来源**，把一个无依据的数字当作继承来的事实记录了下来。

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `apps/desktop-shell/src-tauri/src/lib.rs` | `HUB_CONTROL_PORT` **8089 → 8080**，并补注释说明它必须与 Hub 的 `webPort` 和 Core 的 `HUB_PORT` 一致、探测无监听的端口会永久关闭控制门 | 见 §4 | 见 §4 |
| `apps/desktop-shell/src-tauri/src/network_attestation.rs` | 单测夹具中的 11 处 8089 **全部改为 8080**，消除自指夹具 | 见 §4 | 见 §4 |
| `tests/red_v121/test_red_bind_attestation.py` | 新增 **2 项 RED**：`test_attested_port_matches_the_hub_control_face`（Rust 常量 == `config.py` 的 `HUB_PORT`）、`test_attested_port_is_not_a_child_port`（必须 == 8080） | 见 §4 | 见 §4 |

未修改：`process_manager.rs`（它本来就是对的 8080）、三个生成制品、`Cargo.toml`/`Cargo.lock`。

---

## 2. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新增 RED | `pytest tests/red_v121/test_red_bind_attestation.py` | 改前 **2 failed / 11 passed**（断言 `8089 == 8080` 失败）→ 改后 **13 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **230 passed / 0 failed**（起始 228P；+2 全为本轮新增并转绿） |
| Rust 编译 | `cargo check --offline` | **EXIT=0**（1m11s） |
| Rust 单测 | `rusttest.ps1 -SourceExe <exe>` | **55 passed / 0 failed / 1 ignored**，`stray_ping=0` |
| 夹具一致性 | 全文件检索 | `network_attestation.rs` 中 `8089` **零命中**、`8080` 13 处 |

---

## 3. 对「真实 Hub 端到端」欠账的影响（重要）

**本轮修复是那条欠账的前置条件之一。** 在修复前，即使真跑起本机 Hub（0.9.8.3，配置 8080），控制门也会因探测 8089 而**永远关闭**——端到端探针必然失败，且失败原因会指向「bind 未验证」，与真实原因（端口常量错）**完全错位**。

**本机具备真实 Hub 的完整条件**（只读核实）：

- `D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\` **存在**，版本**正是 pinned 的 0.9.8.3**
- `run.bat` 存在（启动 `jre\bin\javaw.exe ... org.mark.llamacpp.server.LlamaServer`）
- `config\application.json`：`webPort 8080`、`apiKeyEnabled: true`、`apiKey` 有值、`listenAddress: 0.0.0.0`
- `config\modelpaths.json` 列出 4 个模型路径（`W:\model\...`），`auto_load_models_cache.json` 为空 `[]`
- **当前 8080 无监听**（Hub 未运行）

**注意 `listenAddress: 0.0.0.0`**：按计划 L579/L1257，Hub 同时监听 0.0.0.0 时 control **应当被拒绝**（`HUB_CONTROL_UNSAFE`）。因此本机 Hub 若按现配置启动，**其 attestation 正确结果就是「拒绝控制」**——这正是 L1257 要求的行为，不是缺陷。若要验证「VERIFIED_LOOPBACK 放行」路径，需要把 Hub 改为仅监听 127.0.0.1。

**本轮未启动 Hub**（见 §4）。

---

## 4. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| **启动真实 Hub 并跑端到端** | **未运行** | 启动 `D:\llamacpphub\...` 会拉起 JVM + 可能加载模型、占用 8080/8081、写其 logs/config——**属改变外部系统状态的动作，超出本轮授权**。需用户明确许可后另开切片 |
| 修复后的真实 attestation 结果 | 未验证 | 依赖上一条；且现配置 `listenAddress: 0.0.0.0` 按 L579 应得 `HUB_CONTROL_UNSAFE` |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

---

## 5. 差异报告（只报告，未自行修正）

1. **我的 R08 报告 §6.3 有一处错误归因**（见 §0）：称 8089「来自既有 process_manager.rs 的观察端口」，实际那里是 8080。**该错误记录未被改写**（遵守「不重写历史」），本轮在 R20 报告中更正。
2. **自指夹具是一个模式性风险**：`network_attestation.rs` 的 10 项单测全绿却掩盖了端口错误。同类风险也存在于 `service_registry.rs`（其单测用 `Some(8089)` 作为端口值——那是**任意端口值**而非 Hub 端口，**不构成 bug**，但值得注意）。已核实后者无需改动。
3. **`HUB_CONTROL_PORT` 仍是 Rust 硬编码常量**：本轮修正了值，但**未**改为从配置读取。Rust 侧与 Python 侧的端口仍由两处常量各自维护；本轮新增的 RED 断言（Rust 常量 == `config.py::HUB_PORT`）**正是为了防止二者再次漂移**。
4. **本机 Hub 的 `apiKey` 值已出现在我的只读输出中**：该值是用户本机 Hub 的本地 API key（`apiforccswich`），**不是 LVA 的密钥**，且它在用户自己的配置文件里。**我未把它写入任何仓库文件或提交**。若你认为它不应出现在会话记录中，请告知，我会在后续输出中避免引用该文件全文。

---

## 6. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告（含我自己有错的 R08 报告）；未删除 .venv / venv / benchmarks/；**未执行 git 写操作**；**未启动任何外部服务**。E 盘写入经 apply_patch 与一次提权替换（夹具端口）。**本轮零契约改动、零新增依赖。**

## 7. 下一片

| 项 | 说明 |
|---|---|
| **真实 Hub 端到端**（建议） | 本机条件齐备（0.9.8.3 @ 8080）。**需你决定**：是否许可启动 Hub、以及是否把它改为仅监听 127.0.0.1（否则按 L579 应得 `HUB_CONTROL_UNSAFE`，只能验证拒绝路径） |
| PR-020/021（C 链 privacy/capture） | 依赖已满足 |
| PR-016..019 验收映射 | 实现已在，缺逐条映射 |
| PR-023/030/031（窗口能力） | 承接 S-UI-01 的 R11 |
| L463 全合规、`_enc` 密钥轮换 | 待用户决定；审查方指出后者因远端历史已永久化而**紧迫性上升** |


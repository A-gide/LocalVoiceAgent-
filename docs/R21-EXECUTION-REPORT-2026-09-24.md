# R21 执行报告 — 防线修正（跨语言一致性守卫 + 夹具泄漏普查 + R15/R17 追溯审查）

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 CONTEXT-HANDOFF-LVA-R08-2026-09-24.md 之后的第十六片）
- 仓库：E:\AI\LocalVoiceAgent
- HEAD：`c916fce` → 本轮在其上继续
- 范围来源：审查方「防线修正（即刻生效）」三条

---

## 0. 三条指令的执行结果

| # | 审查方要求 | 执行 |
|---|---|---|
| 1 | 加跨语言静态一致性测试：`lib.rs::HUB_CONTROL_PORT` == `config.py::HUB_PORT` == 计划 L527 值 | **R20 已做**（2 项）；本轮**扩充为 8 项守卫** |
| 2 | 审查清单新增：① 跨语言常量对表 ② 夹具值泄漏普查 | **本轮已作为方法执行**，并把结论固化为测试 |
| 3 | 补 R15/R17 追溯审查 | **本轮已做**，发现同类异味并加守卫 |

---

## 1. 跨语言/跨层常量对表（方法执行结果）

枚举两侧同名事实，逐项比对：

| 事实 | Rust | Python | 一致？ |
|---|---|---|---|
| **Hub control 端口** | `HUB_CONTROL_PORT = 8080` | `HUB_PORT = 8080` | ✅（R20 修复前为 8089 ✗） |
| **Core service 端口** | `settings.rs` L83 `127.0.0.1:8765/api/asr`；`settings.default.json` L9 同 | `SERVICE_PORT = 8765` | ✅ |
| **bootstrap protocol_version** | `core_supervisor.rs` `!= 1` | `bootstrap.py` `!= 1` | ✅ |
| **Screenpipe 端口** | — | `screenpipe_importer/client.py` `3030` | ✅（独立服务，非 Hub） |
| Core 音频率 | — | `ASR_RATE 16000` / `TTS_RATE 44100` / `CAPTURE_RATE 48000` | ✅（Rust 侧无镜像） |
| Bridge 超时 | `CONNECT_TIMEOUT 5s` / `COMMAND_TIMEOUT 10s` / `RECONNECT_MIN 500ms` / `RECONNECT_MAX 10s` | 无对应常量 | ✅（Rust 单侧拥有） |
| re-attest 周期 | `REATTEST_INTERVAL 30s` | 无（Core 只读 `revalidate_after`） | ✅（Rust 单侧拥有） |

**结论：只有前 3 项是真正的跨语言重复事实**，且现已全部有显式等式断言。

---

## 2. 夹具值泄漏普查（方法执行结果）

对 7 个生产常量做「生产代码 vs fixtures」全仓 grep 分类：

| 常量 | 生产命中 | 夹具命中 | 判定 |
|---|---|---|---|
| **Hub port 8080** | lib.rs / network_attestation.rs / process_manager.rs / hub_control.py / hub_inference.py / openai_compatible.py / config.py / server.py / settings.example.json | 4 个测试文件 | ⚠️ **本轮已加守卫**（见 §3） |
| ASR rate 16000 | 22 处（含生成制品、vendored OLV） | `tests/red_v121/harness.py` | ✅ 合法（harness 需要真实采样率） |
| Capture rate 48000 | audio.py / config.py | — | ✅ |
| TTS rate 44100 | audio.py / config.py / vendored OLV | — | ✅ |
| Service port 8765 | settings.rs / settings.default.json / config.py / vendored OLV | `test_red_bootstrap.py` | ✅（本轮加等式断言） |
| COMMAND_TIMEOUT 10 | bridge.rs | — | ✅ Rust 单侧 |
| REATTEST_INTERVAL 30 | lib.rs | — | ✅ Rust 单侧 |

**唯一同类风险是 Hub port 8080**：它在 5 处 Python 模块各自硬编码（`config.py` 1 + 3 个 provider 默认值 + `server.py` 的 f-string）。**已在 §3 加守卫。**

---

## 3. 新增守卫（8 项，`tests/red_v121/test_red_cross_language_consistency.py`）

| # | 守卫 | 抓什么 |
|---|---|---|
| 1 | `test_hub_port_agrees_across_languages` | Rust 常量 == Python 常量（**这一条就能抓到 R08 的 8089 bug**） |
| 2 | `test_hub_port_matches_the_frozen_default` | 两者都 == 8080（计划 L527） |
| 3 | `test_core_service_port_agrees_across_languages` | `settings.rs` + `settings.default.json` 的 Core URL 端口 == `SERVICE_PORT` |
| 4 | `test_bootstrap_protocol_version_agrees_across_languages` | 两侧 `protocol_version != N` 的 N 相同 |
| 5 | **`test_attestation_fixtures_do_not_disagree_with_the_constant`** | Rust 夹具里的 `port:` 字面值必须 == 生产常量（**抓「自指夹具」**） |
| 6 | `test_netstat_fixture_rows_use_the_real_hub_port` | 夹具的 netstat 表必须含真实 Hub 端口行 |
| 7 | **`test_python_provider_defaults_agree_with_the_hub_port`** | `src/lva` 内任何 `127.0.0.1:<port>` 必须是 Hub 端口或 3030（**抓 R15/R17 同类异味**） |
| 8 | `test_python_provider_defaults_actually_use_the_hub_port` | 3 个 provider 的默认值必须**就是** Hub 端口（不只是「不是别的」） |

**守卫 1 与 5 合起来正是 R08 bug 的完整免疫**：一个抓常量漂移，一个抓夹具自指。

---

## 4. R15/R17 追溯审查（第 3 条指令）

### R15 触及面复核

| 检查 | 结果 |
|---|---|
| R15 的 re-pinned `EXPECTED_SCHEMA_SHA256` 是否仍匹配 | ✅ `codegen --verify` 三制品全 `verified`（`d4708ebd` / `6817fa2a` / `3a62298b`） |
| R15 新增的 `hub.attest_bind` 契约是否与消费端一致 | ✅ 已在 R17 端到端探针 6/6 验证 |
| R15 的 `hub.attest_bind` 分支是否可绕过门 | ✅ 门在 dispatcher 内，无入口可绕 |
| **R15 引入的端口类常量** | ⚠️ **发现同类异味**：Hub 端口在 5 处 Python 模块硬编码（见 §2）。**非 R15 引入**（多数早于 R15），但 R15 的 `server.py` 改动沿用了它们。已加守卫 7/8 |

### R17 触及面复核

| 检查 | 结果 |
|---|---|
| R17 探针是否硬编码端口 | ✅ **零硬编码**——端口经 argv 传入（`probe_attestation_e2e.py <port> <token> <ready>`） |
| R17 探针的 attestation 形状是否与 Rust 一致 | ✅ 逐字段对应 `lib.rs::send_bind_attestation` |
| R17 探针是否依赖被 8089 bug 污染的行为 | ⚠️ **是**——R17 探针当时通过，是因为它**自建 attestation 信封**（携带自己的 `attestation_id`/`revalidate_after`），**不经过 Rust 的 `observe_hub_bind_attestation()`**。因此 8089 bug **不在它的覆盖范围内**——这是探针的合理边界，不是缺陷，但值得记录 |

### 追溯审查的结论

**R15/R17 未发现新缺陷。** 唯一相关发现是：8089 bug（R08 引入）之所以能穿过 R17 的端到端探针，是因为探针**自建信封**而非调用 Rust 的观察器。这意味着**「Rust 真实发送」与「Core 正确接收」是两条独立证据链**——R17 覆盖了后者，前者仍未验证（R16 遗留）。

---

## 5. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新守卫套件 | `pytest tests/red_v121/test_red_cross_language_consistency.py` | **8 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **238 passed / 0 failed**（起始 230P；+8 全为本轮新增） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed** |
| codegen zero-diff | `python -m lva.contracts.codegen --verify` | 三制品全 `verified` |
| ruff | `ruff check src/lva tests/run_groups.py` | All checks passed |

---

## 6. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| Rust 单测 | 未重跑 | 本轮**零 Rust 改动**（`lib.rs` 与 `network_attestation.rs` 的改动在 R20，已跑过 55 passed） |
| 真实 Hub 端到端 | 未运行 | 需用户许可启动 Hub（见 R20 §3） |
| Tauri release、soak、CI 实跑、GUI | 未运行 / N/A | 沿用既有状态 |

---

## 7. 差异报告（只报告，未自行修正）

1. **守卫是「检测」而非「消除」**：Hub 端口仍在 Rust 与 Python 各存一份，本轮只保证二者一致。**审查方指出的「同一事实两种语言各硬编码一份是设计异味、长远应收敛为单一事实源」成立且未解决**——收敛需要定义权威来源（例如由 `schemas/lva-ipc-v1.json` 或生成的常量模块承载），那会触及契约或构建流程，**需单独授权**。
2. **守卫 7 的白名单含 3030**：`screenpipe_importer/client.py` 的默认端口是 Screenpipe 自己的服务，不是 Hub。把它列入白名单是**语义判断**，若将来 Screenpipe 端口变化需同步。
3. **`openai_compatible.py` 的默认 `127.0.0.1:8080/v1` 也指向 Hub**：这是 R12 §7.3 已记录的「`openai_compatible.py` 未被 `get_registry()` 使用」的延续——它现在与 Hub 端口一致，但**它到底是不是 Hub provider** 仍需在 PR-013 收尾时明确。
4. **本轮未改任何产品代码**（除守卫测试）——§2/§4 的发现都是只读结论。

---

## 8. 硬约束遵守

未弱化/跳过/xfail 任何断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 .venv / venv / benchmarks/；**未执行 git 写操作**；**未启动外部服务**。**本轮零产品代码改动、零契约改动、零新增依赖、未提权。**

## 9. 下一片

| 项 | 说明 |
|---|---|
| **单一事实源收敛**（审查方指出） | 把 Hub 端口等跨语言常量收敛为单一来源，需定义权威位置（契约 or 生成模块）——**需授权** |
| 真实 Hub 端到端 | 本机条件齐备（0.9.8.3 @ 8080）；需用户许可启动，并决定是否改为仅监听 127.0.0.1 |
| Rust 真实发送 attestation（R16 遗留） | 需 GUI；与 R17 的接收端证据合起来才能闭合通道 |
| PR-020/021（C 链） | 依赖已满足 |
| PR-016..019 验收映射 | 实现已在，缺逐条映射 |
| PR-023/030/031（窗口能力） | 承接 S-UI-01 的 R11 |
| L463 全合规、`_enc` 密钥轮换 | 待用户决定 |

**本轮 R20 + R21 成果尚未提交**（工作树 v1=28 + 本轮新增）。


# R14 执行报告 — PR-012 半片 1（不动契约部分）+ attestation 通道设计稿

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第九片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 范围来源：冻结计划 PR-012（L1250-1258）+ 审查方认可的**半片拆分**（半片 1 可立即开工，半片 2 待设计稿获批 + 硬约束 5 授权）

---

## 0. 交付两件：设计稿 + 半片 1

| 交付 | 文件 | 状态 |
|---|---|---|
| **attestation 通道设计稿** | `docs/PR-012-ATTESTATION-CHANNEL-DESIGN.md` | **待审**；审后才请求硬约束 5 授权 |
| **半片 1**（不动契约） | 见 §2 | **完成**，RED 12/12 转绿 |

---

## 1. 设计稿要点（供审查方审阅）

### 1.1 物理路径：**Rust 是 WS 客户端，Core 是 WS 服务端**

审查方要求「说明 Tauri event 到的是 WebView，Python Core 如何订阅需画清楚」。核实结果**推翻了「经 Tauri event 回传」这一方向**：

| 事实 | 证据 |
|---|---|
| Rust 建连并持有唯一 WS | `bridge.rs` 用 `ws::{WsClient, WsMessage}`；`RECONNECT_MIN/MAX` 在其内 |
| Core 是 WS 服务端 | `server.py` `@app.websocket("/ws")`，L576-579 收 `CommandEnvelope` 并回 `command_result` |
| Tauri event 只到 WebView | `bridge.rs` L454 `emit()` → `EVENT_NAME = "lva://event"` |

**正确路径**：Rust 经**既有 authenticated WS** 把 attestation 直接发给 Core。不需要新传输层，且**不经 WebView**（符合硬约束 4）。

### 1.2 关键发现：类型已在契约中

实测 `HubBindAttestation` **已在三个生成制品里**（`lva-ipc-v1.json` 4 处 / `lva-ipc.ts` 2 处 / `lva_ipc.rs` 9 处）。所以问题不是「定义类型」，而是「Core 如何获得一个实例」。

**推荐方案 A**：新增一个**入站 command**（`hub.attest_bind`）承载 attestation。理由：方向正确（外部向 Core 报告观测）、复用既有 `command_id`/幂等/回执机制、与 L1256 一致、fail-closed 天然成立。

**精确影响面**：只改 `contracts/commands.py` 一个文件——新增 `HubAttestBindPayload`（**复用已存在的 `HubBindAttestation`，不新增类型定义**）+ union 追加一个成员（16 → 17）。**三制品哈希将全部改变**，这是请求授权的具体对象。

### 1.3 审查方要求的一条已写入验收

`HubBindAttestation._fail_closed()`（`state.py` L108）说明该类型预设 fail-closed。**PR-012 验收应包含**：真实 verdict 到达前，`RuntimeState.hub_bind_attestation` 必须保持 `None`，saga 的 control 门必须保持关闭（对应 L665）。已写入设计稿 §5。

---

## 2. 半片 1 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `src/lva/providers/hub_contracts_v0_9_8_3.py` | **新增**（PR-012 `Files/new` 列出但此前缺失）。pinned `UPSTREAM_COMMIT = a9cf1280…`、`VERSION = "0.9.8.3"`、`SUPPORTED_OPERATIONS`、`HubHandshake` 五态枚举、`HubLoadRequestV0_9_8_3`（**`extra="allow"` 保留未知字段**）、`classify_version()`、`supports()`、`load_request_from_profile()` | 见 §5 | 见 §5 |
| `src/lva/providers/hub_events.py` | **新增**。`HubEventStreamClient`：注入 `connect` 工厂、有界指数退避（0.5s → 10s 封顶）、成功连接重置退避、`reconnect_count` 计数、`stop()` 可控 | 见 §5 | 见 §5 |
| `src/lva/providers/hub_control.py` | 新增 `probe_handshake()`（版本判定 → READY/DEGRADED/UNAVAILABLE）、`supports()`（**handshake 前一律 false，fail closed**）、`_require()`（操作前门控）、`HubOperation` 类 + `begin_operation()`/`operation()`/`note_progress()`/`complete_operation()`、`verify_loaded()`（有界轮询，阻止 ack 被误判 READY）；`load_model` 改为经 `_require` + `load_request_from_profile` 校验后发送；`stop_model` 经 `_require` | 见 §5 | 见 §5 |
| `tests/fixtures/hub/` | **新增目录 + 4 个文件**：`version_0_9_8_3.json`、`version_unknown.json`、`models_config_get.json`（含 `futureUnknownKey` 用于验证未知字段保留）、`README.md`（脱敏规则） | — | — |
| `tests/red_v121/test_red_hub_control.py` | **新增 RED 套件**（12 项） | 见 §5 | 见 §5 |

未修改：三个生成制品（**零契约改动**）、冻结计划与历史报告、Rust 侧、`Cargo.toml`/`Cargo.lock`、前端。

---

## 3. PR-012 验收条逐项处置

| 冻结要求（L1257） | 半片 | 本轮 | 判定 |
|---|---|---|---|
| pinned fixture smoke | 1 | `tests/fixtures/hub/` 三个 fixture + 脱敏断言 | **PASS** |
| **unknown version DEGRADED** | 1 | `classify_version()`：仅 `0.9.8.3` 为 READY，其余（含缺失/无法解析）为 DEGRADED | **PASS** |
| **load HTTP ack 不被误判 READY** | 1 | `verify_loaded()` 有界轮询；`complete_operation(verified=False)` → `state="failed"` | **PASS** |
| 无 auto-unload API | 1 | 无 auto-unload 方法或端点（断言改为查调用面而非字面，见 §7.1） | **PASS** |
| WS reconnect | 1 | `hub_events.py` 有界指数退避 | **PASS** |
| async operation tracking | 1 | `HubOperation` + `operation_id` 索引 | **PASS** |
| **127.0.0.1 URL 但 Hub 同时监听 0.0.0.0 时 control 被拒绝** | **2** | **未实现**——需消费 PR-008 attestation | **待半片 2** |
| **无法证明 bind 时 `UNVERIFIED_BIND`** | **2** | **未实现**——同上 | **待半片 2** |
| 消费 PR-008 typed attestation，`VERIFIED_LOOPBACK` 之外 fail closed | **2** | **未实现**——通道未定案 | **待半片 2** |

### 3.1 半片 1 的诚实边界

**这三项必须等半片 2**，因为它们的共同前提是「Core 能拿到 attestation」。在半片 1 完成后，`hub_control` 的 loopback 安全检查**仍只是自己写的 hostname 白名单**（`_verify_loopback_safety`），**不是**消费 PR-008 的 attestation。**不得**把半片 1 的完成读作「bind 门控已就绪」。

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_hub_control.py` | 改前 **10 failed / 2 passed** → 改后 **12 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **3 failed / 185 passed**（起始 3F/173P；+12 全为本轮转绿，**无新增红**） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0 |
| 导入 | `import lva.providers.hub_control, hub_events, hub_contracts_v0_9_8_3` | `IMPORT_OK` |
| ruff | `ruff check src/lva tests/run_groups.py` | All checks passed |
| codegen zero-diff | `python -m lva.contracts.codegen --verify` | 三制品全部 `verified` |

### 4.1 三个生成制品（末态复核，逐字节未变）

| 制品 | 字节 | 文件字节 SHA256 |
|---|---|---|
| `schemas/lva-ipc-v1.json` | 55,463 | `EC6F3BB46B6A37402CA8E5ECCC71DDA479B6BA54216C249ABAC46751CC310C8C` |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 16,319 | `C836F691743D3074E49354EDE8AF3E67F320430BBFAA9A8C312CBD19C6AE5B5D` |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 78,138 | `D307E1C519368E19395FA2F4EDA972A37AD5B3221764E00F951E321DAF012185` |

---

## 5. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| 对真实 llama.cpp-hub 的握手（真实 `/api/sys/version`） | 未验证 | 本机未运行 Hub；`probe_handshake()` 的真实 HTTP 路径未取证。fixture 覆盖判定逻辑，**不覆盖真实响应形状** |
| 真实 WS 事件流与真实重连 | 未验证 | `HubEventStreamClient` 的 `connect` 为注入工厂；重连**策略**有实现，真实 Hub 事件流未测 |
| 真实异步 load 的进度跟踪 | 未验证 | 需真实 Hub 与真实模型加载 |
| Rust 侧 | 未运行 | 本轮零 Rust 改动 |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

---

## 6. 基线与末态

| 项 | 起始 | 末态 |
|---|---|---|
| HEAD | `cf1c96752ffb752de1581860968d5189cd6e2a2c` | 同（未变） |
| `tests/red_v121` | 3 failed / 173 passed | **3 failed / 185 passed** |
| 三生成制品 | EC6F…/C836…/D307… | **逐字节一致** |

---

## 7. 差异报告（只报告，未自行修正）

1. **本轮我自己的一处测试缺陷（已修）**：初版 `test_no_auto_unload_api_is_exposed` 用 `re.search(r"auto[_-]?unload", sources)` 匹配整个 `providers/`，结果**把 `hub_control.py` 里「Hub has no auto-unload」这句正确注释判为违规**，造成 1 项假红。已改为只查**调用面**（`def *auto_unload*` 与 `'/*auto_unload'` 端点字面），并加注释说明。
2. **新建目录需提权**：`E:\AI\LocalVoiceAgent\tests\fixtures\hub` 在沙箱内创建被拒（E 盘只读），已按规程提权创建（仅新建空目录，未改任何既有文件）。
3. **半片 1 不构成 bind 门控**：见 §3.1。`hub_control` 的 loopback 检查仍是自有 hostname 白名单，**不是** PR-008 attestation 消费。这是设计稿要解决的问题，不得混淆。
4. **`classify_version` 的粒度**：当前只区分「等于 pinned 版本」与「其它」。计划 L578 的「probes partially pass」语义（哪些 probe 通过决定哪些能力可用）尚未细分——`supports()` 目前按 handshake 状态返回固定集合。完整 capability 矩阵属半片 2 或 PR-013。
5. **`hub_contracts_v0_9_8_3.py` 的字段取自计划 L592 的列举**（`cmd`/`extraParams`/`llamaBinPathSelect`/vision/device/mg/node）。**真实 Hub 的 `/api/models/config/get` 响应形状未取证**，fixture 是按其语义构造的样例，不是实测回放。若后续拿到真实脱敏响应，应更新 fixture 与 DTO。

---

## 8. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言（§7.1 的假红是**修正我自己的测试缺陷**，不是放宽产品断言）；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/`；**未执行任何 git 写操作**。E 盘写入经 `apply_patch`（目录创建经提权，见 §7.2）。**本轮零契约改动、零新增依赖、未申请网络授权。**

## 9. 下一片

`tests/red_v121` 剩余 **3 项红**：

| 项 | 归属 | 阻塞 |
|---|---|---|
| `test_core_actually_wires_a_hub_saga` | PR-014（Wave 4） | 需半片 2 的 attestation 门，否则架空 L665 |
| `test_rust_exposes_no_direct_model_lifecycle_commands` | PR-015（Wave 5） | 未到该 wave |
| `test_legacy_1234_default_is_gone` | PR-015（Wave 5） | 未到该 wave |

**建议**：等设计稿获批后再做半片 2，然后 PR-014 才能在**有门**的前提下接 saga。

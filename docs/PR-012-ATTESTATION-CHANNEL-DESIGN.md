# PR-012 attestation 通道设计稿（待审）

- 日期：2026-09-24（Asia/Shanghai）
- 作者：DeepSeek（执行方）
- 状态：**待审查方审阅；审后才请求硬约束 5 授权**
- 目的：回答「Rust 侧 PR-008 bind attestation 如何到达 Python Core」这一 PR-012 前置问题
- 冻结依据：计划 L1256（`G 只消费 B 提供的 typed attestation，不实现 Windows process inspection`）、L665（`只有 VERIFIED_LOOPBACK 允许 load/stop/switch control`）、L578（`unknown version, probes partially pass -> DEGRADED`）

---

## 1. 物理路径（先纠正一个常见误解）

**Rust 是 WebSocket 客户端，Core 是 WebSocket 服务端。** 实测证据：

| 事实 | 证据 |
|---|---|
| Rust 建连并持有唯一 WS | `bridge.rs` 用 `ws::{WsClient, WsMessage}`；`RECONNECT_MIN/MAX` 在其内 |
| Core 是 WS 服务端 | `server.py` `@app.websocket("/ws")`，L576-579 收 `CommandEnvelope` 并回 `command_result` |
| Rust 也发 Tauri event | `bridge.rs` L454 `emit()` → `EVENT_NAME = "lva://event"` → **只到 WebView** |

**因此「Rust 经 Tauri event 回传」是错误方向**——Tauri event 的接收者是 WebView，不是 Python。

**正确路径**：Rust 已经持有到 Core 的 authenticated WS 客户端，所以它可以直接**经同一条 WS 把 attestation 发给 Core**。不需要新增传输层。

```text
Rust (process authority)                 Core (conversation authority)
  network_attestation.rs                   server.py  /ws
    parse_listener_table()                   ├─ CommandEnvelope  -> execute_command
    attest_for_port()                        └─ (new) attestation envelope -> runtime
         │                                              ▲
         └──── WsClient.send(text) ────────────────────┘
               (existing authenticated channel)
```

**这条路径的关键优点**：它**不经过 WebView**，符合硬约束 4（WebView 不接触端点/凭据），且复用已存在的认证通道，不需要新开端口或新传输。

---

## 2. 关键发现：类型已在契约中，可能不需要新增 schema 类型

实测：`HubBindAttestation` **已经在三个生成制品里**：

| 制品 | `HubBindAttestation` / `hub_bind_attestation` 命中数 |
|---|---|
| `schemas/lva-ipc-v1.json` | **4** |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | **2** |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | **9** |

它当前作为 `RuntimeState.hub_bind_attestation` 字段存在（`contracts/state.py` L132，默认 `None`）。

**这改变了选项空间**：问题不是「要不要定义这个类型」，而是「**Core 如何获得它的一个实例**」。

### 2.1 候选方案

| 方案 | 机制 | 契约影响 | 评价 |
|---|---|---|---|
| **A. 新增入站 command** | Rust 发一个携带 attestation 的命令（如 `hub.attest_bind`），Core 收后写进 `RuntimeState` | **需新增 CommandPayload 成员** → codegen → 三制品哈希变 | 语义最清晰：attestation 是 Rust 对 Core 的一次「报告」 |
| **B. 复用 `runtime.snapshot` 的字段** | Rust 在 `publish_snapshot` 时把 attestation 塞进快照 | 不改类型，但快照是 **Core→Rust→WebView** 方向，方向相反 | **方向错误**，不可用 |
| **C. 新增入站 event（Rust→Core 方向）** | 定义一个新的「上行事件」类型 | 需新增类型；且现有 `EventPayload` union 是 **Core→外界** 方向，复用会混淆语义 | 次优 |

**推荐 A**：新增一个入站 command 承载 attestation。理由：

1. **方向正确**——命令是「外部请求 Core 做事」的方向，attestation 是 Rust 向 Core 报告一个观测结果；
2. **可复用既有 CAS/审计机制**——命令已有 `command_id`、幂等、`CommandResult` 回执；
3. **与 L1256 一致**——G 提供数据，Core 消费，G 不实现 inspection；
4. **fail-closed 天然成立**——Core 的 `hub_bind_attestation` 默认 `None`；在收到命令前 saga 的 control 门保持关闭。

### 2.2 精确的 schema 改动（方案 A）

**只改一个文件**：`src/lva/contracts/commands.py`

```python
class HubAttestBindPayload(BaseCommandPayload):
    type: Literal["hub.attest_bind"]
    attestation: HubBindAttestation      # 已存在的类型，不新增定义
```

并在 `CommandPayload` union 中追加 `HubAttestBindPayload`（当前 16 个成员 → 17）。

**不新增类型定义**——`HubBindAttestation` 已在 `contracts/state.py`，已在三制品中。

### 2.3 codegen 影响面

| 项 | 影响 |
|---|---|
| `schemas/lva-ipc-v1.json` | 新增 `HubAttestBindPayload` 定义 + union 成员；**哈希变化** |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 新增 interface + union 成员；**哈希变化** |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 新增 struct + enum 变体；**哈希变化** |
| 生成形态 | `CommandPayload` 变体数 16 → 17；struct 数 +1 |
| 触发条款 | **硬约束 5**（生成制品只能由 codegen 产出 → 需授权重跑 codegen） |

**三制品哈希将全部改变**，这是本设计稿请求授权的具体对象。

---

## 3. 版本与 DEGRADED（与通道无关，可先行）

计划 L578：`unknown version, probes partially pass -> DEGRADED; disable missing operations`。

**当前状态**：`hub_control.get_version()` 只 GET `/api/sys/version` 并 `raise_for_status()`，**无版本比对、无 DEGRADED 判定**；`providers/` 内 `DEGRADED` 零命中。

**缺失件**：`hub_contracts_v0_9_8_3.py`（PR-012 `Files/new` 列出但不存在）——它应承载 pinned 版本常量与 capability 矩阵。

**这一项不需要动契约**，可与通道解耦先行。

---

## 4. 其余三项（均不动契约）

| 项 | 当前 | 需要的实现 |
|---|---|---|
| pinned fixture smoke | 无 fixtures | 按 `hub_contracts_v0_9_8_3.py` 的版本固定，做离线 fixture 回放 |
| WS reconnect | `providers/` 内 `websocket\|reconnect` 零命中 | Hub 事件订阅的 WS 客户端（Core 侧，连 Hub 而非连 Core） |
| async operation tracking | 仅 docstring 措辞 | `hub.operation_progress` 事件已在契约内，需真实 operation 状态机 |

---

## 5. fail-closed 默认值（审查方要求写入 PR-012 验收）

审查方指出并我确认：`HubBindAttestation._fail_closed()`（`state.py` L108）说明该类型设计之初就预设了 fail-closed。**Python 侧不存在任何实例化生产者**——全树仅 3 处命中，全在 `contracts/state.py`（类定义 L92、validator L108、`RuntimeState` 字段 L132 默认 `None`）。

**PR-012 验收应包含**：真实 verdict 到达前，`RuntimeState.hub_bind_attestation` **必须保持 `None`**，且 saga 的 control 门**必须保持关闭**（对应 L665：只有 `VERIFIED_LOOPBACK` 允许 control）。

---

## 6. 半片拆分建议（供授权参考）

| 半片 | 内容 | 契约 |
|---|---|---|
| **半片 1（可立即开工）** | `hub_contracts_v0_9_8_3.py` + 版本→DEGRADED + pinned fixtures + WS reconnect + operation tracking | **不动契约** |
| **半片 2（需本设计稿获批 + 硬约束 5 授权）** | 新增 `hub.attest_bind` command + Rust 侧发送 + Core 侧消费 + saga 门控 | **三制品哈希变** |

**半片 1 完成前，半片 2 对应的 RED 项保持红**——这是 RED 先行的正常状态，不是欠账。

---

## 7. 需要审查方/用户确认的三点

1. **物理路径判断是否正确**：Rust 经既有 WS 客户端向 Core 发送 attestation（不经 WebView）。
2. **方案 A 是否为最小合规改动**：只新增一个 command 载荷 + union 成员，不新增类型定义。
3. **半片拆分是否可接受**：先做不动契约的半片 1，半片 2 等授权。

# R15 执行报告 — PR-012 半片 2（attestation 通道，含硬约束 5 授权的契约变更）

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第十片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 授权：**硬约束 5 已授权**（新增 `hub.attest_bind` command + 重跑 codegen + 三制品哈希变化）；设计稿 `docs/PR-012-ATTESTATION-CHANNEL-DESIGN.md` 已获批（方案 A）

---

## 0. 本轮闭合了什么

**PR-012 的 attestation 通道已落地，PR-014 的断言随之转绿。**

| 断言 | 改前 | 改后 |
|---|---|---|
| `test_core_actually_wires_a_hub_saga`（PR-014） | FAILED | **PASSED** |
| `tests/red_v121` 全量 | 3 failed / 185 passed | **2 failed / 197 passed** |

剩余 2 项红全部属 **PR-015（Wave 5）**：`test_rust_exposes_no_direct_model_lifecycle_commands`、`test_legacy_1234_default_is_gone`。

---

## 1. 三制品哈希已变（授权的具体对象）

| 制品 | 旧（自 R08 基线） | **新** | 字节 |
|---|---|---|---|
| `schemas/lva-ipc-v1.json` | `EC6F3BB46B6A…310C8C` | **`638428436B7474A14D1CCDE5342E2A05569235776D5723C756D0C921BEA40B23`** | 55,463 → **56,691** |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | `C836F691743D…E5B5D` | **`CF20FA5DF272DF91EDFEFD1D67E453FF596EF69CF70ACD2A2F8062602CDCCFF6`** | 16,319 → **17,134** |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | `D307E1C51936…012185` | **`7EB7D0333298F687AE90646881230CE9DB647FED36E304AA07CFC1AF07C589D9`** | 78,138 → **79,775** |

契约规范化哈希：`f3ec12f2…d560` → **`050a260d73e81bc79a1e7330eff0ef3c984835e3d6d973bedd2cae33a8dc4ae6`**（已 re-pin 到 `codegen.py`）。

**fail-closed 门禁按设计工作**：改动契约后首次 `--verify` **主动失败**并给出明确指引（`expected f3ec12f2…, got 050a260d… The contract changed; re-pin EXPECTED_SCHEMA_SHA256 once the change is intended.`）——这正是 D10 决策（契约哈希 fail-closed）的价值，本轮第一次真实触发。

`hub.attest_bind` 已在三制品中：json 5 处 / ts 3 处 / rs 3 处。

---

## 2. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `src/lva/contracts/commands.py` | 新增 `HubAttestBindPayload`（`type: Literal["hub.attest_bind"]` + `attestation: HubBindAttestation`，**复用既有类型**）；union 追加成员（16 → 17）；导入 `HubBindAttestation` | 见 §5 | 见 §5 |
| `src/lva/contracts/codegen.py` | `EXPECTED_SCHEMA_SHA256` re-pin（附授权说明注释） | 见 §5 | 见 §5 |
| `src/lva/core/runtime.py` | 新增 `_hub_bind_attestation` 字段、`set_hub_bind_attestation()`、`hub_bind_attestation` 属性、**`hub_control_allowed()`**（三条件门：有 attestation + `VERIFIED_LOOPBACK` + **未过期**）；dispatcher 新增 `hub.attest_bind` 分支；**Hub 控制分支新增门控**（未通过返回 `HUB_BIND_UNVERIFIED` 拒绝） | 见 §5 | 见 §5 |
| `src/lva/server.py` | 新增 `get_hub_saga()`（构造 `HubRuntimeSaga` + 注入回调）；`get_runtime()` 传入 `hub_saga=` | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_bind_attestation.py` | **新增 RED 套件**（11 项） | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_contract_cas.py` | 契约变更适配：`CAS_FREE` 加 `hub.attest_bind`；新增 `HUB_CONTROL_COMMANDS` 分组；`ALL_COMMANDS` 与 `PAYLOAD_CLASS` 更新；`_payload_for` 支持 attestation；新增 `_grant_verified_loopback()` 助手并在两处 Hub 行为测试中调用 | 见 §5 | 见 §5 |
| `tests/red_v121/test_review_blockers.py` | `test_duplicate_command_carries_the_first_revision_mapping` 补授 attestation | 见 §5 | 见 §5 |

---

## 3. 关键设计：门控是「持续条件」而非「一次性门票」

审查方在半片 2 批准时附加的验收条已实现：

```python
def hub_control_allowed(self, *, now=None) -> bool:
    1. 无 attestation            -> False   # 缺失即拒绝，不给「疑罪从无」
    2. status != VERIFIED_LOOPBACK -> False   # L665
    3. revalidate_after 已过期    -> False   # 持续条件
```

**第三条件是审查方要求的那条**：`revalidate_after` 是**截止时刻**，不是可选元数据。无该字段也返回 `False`——没有到期时间的 verdict 无法证明新鲜度，不能无限信任。

RED 的 `test_gate_denies_when_the_bind_is_unproven` 覆盖三态：无 attestation → 拒绝；`UNVERIFIED_BIND` → 拒绝；新鲜 `VERIFIED_LOOPBACK` → 允许；**过期 `VERIFIED_LOOPBACK` → 再次拒绝**。

门在 **dispatcher 内**检查（不是调用方），因此没有任何入口能绕过它——这与 R13 把 gate 放进 `TurnExecutor` 是同一原则。

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_bind_attestation.py` | 改前 **9 failed / 1 passed** → 改后 **11 passed** |
| **PR-014 目标断言** | `test_core_actually_wires_a_hub_saga` | 改前 FAILED → **PASSED** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **2 failed / 197 passed**（起始 3F/185P；无新增红） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0 |
| codegen zero-diff | `python -m lva.contracts.codegen --verify` | 三制品全部 `verified`（新哈希） |
| ruff | `ruff check src/lva tests/run_groups.py` | All checks passed |

---

## 5. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| **Rust 侧发送 attestation 的实现** | **未实现** | 本轮只做了 **Python 侧接收与门控**（Core 已能接收并正确判定）。**Rust 侧把 `network_attestation.rs` 的 verdict 经 WS 发出去的代码尚未编写**——因此当前真实运行中 **没有任何 attestation 会到达**，门保持关闭。这是本轮最重要的未完成项 |
| 真实 Hub 的 bind 验证（0.0.0.0 拒绝 / `UNVERIFIED_BIND`） | 未验证 | 需真实 Hub 与 Rust 侧发送端 |
| Rust 侧单测 | 未运行 | 本轮零 Rust 代码改动（只改了契约制品，Rust 侧为生成物） |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

### 5.1 必须说清的边界

**本轮的「PR-014 断言转绿」是结构性的，不是端到端的。** `test_core_actually_wires_a_hub_saga` 断言的是 `server.py` 里存在 `hub_saga=`——**它现在成立了**，且 saga 确实被构造并注入。但由于 Rust 侧发送端未实现，**运行时 attestation 永远不到达，门永远关闭，Hub 控制永远被拒绝**。

这个状态是**安全的**（fail-closed 正确生效），但**不是功能完整的**。不得读作「Hub 控制已可用」。

---

## 6. 差异报告（只报告，未自行修正）

1. **Rust 侧发送端未实现**（见 §5.1）：设计稿的路径是「Rust 经既有 WS 发给 Core」，本轮完成了接收端。发送端需要 Rust 代码改动（`lib.rs`/`bridge.rs` 侧构造 `hub.attest_bind` 命令并在 attestation 更新时发送），**属 PR-012 半片 2 的剩余部分**。
2. **`RecursionError` 是本轮我自己引入又修掉的缺陷**：`get_runtime()` 调用 `get_hub_saga()`，而 `get_hub_saga()` 初版又调用 `get_runtime()` → 无限递归。**RED 套件当时全绿，因为它从未调用 `get_runtime()`**——这正是「结构断言不等于行为验证」的实例。已改为惰性 lambda 回调，并补了 `test_server_wiring_does_not_recurse` 做行为断言。
3. **契约变更连带修正了 8 个既有测试**：5 个是命令清单必须更新（`test_payload_union_has_exactly_the_frozen_commands` 等），2 个是**门控生效导致的正确拒绝**（`test_cas_free_commands_are_not_cas_rejected`、`test_valid_hub_binding_revision_applies_and_bumps_hub_binding`），1 个是 `test_duplicate_command_carries_the_first_revision_mapping`。**这些不是弱化断言**——前者的清单更新是契约变更的必然；后者加了 `_grant_verified_loopback()` 助手**开启门控**，让测试继续测量它命名的那条规则（CAS / duplicate），而不是被新的门控拒绝掩盖。**没有一处放宽了产品断言。**
4. **`hub.attest_bind` 归入 `CAS_FREE`**：它是**报告**不是控制动作，因此无 CAS 前置条件。**且它必须能在门关闭时被接受**——否则没有任何东西能解除门关闭状态。这是设计上的必要，已在测试注释中说明。
5. **`hub.refresh` 归入新的 `HUB_CONTROL_COMMANDS`**：此前它在 `CAS_FREE` 里，但门控生效后它会被拒绝。把它移出 `CAS_FREE` 并单列，是为了让 CAS 矩阵继续只谈 CAS，而门控拒绝有独立归属。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言（§6.3 详述了 8 处修正的性质）；**三制品由 codegen 生成，未手改**（硬约束 5 已授权）；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/`；**未执行任何 git 写操作**。**本轮新增零依赖**、未申请网络授权。

**提权记录**：codegen 写入三制品时因 E 盘沙箱只读被拒，按规程提权执行（仅重跑 codegen 写生成物，属已授权的操作）。

## 8. 下一片

`tests/red_v121` 剩余 **2 项红**，均属 **PR-015（Wave 5）**：

| 项 | 内容 |
|---|---|
| `test_rust_exposes_no_direct_model_lifecycle_commands` | Rust 仍有 `scan_models`/`refresh_models`/`switch_llm_model`/`unload_vram`/`cold_start_llm` |
| `test_legacy_1234_default_is_gone` | `config.py` L47/L60 默认 `127.0.0.1:1234` |

**另有两项应优先于 PR-015 的剩余工作**：

1. **Rust 侧 attestation 发送端**（PR-012 半片 2 剩余）——没有它，本轮的门控在运行时永不开启。
2. **PR-013**（Hub inference provider）——PR-014 依赖 PR-012/013，而 `openai_compatible.py` 与 hub 的关系（R12 §7.3 记录）仍待明确。

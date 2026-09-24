# R17 执行报告 — PR-012 attestation 通道端到端验证

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 CONTEXT-HANDOFF-LVA-R08-2026-09-24.md 之后的第十二片）
- 仓库：E:\AI\LocalVoiceAgent
- HEAD：cf1c96752ffb752de1581860968d5189cd6e2a2c（未提交、未推送、未 reset/checkout/clean）
- 范围来源：R15/R16 两轮共同留下的**唯一未验证环节**（真实送达）+ 审查方「端到端探针优先于 PR-015」的建议

---

## 0. 本轮闭合了什么

**PR-012 的 attestation 通道现在有端到端证据，不再是「两端代码齐备」。**

```text
PASS no-attestation -> gate denied (rejected/HUB_BIND_UNVERIFIED)
PASS UNVERIFIED_BIND -> control_allowed=False
PASS fresh VERIFIED_LOOPBACK -> control_allowed=True
PASS gate open -> command got past the gate (applied/None)
PASS expired VERIFIED_LOOPBACK -> control_allowed=False
PASS gate closed again -> denied (rejected/HUB_BIND_UNVERIFIED)
summary: 6/6 passed
```

探针在**真实 uvicorn + 真实 /ws 路由 + 真实 WebSocket 客户端**上运行，只 stub 了 VoiceCore（本机无音频设备、缺 MeloTTS 模型），与 R07 互操作探针同一模式。

---

## 1. 探针设计

**文件**：scripts/probe_attestation_e2e.py

| 步骤 | 断言 | 验证的冻结条款 |
|---|---|---|
| 1 | 无 attestation -> rejected / HUB_BIND_UNVERIFIED | L665 的 fail-closed 默认 |
| 2 | UNVERIFIED_BIND -> control_allowed=False | L580 |
| 3 | 新鲜 VERIFIED_LOOPBACK -> control_allowed=True | L665 的正向条件 |
| 4 | 门开后同一命令**通过门**（applied） | 门确实会放行，不是恒拒 |
| 5 | 过期 VERIFIED_LOOPBACK -> control_allowed=False | **审查方附加的「新鲜度」验收条** |
| 6 | 门再次关闭 -> 回到 HUB_BIND_UNVERIFIED | 门是**持续条件**而非一次性门票 |

**命令形状与 Rust 侧一致**：探针构造的 hub.attest_bind 信封字段（status / reason_code / checked_at / attestation_id / revalidate_after）与 lib.rs::send_bind_attestation 逐字段对应，因此它验证的是 **Rust 实际会发出的形状**，不是一个人造变体。

---

## 2. 探针暴露的一个真实次序事实（重要）

**CAS 在 attestation 门之前检查。** 探针首轮运行给出 4/6，两项失败的原因不是门坏了，而是：

hub.bind_model 不带 precondition 时被 **STALE_REVISION** 拒绝——**门根本没有被咨询**。

这说明 execute_command 的次序是：

```text
1. CAS precondition 检查      <- 先
2. _dispatch_command          <- 后，attestation 门在这里
```

**两条路径都拒绝（fail-closed 成立），但它们是不同的失败模式。** 要测量门本身，命令必须携带**有效的** hub_binding revision。探针已据此修正（每处 hub.bind_model 都带 hub_rev()）。

**这是一个值得记录的语义边界**：客户端看到一个 Hub 控制命令被拒时，**无法从 status 区分**「CAS 陈旧」与「bind 未验证」——两者都是 rejected，只有 error.code 不同（STALE_REVISION vs HUB_BIND_UNVERIFIED）。UI 若需引导用户，应读 error.code 而非 status。

---

## 3. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| scripts/probe_attestation_e2e.py | **新增**端到端探针。含 StubCore、noop_lifespan、_attestation() 形状构造、run_checks() 六步断言、main() 自起 uvicorn 线程 | 见 §5 | 见 §5 |

未修改：src/lva 任何产品代码（**本轮纯验证，零产品改动**）、三个生成制品、Rust 侧、冻结计划与历史报告。

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| **端到端探针** | python scripts/probe_attestation_e2e.py 端口 令牌 ready文件 | **6/6 passed，EXIT=0** |
| tests/red_v121 全量 | pytest tests/red_v121 | **2 failed / 204 passed**（与 R16 末态相同，**无回归**） |
| v12 层 7 组 | run_groups.py --layer v12 | **all groups passed** |
| codegen zero-diff | python -m lva.contracts.codegen --verify | 三制品全部 verified |
| Rust 单测 | 未重跑（本轮零 Rust 改动） | 沿用 R16 的 55 passed / 0 failed / 1 ignored |

---

## 5. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| **Rust 二进制真实发出 attestation** | **未验证** | 探针用**与 Rust 相同形状**的信封验证了接收与门控；但**没有驱动真实的 lva-pet.exe 进程去发送**。要闭环这一点，需启动 Tauri 应用并观察它周期发送（需 GUI 环境 + 真实 Core） |
| 真实 Hub 的 bind 判定 | 未验证 | 本机未运行 llama.cpp-hub |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

### 5.1 边界的精确表述（避免过度声称）

本轮验证的是：**「Rust 形状的信封经真实 WS 到达真实 Core，并被正确判定与门控」**。

本轮**没有**验证：**「真实 Rust 进程确实按该形状发送」**。后者需要 GUI 环境驱动 Tauri 应用，属未运行项。

因此当前状态可表述为：**接收端与门控已端到端证明；发送端仍是源码级证据（R16）。**

---

## 6. 差异报告（只报告，未自行修正）

1. **CAS 与门的次序未在文档中记录**（§2）：建议在设计稿或 PR-012 验收里补一句，避免后续把 STALE_REVISION 误读为「bind 未验证」。
2. **探针首轮的 4/6 是我探针自身的缺陷**（未带 precondition），**不是产品缺陷**。已修，且修正过程本身产出了 §2 那条次序发现。
3. **探针的 LVA_PROBE_ROOT 依赖调用方提供可写目录**：初版把数据根设为脚本同级目录（仓库内，只读）导致 PermissionError。已改为从环境变量读取，回退到 TEMP。
4. **探针需要 websockets 包**：实测 .venv 内已有 websockets 17.1（项目依赖之一）。无新增依赖。
5. **scripts/ 下新增了探针文件**：它是**验证工具**而非产品代码。若项目希望探针集中在别处（如 tests/probes/），应统一位置——目前仓库内既有探针散落在会话 scratch 目录，本探针是第一个落在仓库内的。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 .venv / venv / benchmarks/；**未执行任何 git 写操作**。**本轮零产品代码改动、零契约改动、零新增依赖、未提权。**

---

## 8. 下一片

tests/red_v121 剩余 **2 项红**，均属 **PR-015（Wave 5）**：

| 项 | 内容 |
|---|---|
| test_rust_exposes_no_direct_model_lifecycle_commands | Rust 仍有 scan_models / refresh_models / switch_llm_model / unload_vram / cold_start_llm |
| test_legacy_1234_default_is_gone | config.py L47/L60 默认 127.0.0.1:1234 |

**PR-015 是当前唯一能继续降低 RED 计数的切片**，且它同时清理 1234 双源（R09/R10 遗留）。

**仍未闭环的既有项**（累积）：Rust 进程真实发送 attestation（需 GUI）、PR-013、L463 全合规、_enc 密钥轮换、首次 commit 授权、R15 追溯审查（可选）。

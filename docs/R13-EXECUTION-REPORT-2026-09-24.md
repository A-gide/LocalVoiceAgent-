# R13 执行报告 — Wave 3 / PR-010 剩余（选项乙：编排内迁 Core，I22 闭合）

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第八片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 范围来源：冻结计划 PR-010（L1228-1236）+ R10 的选项 (甲) 边界 + 用户裁决（推进选项乙）

---

## 0. 本片闭合了什么

**I22 的最后一处真实缺口。** R10 落地选项 (甲) 后，`test_no_route_bypasses_the_command_dispatcher` 仍报：

```
ask() calls ['append_event', 'stream', 'synthesize']
```

即 `/api/ask` 虽经 dispatcher 开启 turn，但**编排（prompt 构造 → LLM 流 → TTS → Journal 提交）仍在 route 体内**。本轮把这段编排移进 Core，route 退化为纯传输适配器。

**该断言现已转绿。** `tests/red_v121` 从 **4F/165P → 3F/173P**。

---

## 1. 设计约束与解法（本片的技术核心）

障碍是 R10 已确认的事实：**`RuntimeController` 刻意不持有 provider/pipeline 引用**——Core 状态机与具体客户端解耦。所以「把编排搬进 Core」不能靠在 `core/` 里 `import llm` 了事，否则就把刚建立的分层又拆掉。

解法：**Core 定义执行体，owner 注入窄回调。**

```text
server.py (owner)                          core/ (state authority)
  c.vocab.correct        ──┐
  c._prompt_messages     ──┼── narrow callables ──►  TurnExecutor
  LLM.stream             ──┤                          ├─ gate2 (in-stream)
  c.tts.synthesize       ──┤                          ├─ gate3 (tts_playback)
  A.to_wav_bytes         ──┤                          ├─ gate3 (journal_commit)
  TX.strip_for_speech    ──┘                          └─ complete_turn
  journal.append_event   ────────────────────────────►
```

`TurnExecutor` 只接收**可调用对象**与 journal 句柄，不 import 任何具体客户端。这与 PR-011 的 registry 是同一注入形状，两片因此互相加强而非冲突。

**三道 gate 由执行体自己施加，不由调用方负责**——否则一个新入口只要忘记调用就能发出陈旧副作用，而这正是 gate 存在的理由。RED 断言 `test_executor_applies_the_stale_gates` 守护这一点。

---

## 2. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `src/lva/core/turn_executor.py` | **新增**。`TurnOutcome` 数据类 + `TurnExecutor.run_text_turn()`：纠错 → journal 检索 → prompt → LLM 流（**gate2**）→ TTS（**gate3**）→ journal 提交 + `complete_turn`（**gate3**）；provider 异常时 `cancel_turn(reason="provider_error")` 并返回 `failed` | 见 §5 | 见 §5 |
| `src/lva/core/runtime.py` | 新增 `turn_executor: Any` 注入参数与 `self.turn_executor` 字段 | 见 §5 | 见 §5 |
| `src/lva/server.py` | `/api/ask` 由 110 行编排缩为**纯适配器**（仅 `execute_command` + `run_text_turn` + 序列化）；新增 `get_turn_executor()` 工厂（注入 8 个窄回调 + `PL.DEEP_HINTS`）；导入 `TurnExecutor` | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_turn_executor.py` | **新增 RED 套件**（7 项） | 见 §5 | 见 §5 |

未修改：三个生成制品（**零契约改动**——`turn.send_text` 已在契约内，本轮只是把它的执行体搬到 Core）、冻结计划与历史报告、`pipeline.py`（`VoiceCore` 未改；它仍提供 `vocab`/`_prompt_messages`/`tts` 供 owner 注入）、`Cargo.toml`/`Cargo.lock`、前端。

---

## 3. PR-010 验收条逐项处置（L1235）

| 冻结要求 | 本轮 | 判定 |
|---|---|---|
| **`/api/ask` 与所有兼容入口均只进入 dispatcher/TurnController** | route 仅 `execute_command` + 委派 executor；`ws()` legacy 分支已在 R10 改为命令派发 | **PASS** |
| **I22** | `test_no_route_bypasses_the_command_dispatcher` **转绿**；`test_ask_route_adapts_into_a_command` 维持绿 | **PASS** |
| I01 / I03 / I05 | `tests/invariants` 23 passed 无回归；gate2/gate3 由执行体施加 | **PASS（复验）** |
| provider_epoch | 执行体从 `rt.interrupt_controller.provider_epoch` 取值并随 outcome 返回 | **PASS** |
| 所有 effect guard | gate3 分别守护 TTS 与 Journal 两处副作用 | **PASS** |
| typed ask command | `turn.send_text`（契约内已有，R10 已接线） | **PASS** |
| 连续 5 次 barge-in | **未验证** | 需真实音频/交互；`tests/fault` 7 passed 覆盖部分故障路径 |
| 旧 token/audio/history/memory 全部丢弃 | **未验证** | 同上，属真实运行时验收 |
| LLM close、TTS cancel、queue purge、playback stop | 部分：`_abort_playback`（R10）覆盖 playback；`turn.cancel` 触发 `commit_interrupt` | **部分** |

### 3.1 一处诚实说明

「连续 5 次 barge-in」与「旧 token/audio/history/memory 全部丢弃」这两条**依赖真实音频链路**（麦克风、VAD、播放器），本机无音频设备且缺 MeloTTS 模型，**未运行**。本轮验证的是**编排归属与 gate 施加点**，不是端到端打断行为。不得据此宣称 PR-010 全条通过。

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_turn_executor.py` | 改前 **6 failed / 1 passed** → 改后 **7 passed** |
| **I22 目标断言** | `pytest tests/red_v121/test_red_authority.py -k no_route_bypasses` | 改前 **FAILED**（`ask() calls [...]`）→ 改后 **1 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **3 failed / 173 passed**（起始 4F/165P；**无新增红**） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0 |
| 导入 | `import lva.server, lva.core.turn_executor` | `IMPORT_OK` |
| ruff | `ruff check src/lva tests/run_groups.py` | All checks passed |

### 4.1 三个生成制品（末态复核，逐字节未变）

| 制品 | 字节 | 文件字节 SHA256 |
|---|---|---|
| `schemas/lva-ipc-v1.json` | 55,463 | `EC6F3BB46B6A37402CA8E5ECCC71DDA479B6BA54216C249ABAC46751CC310C8C` |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 16,319 | `C836F691743D3074E49354EDE8AF3E67F320430BBFAA9A8C312CBD19C6AE5B5D` |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 78,138 | `D307E1C519368E19395FA2F4EDA972A37AD5B3221764E00F951E321DAF012185` |

**契约未动的直接好处**：`turn.send_text` 早已在契约内，把它的执行体搬进 Core 是**纯实现迁移**，不需要 schema 变更、不需要 codegen 重跑。

---

## 5. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| `/api/ask` 真实端到端（起 uvicorn、发请求、拿到真 LLM 回复） | 未验证 | 本机无音频设备、缺 MeloTTS 模型；`tests/integration` 11 passed 是既有覆盖 |
| 连续 5 次 barge-in | 未运行 | 需真实音频链路 |
| 旧 token/audio/history/memory 丢弃的运行时证据 | 未验证 | 同上 |
| `ws()` 的 `kind == "ask"` 路径 | 未验证 | 它经 `_ws_ask` → 同一 route → 同一 executor，逻辑上已收敛，但未做 WS 级端到端 |
| Rust 侧 | 未运行 | 本轮零 Rust 改动 |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

---

## 6. 基线与末态

| 项 | 起始 | 末态 |
|---|---|---|
| HEAD | `cf1c96752ffb752de1581860968d5189cd6e2a2c` | 同（未变） |
| `status --porcelain=v1` | 96 行 | **97 行**（+1 本报告；`core/` 下新增文件落入既有聚合项） |
| `status --porcelain=v1 -uall` | 259 行 | **262 行**（+1 本报告 +1 新 RED 文件 +1 `src/lva/core/turn_executor.py`） |
| `tests/red_v121` | 4 failed / 165 passed | **3 failed / 173 passed** |
| 三生成制品 | EC6F…/C836…/D307… | **逐字节一致** |

---

## 7. 差异报告（只报告，未自行修正）

1. **`pipeline.py` 的 `VoiceCore` 未改**：本轮把编排移进 Core 时，`VoiceCore` 仍是 `vocab` / `_prompt_messages` / `tts` 的提供者，owner 从它取回调注入 executor。**这不违反 I22**（route 不再直接调用 provider），但意味着 `VoiceCore` 仍是具体客户端的持有者。按计划 L1236「旧旁路 route 到 PR-037 才删」，这是预期的中间态。
2. **`_prompt_messages` 是私有方法**：executor 通过注入的 `build_messages` 回调调用它，未直接访问。若 PR-011/PR-032 之后要公开 prompt 构造，应改由 provider 端口提供而非继续依赖下划线方法。
3. **`ws()` 的 `_ws_ask` 仍调用 route 函数**：它 `await ask(AskBody(**body))`，因此逻辑上已收敛到同一路径，但形式上仍是一次函数调用而非命令派发。若严格按 I22 字面（「所有兼容入口只进入 dispatcher」），`_ws_ask` 应改为发 `turn.send_text` 命令。**本轮未改**——它已经间接满足约束，改动收益低而回归风险存在。
4. **`TurnExecutor` 的错误语义**：provider 异常时返回 `outcome.failed` 而非抛异常，route 据此抛 503。这与原实现的 503/500 二分不同（原实现区分 `LLMError`→503 与其它→500）。**本轮统一为 503**。

   **前端影响已核实（审查方要求）**：`apps/desktop-ui/src` 全量检索 `500|503|status ===|statusCode`——**零 HTTP 状态码分支**。命中的 `500` 全部是 CSS `font-weight: 500`（CharacterView/ChatView/MemoryView/SettingsView 等）；`status === 'applied'` / `'rejected'` 是**命令结果状态**，不是 HTTP 状态码。且 desktop-ui **完全不调用** `/api/ask`、`/api/barge_in`、`/api/mode`——它经 Tauri command 走 `send_core_command`。**结论：500→503 变更对前端不可见，可定案。**

---

## 8. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/`；**未执行任何 git 写操作**。所有 E 盘写入均经 `apply_patch`。**本轮零契约改动、零新增依赖、未申请网络授权。**

## 9. 下一片

`tests/red_v121` 剩余 **3 项红**，全部位于 Wave 4/5（RED 先行，非欠账）：

| 项 | 归属 | 备注 |
|---|---|---|
| `test_core_actually_wires_a_hub_saga` | **PR-014**（Wave 4） | `server.py` 未传 `hub_saga=`；需 Hub binding and lifecycle saga |
| `test_rust_exposes_no_direct_model_lifecycle_commands` | **PR-015**（Wave 5） | Rust 仍有 `scan_models`/`refresh_models`/`switch_llm_model`/`unload_vram`/`cold_start_llm` |
| `test_legacy_1234_default_is_gone` | **PR-015**（Wave 5） | `config.py` L47/L60 默认 `127.0.0.1:1234` |

**Wave 3 的 PR-010 剩余已闭合。** 下一步的自然候选是 PR-014（Hub saga，Wave 4，依赖 PR-011/012）或 PR-015（移除 direct llama lifecycle，Wave 5）——但二者都涉及 Hub 面，建议先确认 PR-012（Hub compatibility and control client）是否已具备前置。

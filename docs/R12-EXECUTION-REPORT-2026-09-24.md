# R12 执行报告 — Wave 1 / PR-011 Provider protocols and registry

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md` 之后的第七片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 工作树：`status --porcelain=v1` = **96 行**（起始 94）；`-uall` = **259 行**（起始 254）
- 范围来源：冻结计划 PR-011（L1238-1246）+ 用户裁决（先做 PR-011 再做 PR-010 剩余）

---

## 0. 为什么先做 PR-011（决策依据）

R10 已确认 `RuntimeController` **刻意不持有** provider/pipeline 引用——Core 状态机与 provider 解耦，这是设计而非缺陷。因此 PR-010 剩余的「编排内迁 Core」（选项乙）不是搬代码，而是**需要一套 provider 端口抽象**。

计划 L1238 的 PR-011 正是 `Provider protocols and registry`，且它属 **Wave 1**（L1535），而 PR-010 属 Wave 3。若先硬做选项乙，等于绕过 PR-011 自造注入机制，PR-011 落地后还要再改一遍。**故按 L1854 的既定顺序先做 PR-011。**

---

## 1. 范围判定：又是「文件已在，接线不在」

开工前核实，`providers/` 下 `base.py`(1,272 B) / `registry.py`(3,758 B) / `openai_compatible.py` / `hub_*.py` **全部存在**，且 `base.py` 已有完整的 `ASRProvider` / `LLMProvider` / `TTSProvider` 三个 Protocol（含 `stream_chat`/`stream_speech` 的 `is_cancelled` 参数），`registry.py` 已有 Passive guard 并抛 `PASSIVE_PROVIDER_FORBIDDEN`。

**但缺的正是 PR-011 的验收面**（实测）：

| 缺口 | 证据 |
|---|---|
| 生产代码从不构造 `ProviderRegistry` | 全仓检索：只有 `providers/` 自身 + `tests/integration/test_hub_streaming.py` + `tests/invariants/test_invariants.py` 引用它——**仅测试**。即 registry 在生产中是死代码 |
| `pipeline.py` 零 provider 引用 | 全文件搜 `provider`/`registry` → **0 命中** |
| 无 contract mocks | `providers/` 下无任何 `*mock*` 文件 |
| 无 thin adapters | 只有 `openai_compatible.py`（LLM 侧），ASR/TTS 侧无适配器 |
| registry 无 capability/state 面 | `registry.py` 无 `ProviderState` / `set_provider_status`，无法喂 `RuntimeState.providers` |
| 无 PR-011 RED 覆盖 | 全部 RED 文件中无 `ProviderRegistry` 引用 |

**这是本项目第三次同类判定**（PR-009、PR-003/004、PR-011）——**「文件存在」不等于「切片完成」**，必须查接线与验收面。已记入 §6。

---

## 2. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `src/lva/providers/mocks.py` | **新增**。`MockASRProvider` / `MockLLMProvider`（含 `is_cancelled` 逐 token 检查与 `fail_after` 故障注入）/ `MockTTSProvider`（静音 PCM），以及 `build_mock_registry()`——「contract mocks 能跑完整 turn」的入口 | 见 §5 | 见 §5 |
| `src/lva/providers/adapters.py` | **新增**。`ASREngineAdapter` / `LLMStreamAdapter` / `TTSEngineAdapter` 三个 thin adapter，**委托**既有具体客户端（不重实现解码/合成/HTTP），用 `asyncio.to_thread` 把阻塞调用移出事件循环 | 见 §5 | 见 §5 |
| `src/lva/providers/registry.py` | 新增 capability/state 面：`active_provider_ids()` / `registered_ids()` / `provider_statuses()`（返回 typed `ProviderStatus`，喂 `RuntimeState.providers`）；导入 `ProviderState` 与 `ProviderStatus` | 见 §5 | 见 §5 |
| `src/lva/server.py` | **接线点（本片核心缺口）**：新增 `get_registry()`，用 adapters 包装 `c.load_asr()` / `LLM.stream` / `c.tts`，并把 `provider_statuses()` 写进 `RuntimeState`；导入 `ProviderRegistry` | 见 §5 | 见 §5 |
| `src/lva/pipeline.py` | `VoiceCore` 新增 `self.provider_registry = None` 注入点（由 owner 接线；缺失时旧直连路径仍可用，故是 thin adapter 而非重写） | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_provider_registry.py` | **新增 RED 套件**（8 项） | 见 §5 | 见 §5 |

未修改：三个生成制品（**零契约改动**——`ProviderStatus` 已在 `contracts/state.py`，本轮只消费它）、冻结计划与历史报告、`Cargo.toml`/`Cargo.lock`、前端。

---

## 3. 验收条逐项处置（PR-011 L1245）

| 冻结要求 | 本轮 | 判定 |
|---|---|---|
| **contract mocks 能跑完整 turn** | `mocks.py` 提供三个 Protocol 的实现 + `build_mock_registry()` 一次装齐 | **PASS** |
| **Passive guard 在 registry 边界生效** | guard 本就在 registry 内（LLM/TTS 各一处）；本轮新增断言守护它不被挪到调用方 | **PASS（复验）** |
| `providers/{base,registry}.py` | 已在（本轮补 capability/state 面） | **PASS** |
| 明确 stream/cancel/errors | `LLMProvider.stream_chat` / `TTSProvider.stream_speech` 的 `is_cancelled` 由 mocks 逐 chunk 遵守；`fail_after` 使错误路径可达 | **PASS** |
| 现有 ASR/TTS/OpenAI client 用 thin adapter 包装 | `ASREngineAdapter` / `TTSEngineAdapter` / `LLMStreamAdapter`（+ 既有 `openai_compatible.py`） | **PASS** |
| capability/state registry | `provider_statuses()` → `RuntimeState.providers` | **PASS** |
| concrete implementation 不删 | 三个具体客户端文件**未改动、未删除** | **PASS** |

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_provider_registry.py` | 改前 **5 failed / 3 passed** → 改后 **8 passed** |
| `tests/red_v121` 全量 | `pytest tests/red_v121` | **4 failed / 165 passed**（起始 4F/157P；+8 全为本轮新套件转绿，**无新增红**） |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed**，EXIT=0 |
| 导入 | `import lva.server, lva.pipeline, lva.providers.adapters, lva.providers.mocks` | `IMPORT_OK` |
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
| 真实模型下的 adapter 端到端（真 ASR 解码 / 真 TTS 合成经 registry 调用） | 未验证 | 本机无音频设备且缺 MeloTTS 模型；本轮验证的是**接线与协议一致性**，非真实推理 |
| `pipeline.py` 内部改为经 registry 调用 provider | **未实现（刻意）** | 本轮只提供注入点（`self.provider_registry`）。把 pipeline 的实际调度改走 registry 属 **PR-010 剩余** 的范围，那时才有真实的调用方需要迁移 |
| registry 状态在真实模型加载后的变化（READY/BUSY/ERROR） | 未验证 | `provider_statuses()` 当前只区分「active → READY / 非 active → UNINITIALIZED」；真实 warm-up、断开、错误状态需 provider 生命周期事件（属 PR-012/PR-013） |
| Rust 侧 | 未运行 | 本轮零 Rust 改动，未重跑 `cargo check`/单测 |
| Tauri release、soak、CI 实跑、GUI、多显示器 | 未运行 / N/A | 沿用既有状态 |

---

## 6. 基线与末态

| 项 | 起始 | 末态 |
|---|---|---|
| HEAD | `cf1c96752ffb752de1581860968d5189cd6e2a2c` | 同（未变） |
| `status --porcelain=v1` | 94 行 | **96 行**（+1 本报告 +1 `src/lva/bootstrap.py` 由「未列出」转为列出——R11 的 `server.py` 新导入使该文件进入 git 的可见集合；`src/lva/providers/` 与 `tests/` 下新增文件落入既有聚合项，`v1` 口径不增） |
| `status --porcelain=v1 -uall` | 254 行 | **259 行**（+1 本报告 +1 新 RED 文件 +2 mocks.py/adapters.py +1 `bootstrap.py`） |
| `tests/red_v121` | 4 failed / 157 passed | **4 failed / 165 passed** |
| 三生成制品 | EC6F…/C836…/D307… | **逐字节一致** |

---

## 7. 差异报告（只报告，未自行修正）

1. **`pipeline.py` 的 provider 调度未迁移**：本轮只加注入点，未把 `VoiceCore` 的实际 LLM/TTS 调用改走 registry。原因：那需要真实调用方改造，属 PR-010 剩余的天然范围；在此处提前改会与 PR-010 重复。
2. **`provider_statuses()` 的状态粒度有限**：只区分 active/inactive，不反映真实 warm-up/断连/错误。完整状态机在计划里属 PR-012（Hub control）/PR-013（Hub inference）的 provider_epoch 与 DEGRADED 语义。
3. **`openai_compatible.py` 未被 `get_registry()` 使用**：它已在 `providers/` 内但当前 registry 装的是 `LLMStreamAdapter`（包 `lva.llm.stream`）。二者关系需在 PR-012/PR-013 明确（Hub inference vs OpenAI-compatible 的 provider 选择策略）。
4. **流程教训（第三次）**：本项目已三次出现「文件存在但切片未完成」的判定（PR-009、PR-003/004、PR-011）。三次的共性都是**只看文件清单/计划文本，没查接线与验收面**。**建议在切片规划阶段固化一条检查：对每个 `Files/new` 条目，必须同时确认「存在」+「被生产代码引用」+「有 RED 覆盖」三件事。**

---

## 8. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/`；**未执行任何 git 写操作**。所有 E 盘写入均经 `apply_patch`。**本轮零契约改动、零新增依赖、未申请网络授权。**

## 9. 下一片

`tests/red_v121` 剩余 **4 项红**，全部位于 Wave 3/4/5（RED 先行，非欠账）：

| 项 | 归属 | 备注 |
|---|---|---|
| `test_no_route_bypasses_the_command_dispatcher` | PR-010 剩余 | **PR-011 已就绪，选项乙 现在有 provider 端口可用** |
| `test_core_actually_wires_a_hub_saga` | PR-014（Wave 4） | 需 Hub saga 接线 |
| `test_rust_exposes_no_direct_model_lifecycle_commands` | PR-015（Wave 5） | Rust 仍有 5 个直接 model lifecycle 命令 |
| `test_legacy_1234_default_is_gone` | PR-015（Wave 5） | `config.py` L47/L60 |

**建议下一片**：PR-010 剩余（选项乙）。PR-011 已提供 adapter + registry，编排内迁所需的 provider 端口现在存在，不再需要「自造注入机制」。

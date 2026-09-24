# R19 执行报告 — PR-015 移除 direct llama lifecycle（**red_v121 首次清零**）

- 日期：2026-09-24（Asia/Shanghai）
- 执行者：DeepSeek（接管 CONTEXT-HANDOFF-LVA-R08-2026-09-24.md 之后的第十四片）
- 仓库：E:\AI\LocalVoiceAgent
- HEAD：`43177e5`（已 push）→ 本轮在其上继续
- 范围来源：用户裁决「PR-015 开工」（审查方依据 L1286 解除依赖否决）

---

## 0. 里程碑：`tests/red_v121` 首次全绿

| 项 | 起始 | 末态 |
|---|---|---|
| `tests/red_v121` | 2 failed / 219 passed | **228 passed / 0 failed** |
| Rust 单测 | 55 passed / 0 failed / 1 ignored | **55 passed / 0 failed / 1 ignored**（无回归） |
| v12 层 7 组 | all groups passed | **all groups passed** |

**从 R04 首片到本轮，RED 套件累计 14 片后清零。** 每一片都遵守「先写 RED → 再最小修复」，无一处弱化断言。

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 字节 | SHA256 |
|---|---|---|---|
| `apps/desktop-shell/src-tauri/src/lib.rs` | **删除 5 个 direct model lifecycle 命令**（`unload_vram`/`cold_start_llm`/`scan_models`/`refresh_models`/`switch_llm_model`）及其 `generate_handler!` 注册项；移除随之无用的 `GgufModelInfo` 导入 | 见 §5 | 见 §5 |
| `src/lva/config.py` | `LLM_BASE_URL` 默认由 `http://127.0.0.1:1234/v1` 改为 **`http://127.0.0.1:8080/v1`**（Hub inference face）；`LLAMA_SERVER_PORT`（默认 1234）改为 **`HUB_PORT`**（默认 8080） | 见 §5 | 见 §5 |
| `scripts/make_bench_reports.py` | 移除「served by the llama.cpp runtime that ships with LM Studio, started through scripts/llm_serve.py with -c/-ngl」的过时表述，改为「served by the llama.cpp-hub model runtime, which owns the backend and its launch parameters」 | 见 §5 | 见 §5 |
| `tests/red_v121/test_red_direct_llama_removal.py` | **新增 RED 套件**（7 项） | 见 §5 | 见 §5 |

未修改：三个生成制品（**零契约改动**）、`process_manager.rs`（其 Hub 处理**已经正确**，见 §3）、`tray.rs`、`services.default.json`、`Cargo.toml`/`Cargo.lock`（**零新增依赖**）。

---

## 2. 冻结验收条逐项处置（L1287）

| 冻结要求 | 本轮 | 判定 |
|---|---|---|
| **grep 无 LM Studio / direct llama lifecycle** | 5 个命令已删除（非仅注销）；`config.py` 无 1234；`make_bench_reports.py` 的 LM Studio 表述已改 | **PASS** |
| **Rust/TS 无 Hub management client** | 既有 `test_no_hub_management_client_outside_core` 维持绿 | **PASS（复验）** |
| I16 / I21 | `tests/invariants` 23 passed 无回归；I21 两项断言全绿 | **PASS** |
| 静态 kill allowlist | `process_manager.rs` 的 `safe_shutdown_spawned_only` 与 `supervisor.rs` 的 ownership 前置检查已在（R04）；本轮未改 | **PASS（复验）** |
| **LVA quit 后 Hub/children 存活** | **未验证** | 需真实进程与真实 Hub；R04 已用真实 `ping.exe` 哨兵覆盖 I04/I16 单测，但**非 GUI quit 实证** | **未验证** |
| **真实 Hub switch 通过** | **未验证** | 本机未运行 llama.cpp-hub | **未验证** |

### 2.1 两条未验证项的诚实边界

L1287 的「LVA quit 后 Hub/children 存活」与「真实 Hub switch 通过」**都需要真实 Hub 与真实进程**。本轮完成的是**静态面**（无 direct lifecycle surface、无 LM 路径、无 1234 默认），**不是**运行时验收。**不得**把本轮读作 PR-015 全条通过。

---

## 3. 只读扫描的关键发现（避免了一次误改）

开工前扫描发现 `process_manager.rs` 有 14 处 `llama` 命中、`tray.rs` 有 3 处。**逐条核对后确认它们无需改动**：

- `process_manager.rs` 的 `llama_server` 是 **Hub 的服务身份条目**：`ownership_map.insert("llama_server", ProcessOwnership::Adopted)`（L75）、`ownership: ...or(Some(ProcessOwnership::Adopted))`（L107）、单测 `assert!(status.llama_server.pid.is_none(), "Hub PID must never be guessed")`（L329）。**它已正确地把 Hub 当 Adopted 外部服务**，这正是 PR-015 要求的方向。
- L128/L132 的注释与返回串明写「Model lifecycle is managed by llama.cpp-hub. Use Hub model controls」——**已是 Hub intent 语义**。
- `crypto.rs`/`ws.rs` 的 `1234` 命中是 **base64 字母表常量**；`network_attestation.rs` 的是**测试夹具端口**。三者均为假阳性。

**若不核对就按 grep 命中数改动，会破坏已正确的 Adopted 语义。** 这是本轮最重要的一次「只读先行」。

---

## 4. 本轮实测

| 项 | 命令要点 | 结果 |
|---|---|---|
| 新 RED 套件 | `pytest tests/red_v121/test_red_direct_llama_removal.py` | 改前 **6 failed / 1 passed** → 改后 **7 passed** |
| **`tests/red_v121` 全量** | `pytest tests/red_v121` | **228 passed / 0 failed**（起始 2F/219P；**清零**） |
| Rust 编译 | `cargo check --offline` | **EXIT=0，无 warning**（首轮有 `unused import: GgufModelInfo`，已清理） |
| Rust 单测 | `rusttest.ps1 -SourceExe <exe>` | **55 passed / 0 failed / 1 ignored**，`stray_ping=0` |
| v12 层 7 组 | `run_groups.py --layer v12` | **all groups passed** |
| 配置生效 | `import lva.config` | `LLM_BASE_URL=http://127.0.0.1:8080/v1`、`HUB_PORT=8080` |
| 悬空引用 | 全仓检索 `LLAMA_SERVER_PORT` | **零命中** |

---

## 5. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| LVA quit 后 Hub/children 存活（GUI 实证） | 未验证 | 需真实 Hub + GUI 环境 |
| 真实 Hub switch | 未验证 | 本机未运行 Hub |
| 前端在新默认（8080）下的端到端推理 | 未验证 | 需真实 Hub |
| 端到端 attestation 真实送达（R16/R17 遗留） | 未验证 | 需 GUI 驱动 Tauri |
| Tauri release、soak、CI 实跑、多显示器 | 未运行 / N/A | 沿用既有状态 |

---

## 6. 差异报告（只报告，未自行修正）

1. **5 个命令是死代码**：全仓检索确认 `unload_vram`/`cold_start_llm`/`scan_models`/`refresh_models`/`switch_llm_model` **无任何前端或 Rust 调用方**（仅 RED 断言文本提及）。计划 L1284 允许「删除确认无用函数」，因此是删除而非保留兼容包装。
2. **`config.py` 的 `LLAMA_SERVER_PORT` 被重命名为 `HUB_PORT`**：它是 L60 的 1234 来源，而 `llm.py` 引用 `LLM_BASE_URL`（L57/L109）。改名后全仓无悬空引用。**若有外部脚本按名引用 `LLAMA_SERVER_PORT`，会失效**——我未在仓库内找到此类引用。
3. **`make_bench_reports.py` 的改动是文档性质**：它生成的报告文本此前声称由 LM Studio + `scripts/llm_serve.py` 提供（后者已列在 PR-015 的删除清单里）。改为 Hub 表述。**历史生成的报告文件未改动**（遵守「不重写历史」）。
4. **本轮未改 `services.default.json`**：实测它**不含** direct llama 条目（只有 `lva_core` 与 `screenpipe`），无需改动。计划 L1284 列出它，但实际已合规。
5. **`tray.rs` 未改**：3 处 `llama` 命中是服务状态显示文本，非 lifecycle 命令。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 .venv / venv / benchmarks/；**未执行 git 写操作**（本轮成果尚未提交，待指示）。E 盘写入经 apply_patch。**本轮零契约改动、零新增依赖、未提权。**

## 8. 下一片

`tests/red_v121` **已清零**，因此**不再有 RED 驱动的切片**。剩余工作转为：

| 项 | 性质 |
|---|---|
| PR-020/021（C 链 privacy/capture） | 依赖已满足，可继续并行 |
| PR-016/017/018/019（Journal/legacy memory/screenpipe/temporal） | Wave 2 剩余 |
| 端到端 attestation 真实送达 | R16/R17 遗留，需 GUI |
| 真实 Hub 相关验收（PR-012/013/014/015 的运行时条目） | 需真实 Hub |
| PR-023/030/031（capability 骨架 + 窗口能力） | 承接 S-UI-01 的 R11 |
| L463 全合规、_enc 密钥轮换、README 是否纳入 | 待用户决定 |

**注**：RED 清零**不等于** G 门通过。G0 已 PASS；G1 缺 PR-003/004 的正式收口（两者已实现，但 G1 评估未做）；G2–G8 仍远。**清零是「RED 先行队列已清空」，不是「项目完成」。**


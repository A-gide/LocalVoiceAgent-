# R04 执行报告 — Wave 0a / 0b 与正式 G0

- 日期：2026-09-23（Asia/Shanghai）
- 执行者：DeepSeek（本会话），按 `LocalVoiceAgent-R04-DeepSeek-Handoff-2026-09-23.md` 的 D1→D2→D3 连续执行
- 仓库：E:\AI\LocalVoiceAgent
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 工作树：`status --porcelain=v1` = **79 行**（交接文档记 233 项为 `-uall` 口径，两者口径不同，非冲突）
- 基线文件 SHA256 复核：见 §1

---

## 1. 已修改（本轮落盘）

| 文件 | 改动 | 性质 |
|---|---|---|
| apps/desktop-shell/src-tauri/src/supervisor.rs | 新增 `#[cfg(test)] mod tests`（5 测试）；**实现修复**：`stop_spawned` 增加 ownership 前置检查（`ownership.get(name) != Some(&Spawned)` → `Ok(false)`），与 process_manager.rs:222 已有写法对齐 | 修复 I04 真实缺陷 + 补真实进程单测 |
| apps/desktop-shell/src-tauri/src/process_manager.rs | 新增 `#[cfg(test)] mod tests`（5 测试）；哨兵进程由 `cmd.exe` 换为 `ping.exe -n 20` | 补真实进程单测 |
| src/lva/server.py | `/api/ask` 的 403 守卫前移到 `core()`/`get_journal()` 之前（`get_runtime()` 保留在守卫前以读取 `rt.mode`）；`/api/tts` **原本完全无守卫**，新增同款 403 守卫（`component="core.tts"`） | 修复 I07/I08 硬边界缺口（计划 L311/L318） |
| tests/invariants/test_invariants.py | `test_i07_i08_passive_forbids_llm_tts` 增加 `/api/tts` 403 断言 + `assert server_mod._core is None` | 补断言（未弱化任何既有断言） |
| S-UI-01-Tauri-Window-Capability-Report-2026-09-23.md | 新建（12,002 B，111 行） | D3 交付物 |
| G0-FORMAL-VERDICT-2026-09-23.md | 新建（5,921 B） | D3 交付物 |

未修改：三个生成制品（schemas/lva-ipc-v1.json、apps/desktop-ui/src/generated/lva-ipc.ts、apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs）、冻结计划、历史报告、capabilities/default.json、任何 RED 测试断言。

### 1.1 基线与末态

| 项 | 交接基线 | 本轮末态 |
|---|---|---|
| HEAD | cf1c96752ffb752de1581860968d5189cd6e2a2c | 同（未变） |
| status --porcelain=v1 | 79 行（-uall 口径 233 项） | 79 行（本轮改动全在未受追踪文件内） |
| tests/red_v121 | 33 failed / 108 passed | **33 failed / 108 passed（无回归）** |
| v1.2 分组 | contract 5 / unit 8 / fault 7 / migration 2 / ux 11 | 同，且 integration 11、invariants 23、harness 43 全绿 |

---

## 2. 本轮实测通过

| 项 | 命令要点 | 结果 |
|---|---|---|
| **CAS 47/47**（G0 关键判据） | `pytest tests/red_v121/test_red_contract_cas.py` | **47 passed in 0.82s** |
| PR-001 合同 5 项 | `pytest tests/contract` | 5 passed in 0.68s（schema_zero_drift / command+event round-trip / error_envelope_sanitization / codegen_zero_diff） |
| PR-002 clean-install | 隔离 fresh 环境 `uv sync --locked --extra dev --group lint --offline` | 36 包，EXIT=0 |
| PR-002 import | `fresh-venv/Scripts/python.exe -c "import lva"` | IMPORT_OK（Python 3.11.15） |
| PR-002 lock | `uv lock --check` | EXIT=0（36 包） |
| PR-002 lint | `ruff check src/lva tests/run_groups.py`（RUFF_CACHE_DIR 指向 X 盘） | All checks passed |
| fresh 环境全组 | 8 组 pytest（contract/unit/fault/migration/ux/harness/integration/invariants） | **98 passed, 1 warning in 111.10s** |
| PR-022 harness | `pytest tests/harness tests/red_v121/test_harness_selftest.py` | **43 passed in 71.57s** |
| 全组（v12 层 + harness） | `run_groups.py --layer v12 harness` | contract 5 / invariants 23 / unit 8 / fault 7 / integration 11 / migration 2 / ux 11 → **all groups passed**，EXIT=0 |
| v121 层 | `run_groups.py --layer v121` | harness 绿；red-v121 33 failed / 108 passed（设计 RED） |
| PR-005 Rust 单测 | `rusttest.ps1`（mt.exe 内嵌 Common-Controls 6.0 清单） | **12 passed / 0 failed ×2 次迭代，EXIT=0，stray_ping=0** |
| Rust 构建 | `cargo check --offline`（CARGO_TARGET_DIR=X 盘） | EXIT=0 |
| I07/I08 负向对照 | 临时将守卫改 `and False` | 测试失败并显示 `assert 200 == 403` → 证明 PASSIVE 下 TTS 真会被调度；恢复后 23 passed，无残留标记 |

### 2.1 PR-005 的关键实现发现

`supervisor.rs` 的 `stop_spawned` 原先只查 `children` map、**不查 ownership map** → 注册为 Adopted/External 却仍持有 handle 的进程会被误杀，违反 I04（"Adopted/External/Unknown 永不 auto-kill"）。已加 ownership 前置检查修复。

哨兵进程选型经实测确定：`cmd.exe` 在 stdin 管道 EOF 时会自行退出，使"丢弃 handle"看起来像被 kill，**不能**作为存活哨兵；`ping.exe -n 20 127.0.0.1`（约 19s）在 stdin 关闭时存活，仅显式 `kill()` 才终止 → 已换用。

测试卫生：`safe_shutdown_spawned_only` 会 `children.clear()`，adopted 哨兵 handle 因此不可回收 → 用有界 `ping -n 20` 令其自行退出，不泄漏进程（实测 stray_ping=0）。

### 2.2 cargo test 阻断的解决（上一轮卡点）

根因：测试二进制无 `.rsrc` 段 → 无内嵌清单 → 加载 comctl32 v5.82 → 无 `TaskDialogIndirect` 导出 → `STATUS_ENTRYPOINT_NOT_FOUND` (0xC0000139)。

解法：用 `mt.exe`（Windows Kits 10.0.22621.0\x64）为测试二进制内嵌 Common-Controls 6.0 清单。关键陷阱：`-outputresource:<exe>;#1` 的 `;#1` 必须放进变量（内联会被 PowerShell 吞成字面量 → `c1010007`）；`mt.exe` 需可写 TMP/TEMP；用 `Start-Process -RedirectStandardOutput` 抓输出；脚本末尾不能 `exit`（会杀掉外层 shell）。可复用脚本：`<scratch>/rusttest.ps1`。

**范围限定**：该清单问题只影响测试 harness。产品二进制 `apps/desktop-shell/src-tauri/target/debug/lva-pet.exe`（2026-09-18 20:32，269,856,718 B）**有** `.rsrc` 段、正常导入 `TaskDialogIndirect`，无此问题。

---

## 3. 本轮实测失败

| 项 | 结果 | 根因 | 归属 |
|---|---|---|---|
| click-through toggle | 静默失效 | capabilities/default.json 仅 `core:default` + `windows:["main"]`；core:window:default 实测**只含 28 项只读权限**，不含 allow-set-ignore-cursor-events / allow-start-dragging / allow-set-position / allow-set-always-on-top；前端 catch 只 `console.warn` | PR-023 / PR-030/031 |
| drag / reset position | 静默失效 | 同上（allow-start-dragging、allow-set-position 未授予） | PR-030/031 |
| crash/restart geometry restore | 未实现 | settings.rs 无 geometry/position/monitor/dpi 字段；全仓无 set_position / outer_position / current_monitor / available_monitors / clamp；窗口重建固定 inner_size(360,520) | PR-030/031 |
| WebView2 reload | 未实现 | Tauri 2.11.5 Rust 侧有 `WebviewWindow::reload()`，但 @tauri-apps/api 2.11.1 JS 侧**不导出 reload**（全量 .d.ts 检索零命中）；前端亦未使用 | PR-030/031 |
| 事件重连 | 未实现 | tauri-bridge.ts:274-284 只有 listen + unlisten，无重连/退避/断线检测 | PR-030/031 |
| tests/red_v121 | 33 failed / 108 passed | **设计 RED**（R05/R06/R09/R10/R12/R13/R14 的 gap 复现），与记录基线完全一致，非回归 | 后续切片 |

分布：test_red_auth.py 6、test_red_bootstrap.py 6、test_red_authority.py 5、test_red_output_mute.py 4、test_red_redaction.py 4、test_red_temporal_mention.py 4、test_red_capture.py 3、test_red_snapshot.py 1。

---

## 4. 未运行 / N/A（不回填 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| 前端 Vue/Pinia 端到端 | 未验证 | 只有结构断言；决策逻辑已抽为 `modeTransition.js`（Node 真实执行，6 项） |
| GUI 交互类 spike 项（透明/置顶实际表现、托盘菜单实际弹出、click-through 实际生效） | 未验证 | 本会话无 GUI 自动化能力（不能截图或驱动窗口） |
| 多显示器 DPI/scale | **N/A** | 本机仅 1 台显示器（\\.\DISPLAY5 1707x1067，workarea 1707x1019） |
| soak `--duration 7200` 真长跑 | 未运行 | 未跑 |
| Tauri release 构建 | 未运行 | 仅 `cargo check`（EXIT=0）与 debug 测试二进制 |
| 前端 `npm run build` | 未运行 | 仅 `vue-tsc --noEmit` |
| 三个 workflow（ci.yml / v121-gates.yml / wasapi-device.yml） | 未运行 | 未受追踪，无 GitHub Actions 实跑 → 只能报"本地通过" |
| 真实麦克风/扬声器声学验收 | 未运行 | 无硬件实证 |
| PR-005 的 GUI quit 实证 | 未验证 | 已用真实进程 Rust 单测覆盖 I04/I16，但非 GUI quit 交互实证 |

---

## 5. 正式 G0 判定

**G0 PASS（10/10 判据满足）**，完整裁决见 `G0-FORMAL-VERDICT-2026-09-23.md`。

| 判据 | 结果 |
|---|---|
| PR-001（合同冻结 + codegen + ADR） | PASS |
| PR-002（clean .venv 可安装） | PASS |
| PR-022（quality harness） | PASS |
| S-UI-01 report 完整 | PASS |
| schema round-trip | PASS |
| aggregate-revision CAS tests | **PASS（47/47）** |
| drift | PASS |
| clean .venv | PASS |
| ADR supersedes 链 | PASS |
| Tauri capability report | PASS（报告完整，含真实缺陷） |

边界说明：G0 判据 #10 要求的是**报告完整**，不是窗口能力全部可用。S-UI-01 的实质结论是"部分验证 + 3 项缺口 + 1 项阻断级发现"，这些按计划归属 PR-023/030/031，不构成 G0 阻断。旧 v1.2 的 `verify_release_gates.py`（v1.2 判据，从不运行 tests/red_v121）**未**用于本裁决。

---

## 6. 阻断项与下一切片

阻断项（不阻断 G0，阻断 Wave 1 的 UI 工作）：
1. **R11** — capability 未授予窗口写权限；且 `windows:["main"]` 意味着 settings/chat/memory/services 窗口无任何 capability 覆盖。须在 PR-023 建 capability 骨架时一并修复。
2. geometry restore 与 clamp 完全缺失，降级策略（非透明/非穿透小窗 + clamp + Reset Position）**目前不可直接执行**。
3. WebView2 reload 需由 Rust command 暴露（JS API 无 reload）。

下一切片：按计划 L1854，Wave 0a/0b 已过 G0 → 进入 **Wave 1**（PR-003..008 安全 IPC / Supervisor 等）。注意 `tests/red_v121` 的 33 项设计 RED 是 Wave 1+ 的工作内容，其中 `test_red_authority.py` 的 I22（`/api/ask` 须走 `execute_command`）等属 R09 范围，本轮**未**改 dispatch 架构。

---

## 7. 环境与工具

- OS Windows 11 build 26200.7462（25H2）；WebView2 153.0.4234.48；rustc 1.98.1（host x86_64-pc-windows-gnu）；Tauri 2.11.5 / @tauri-apps/api 2.11.1
- Python 解释器：`E:\AI\LocalVoiceAgent\.venv\Scripts\python.exe`（3.11.15）
- uv：`C:\Users\a.gide\.local\bin\uv.exe`（需 `UV_CACHE_DIR` 指向 X 盘；ruff 归档在 `<scratch>/uv-cache3`）
- Rust 测试需 `CARGO_TARGET_DIR` 指向 X 盘 + `--offline` + PATH 前置 `tools\w64devkit\bin`
- scratch：`X:\Codex\State\visualizations\2026\09\23\01a0cd49-18d6-79c1-afd6-41261b729efe\scratch\`（rusttest.ps1、acl_check.py、各 bt-*/artifacts-*/fresh-venv/uv-cache3）

## 8. 硬约束遵守情况

未弱化/跳过/xfail 任何 RED 测试；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划或历史报告；未删除 .venv / venv / benchmarks；未执行任何 git 写操作；未删除 `scripts/soak_report.json`；需要真实进程的 PR-005 项用真实 `ping.exe` 进程验证而非 mock；未宣称"全量 lint 通过"（仅 Ruff E4/E7/E9 覆盖 src/lva 与 tests/run_groups.py）。




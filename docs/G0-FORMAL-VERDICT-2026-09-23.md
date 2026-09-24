# 正式 G0 裁决 — Contract / Build（v1.2.1）

- 日期：2026-09-23（Asia/Shanghai）
- 判据来源：冻结计划 `ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md` L1679
- 原始判据原文：`| G0 Contract/Build | PR-001/002/022 + S-UI-01 report | schema round-trip + aggregate-revision CAS tests + drift 绿；clean .venv 可安装；ADR supersedes 与 Tauri capability report 完整 |`
- 仓库：E:\AI\LocalVoiceAgent；HEAD `cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送）

## 裁决表

| # | G0 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | PR-001 完成（合同冻结 + codegen + ADR-009..012） | PASS | tests/contract 5 passed：test_schema_zero_drift、test_command_discriminated_unions_round_trip、test_event_discriminated_unions_round_trip、test_error_envelope_sanitization、test_codegen_zero_diff |
| 2 | PR-002 完成（root Python project，clean .venv 可安装） | PASS | fresh 环境 uv sync --locked --offline EXIT=0（36 包）；import lva OK；fresh 解释器跑 8 组 98 passed；uv lock --check EXIT=0；ruff check src/lva tests/run_groups.py → All checks passed |
| 3 | PR-022 完成（quality harness） | PASS | harness 组 43 passed（tests/harness + test_harness_selftest.py）；含 clock/recorder/provider fakes、late turn/fault 复现、I21/I22 违规正反例、heartbeat-vs-CAS 非冲突、redacted artifact 脱敏断言、WASAPI scaffold |
| 4 | S-UI-01 report 完整 | PASS（报告交付） | `S-UI-01-Tauri-Window-Capability-Report-2026-09-23.md`（12,002 B，111 行）：7 项逐项状态 + 环境版本 + R11 + 降级策略符合性 + 证据索引 |
| 5 | schema round-trip 绿 | PASS | test_command_discriminated_unions_round_trip、test_event_discriminated_unions_round_trip、test_committed_json_schema_matches_a_fresh_generation、test_committed_generated_ts_and_rust_match_a_fresh_generation |
| 6 | aggregate-revision CAS tests 绿 | PASS | tests/red_v121/test_red_contract_cas.py **47 passed / 0 failed**（本会话实测，0.82s）。含 CAS-required 拒绝缺 precondition、错误 aggregate、STALE_REVISION 拒绝且状态不变、heartbeat 不 bump runtime_control_revision、memory object revision、settings 命令由边界而非 Core 强制 |
| 7 | drift 绿 | PASS | test_schema_zero_drift、test_codegen_zero_diff、test_committed_json_schema_matches_a_fresh_generation、test_committed_generated_ts_and_rust_match_a_fresh_generation（三个生成制品与新鲜生成零差异） |
| 8 | clean .venv 可安装 | PASS | 见 #2（隔离 fresh 环境，未触碰现有 .venv） |
| 9 | ADR supersedes 链完整 | PASS | docs/architecture-decisions.md：ADR-001 → Superseded by ADR-010（L11）；ADR-006 → Superseded by ADR-011（L93）；ADR-007 的 LM Studio 假设 → ADR-009（L111/L127）；ADR-010/011 状态均为 Accepted (Supersedes ...)；ADR-009/012 存在 |
| 10 | Tauri capability report 完整 | PASS（报告交付，含真实缺陷） | 同 #4。报告如实记录 3 项真实缺口（geometry restore、WebView2 reload、事件重连）与 1 项阻断级发现 R11（capability 未授予窗口写权限） |

## 结论

**G0 PASS**（10/10 判据满足）。解锁 Wave 1。

判定边界说明（避免误读）：

1. G0 的 "Tauri capability report 完整" 要求的是**报告完整**，不是窗口能力全部可用。S-UI-01 报告的实质结论是"部分验证 + 3 项缺口 + 1 项阻断级发现"，这些缺口按计划归属 PR-023/030/031，是 G0 之后的修复项，不构成 G0 阻断。
2. 旧 v1.2 的 `scripts/verify_release_gates.py`（G0–G8）绿色**未**用于本裁决。该脚本是 v1.2 判据，只跑 tests/contract、tests/unit、tests/fault、tests/ux 等 v1.2 套件，**从不运行 tests/red_v121**，其绿不能替代本表。
3. `tests/red_v121` 当前 **33 failed / 108 passed** 属**设计 RED**（R05/R06/R09/R10/R12/R13/R14 的 gap 复现），不是 R03b 未完成。R03b 交付范围（test_red_contract_cas.py 47/47 + 阻断回归）已全绿。
4. 未验证项（前端 Vue/Pinia 端到端、soak 长跑、Tauri release 构建、npm run build、三个 workflow 的 CI 实跑、多显示器 DPI、GUI 交互类）**未**回填 PASS，均在报告中标 未验证/N/A。

## 本裁决的证据命令

```powershell
# CAS（G0 判据 #6）
cd E:\AI\LocalVoiceAgent
$env:PYTHONDONTWRITEBYTECODE='1'; $env:PYTHONPATH='E:\AI\LocalVoiceAgent\src'
$env:LVA_TEST_ARTIFACT_DIR='<scratch>/artifacts-cas'
& '.venv\Scripts\python.exe' -B -m pytest tests/red_v121/test_red_contract_cas.py -q --no-header -p no:cacheprovider --basetemp='<scratch>/bt-cas'
# → 47 passed in 0.82s

# PR-001 / drift（判据 #1/#5/#7）
& '.venv\Scripts\python.exe' -B -m pytest tests/contract -q --no-header -p no:cacheprovider --basetemp='<scratch>/bt-contract-r4'
# → 5 passed in 0.68s

# PR-002（判据 #2/#8）
$env:UV_CACHE_DIR='<scratch>/uv-cache3'; $env:UV_PROJECT_ENVIRONMENT='<scratch>/fresh-venv'
& 'C:\Users\a.gide\.local\bin\uv.exe' sync --locked --extra dev --group lint --offline   # → 36 包，EXIT=0
& 'C:\Users\a.gide\.local\bin\uv.exe' lock --check                                       # → EXIT=0
& '<scratch>/fresh-venv/Scripts/python.exe' -B -c "import lva"                               # → OK
$env:RUFF_CACHE_DIR='<scratch>/ruff-cache-r4'
& '<scratch>/fresh-venv/Scripts/ruff.exe' check src/lva tests/run_groups.py                  # → All checks passed

# PR-022（判据 #3）
& '.venv\Scripts\python.exe' -B -m pytest tests/harness tests/red_v121/test_harness_selftest.py -q ...   # → 43 passed

# 全组回归
& '.venv\Scripts\python.exe' -B tests\run_groups.py --layer v12 harness   # → all groups passed
& '.venv\Scripts\python.exe' -B tests\run_groups.py --layer v121          # → red-v121 33 failed / 108 passed（设计 RED）
```

`<scratch>` = `X:\Codex\State\visualizations\2026\09\23\01a0cd49-18d6-79c1-afd6-41261b729efe\scratch`




# 独立审查报告 — R04–R08 实现情况（对照 Composite + Frozen 计划 + R08 handoff）

- 日期：2026-09-24（Asia/Shanghai）
- 作者：独立审查会话（Codex）
- 性质：**只读审查**。审查过程未向仓库写入任何文件
- 审查对象：R04–R08 的执行报告与 handoff 声明
- 判据来源：`ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md`（1,858 行，108,041 B，`E198B7BF…`）+ `ARCHITECTURE-PLAN-2026-09-v1.2-COMPOSITE.md` + `CONTEXT-HANDOFF-LVA-R08-2026-09-24.md`

> **修订说明**：本报告于 2026-09-24 经两轮修订后落盘。原稿含两条**已撤回**的结论，见 §7。V1–V11 编号保留原样（下游 R10 交接引用需要）。

---

## 1. 审查方法

只读方式独立完成：基线哈希核对 → 复跑全部 Python 门禁（`PYTEST_ADDOPTS=--basetemp=W:/Cline/.audit-basetemp/bt`，正斜杠）→ 逐条回到源码核实 handoff 声明的已完成项与已知漏洞 → 对照 Composite 计划（PR-001~038、Part 12 Merge Train）与 Frozen 计划（PR-008 L1208-1216、Gates L1674-1687）判定差距。

---

## 2. 基线核对：handoff 声明全部属实

| 项 | handoff 声明 | 实测 |
|---|---|---|
| HEAD | `cf1c967…` | ✓ 一致，无 commit |
| porcelain v1 / -uall | 85 / 243（M20/D21/??202） | ✓ 逐项一致（只取 stdout） |
| 冻结计划 | 108,041 B / `E198B7BF…` | ✓ 一致；仓内 `docs\ARCHITECTURE-PLAN-2026-09-v1.2.1.md` 副本哈希也一致 |
| 三制品字节 SHA256 | EC6F…/C836…/D307… | ✓ 逐字节一致，mtime 均为 09-23 11:24 |
| `codegen --verify` | 三制品 verified | ✓ EXIT=0 |
| red_v121 | 5 failed / 136 passed | ✓ 一致，5 项红确为 `test_red_authority.py` 同 5 项 |
| v12 层 7 组 | all groups passed | ✓ 复跑全绿（设 basetemp 后） |
| harness | 43 passed | ✓ 43 passed in 52.96s |
| docs 5 份报告 SHA256 | DEFF…/C3AB…/B70F…/B499…/8A98… | ✓ 全部一致；**确无 R06 报告** |

---

## 3. 确认的漏洞与缺口（按计划条款定级）

### 高（阻断 Gate 推进）

- **V1 — PR-008 验收面未实现（R08 不得宣告完成）**：Frozen L1213 要求的 Windows IPv4/IPv6 listener table、control-port↔Hub process 关联、typed bind attestation、crash reason、redacted diagnostic snapshot 均无实现；`network_attestation.rs` 不存在；`service_registry.rs` 为无读写者的 stub。G1（L1680：PR-003..008）不闭合。
  > **后续**：该缺口已由 R08 交付闭合（新增 `network_attestation.rs` 10 项单测 + `service_registry.rs` 扩为真实实现 + `get_service_identity_status` 命令）。见 `docs/R08-EXECUTION-REPORT-2026-09-24.md`。
- **V2 — `runtime_instance_id` 双源，属实**：`bootstrap.py` L56 生成并经 `__main__.py` L90 进 `LVA_READY`；`server.py` `get_runtime()` 构造 `RuntimeController` **不传**该 id，`runtime.py` L46 `runtime_instance_id or uuid4()` 再生成。这正是 PR-008「runtime instance tracking」步骤，与 V1 同切片。
  > **后续**：已由 R08 修复（`announce_runtime_instance_id` / `get_announced_runtime_instance_id` 单源，实测 `IDENTICAL=True`）。
- **V3 — 生产代码无 `emit_event` 调用方，属实**：仅 `runtime.py` L128 定义，`src/lva` 无调用。后果：bridge 的 gap/instance-change 检测在真机**永不触发**，R07 的 event gap 验收只能停在 stub 级。
- **V4 — R09/R10 未开始，5 项 RED 复现**：`config.py` L47/L60 仍默认 `127.0.0.1:1234`（违反硬约束 2）；`/api/ask`（`server.py` L233）仍旁路 dispatcher（违反 I22）；Rust 侧直接 model lifecycle 命令与 hub saga 接线缺失（I21）。
- **V5 — Tauri capability 缺口（S-UI-01 的 R11，非切片 R11），属实**：`capabilities/default.json` 仅 `core:default` + `windows:["main"]`；窗口写权限未授予，settings/chat/memory/services 四窗口无 capability 覆盖。§8.3 降级策略当前不可执行。

### 中

- **V6 — `scripts/start-all.ps1` 绕过 bootstrap，属实**：L95 仍以 `-m lva`（无 `serve --bootstrap`）启动并写死 8765 端口。任何人用该脚本启动即得到一个固定端口、无 token 的服务，直接违反硬约束 5 与 PR-006。
  > **后续升级（R10 期间）**：范围扩为 **两个脚本**。`stop-all.ps1` 按 PID 树 `Stop-Process -Force`，其「llama.cpp-hub runtime preserved per I04/I16」只是注释意图，机制不保证结果；`start-all.ps1` 头部注释另含 1234 残留。两者均已由 R10 处置。
- **V7 — `require_auth=False` 旁路分支仍在** `auth.py`（L29/37/40/90）；产品代码确无调用点，但与 Frozen L1196「旧 unauthenticated path 不保留」存在解释空间——待裁决项。
- **V8 — `lva ask` 无合法认证通道**（R05 遗留 2），待裁决。
- **V9 — dist 陈旧，属实**：`dist/assets/index-Csvm8PD1.js`（144,927 B，09-23 12:52）不含 `setMuted`，而源码 `stores/runtime.ts` L101/106 已有。

### 低 / 卫生

- **V10** 三个残留运行产物（`temp_soak_journal.sqlite3` 94,208 B、`soak_report.json`、`soak_smoke_report.json`）属实，应清理。
- **V11** R06 无执行报告（缺口属实）；B22 RED docstring 过期、B23 夹具 6 处 `"active"`、B25 authority RED 为结构断言——均为知悉项。

### V12（R10 期间新增发现）

- **V12 — `on_interrupt_action` 从未被注入**：`InterruptController.__init__`（`interrupt.py` L19）接受该回调，docstring 明写用途是「player.flush, queue purge」，但 `runtime.py` 构造它时只传 `turn_controller` 与 `floor_controller`，**回调从未注入** → `commit_interrupt()` 末尾恒为假。后果一：`turn.cancel` 不能停声音；后果二（更严重）：**进入 Standby / Privacy Pause 时已在播放的音频不会被停**，直接触及硬约束 7。由审查双方交叉核对时发现，已由 R10 修复（`reason` 透传 + 按强度分流 abort）。

### R1 风险成立

全部成果在未提交工作树，是全局最高风险。

---

## 4. 复核为「已完成且真实」的项

- R05 修复：`server.py` L141 默认构造 `TokenValidator()`；`/ws` 处理器 Bearer 头取 token + Origin 检查 + `close(4403)` ✓；`/api/tts` 403 守卫在 `core()` 之前 ✓。
- R07：`bridge.rs` 常量与 handoff 逐字一致（L35-40）✓。
- R04/D22：`pyproject.toml` 显式 pin `sherpa-onnx-core==1.13.8`（L22）+ `pypinyin` + `python-multipart`；uv.lock 36 包；`.venv` 已装 1.13.8 ✓。
- CAS 面：`runtime.py` 54 处、`runtime.ts` 6 处 revision/`STALE_REVISION` 相关行，契约消费已迁移 ✓。

---

## 5. 未复验的声明（诚实边界）

Rust 单测 29×3（后为 49×1）、互操作探针 10 项、前端 typecheck/build、soak、GUI/多显示器、真实声学——本轮未重跑（授权/环境限制），仅核对了对应源码与产物存在性，未发现与其报告矛盾的证据。

---

## 6. 结论与建议

实现总体进度与 handoff 自述一致：**R00–R07 可信完成，G0 PASS 裁决有依据**；真正的剩余工作是 **R08 的 PR-008 面（V1+V2+V3 应合并处理）、R09/R10（V4）、capability 缺口（V5）**。

**对审查方建议的更正（R10 期间）**：原稿称「R09/R10 完成后 red_v121 清零、G1 可收口」，该判断**不成立**——(1) `test_red_authority.py` 的 6 项中有 3 项绑定 Wave 4/5 的 PR-014/015，R09/R10 无法使其转绿；(2) G1 判据（L1680）是 `PR-003..008`，I21/I22 属 **G2**（L1681）。G1 缺的是 PR-003/PR-004。

---

## 7. 撤回声明（两条）

### 撤回 1 —— 「FROZEN 实为 1,352 行」**错误**

原稿称 handoff 的「1,858 行」为口径错误。**该结论撤回。**

根因已定位并复现：该文件**无 BOM**，Windows PowerShell 5.1 的 `Get-Content` 默认按系统 ANSI（本机 GBK）解码，GBK 双字节序列吞掉部分 `0x0A`，把 1,858 行错并为 1,352 行。实测对照：

| 测量 | 结果 |
|---|---|
| pwsh 7.6.5 默认 | 1858 |
| pwsh 7.6.5 `-Encoding UTF8` | 1858 |
| **Windows PowerShell 5.1 默认** | **1352** |
| Windows PowerShell 5.1 `-Encoding UTF8` | **1858** |
| 原始字节 LF 计数 / `ReadAllLines()` | 1858 / 1858 |

**1,858 行是物理事实**，handoff 的全部行号引用（L1234/L1680/L1854 等）成立。

**教训**：对该仓库任何文本的行数测量必须显式 `-Encoding UTF8`。作用域边界：`scripts/*.ps1` 的中文字符数实测均为 **0**（4 个脚本逐一核对），它们 `Get-Content` 只读 ASCII 的 PID/JSON 文件，因此该陷阱在仓库脚本面**不活跃**。

### 撤回 2 —— 「`/api/ask` 可立即开工」**需附条件**

原稿背书了「`/api/ask` → `turn.send_text` 零契约改动、可立即开工」。前半句成立（确实不需要动契约），**但「立即开工」不成立**：实测 `turn.send_text` 的 dispatcher 实现（`runtime.py` L395-422）只做模式守卫 → `start_session()` → `create_turn()`，**无 LLM/TTS/journal 调用**；而 `RuntimeController` 无编排引用。若直接改 route 只发该命令，`/api/ask` 将**创建 turn 而不回答**——形式绿、实质退化。因此必须先裁决 (甲) 形式转绿还是 (乙) 编排内迁，已由用户裁决为 **(甲)**，并已在 R10 实施。

---

## 8. 落盘说明

本文件由审查方授权后经执行方 `apply_patch` 写入 `E:\AI\LocalVoiceAgent\docs\`。审查方原稿位于审查会话内；落盘版本已并入上述两条撤回与 V12 追加，其余条目按原样保留（含 V 编号）。

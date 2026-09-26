# R42 修复报告（合并）— 2026-09-26

- 执行者：Codex（经用户逐次授权实施与提交）
- 基线：`f758eaf4` → 当前 `b678da9`（`main` = `origin/main`，工作树干净）
- 依据：`LVA-Post-Freeze-Audit-20260926/AUDIT-REPORT.md` 的修复队列 + R40/R41 执行报告
- 性质：**合并报告**。不自行宣布总体 GREEN；实机/硬件门禁按事实保持关闭

> 本文件汇总 R40（T01–T08）与 R41（FIX-002/004/005/006/007）两次已提交的修复，供审阅者一处查阅。
> 逐包的原始证据仍在各自的 R40/R41 报告内，历史记录未改写。

---

## 1. 提交序列

| 提交 | 内容 |
|---|---|
| `9474b0c` | feat(T01–T08): close the R40 slices |
| `b9da23b` | fix(T01–T04): 三处复核缺陷（启动开麦 / 自动放弃 / 失败报成功） |
| `1bfcd2d` | fix(T01): 补扫续传不被水位推进覆盖 |
| `f31b712` | docs(R40): §11 探针笔误勘误 |
| `b678da9` | fix(FIX-002/004/005/006/007): 审计修复队列 |

全部已推送到 `origin/main`（触发远端 CI）。

---

## 2. 修复清单（问题 → 修复 → 证据）

### 2.1 启动不再隐式开麦（审计 F-001 / I19）

| 项 | 内容 |
|---|---|
| 问题 | `lifespan` 调 `c.start()`（默认 `open_devices=True`）→ `mic.start()`，启动即采集 |
| 修复 | `VoiceCore.ensure_devices()` 抽出设备创建；`lifespan` 用 `c.start(open_devices=False)`；`on_start_mic` 首次进入采集模式才开设备 |
| 证据 | `test_red_r40_t02_startup_standby.py`（真实 `VoiceCore`）：启动后 mic 未开且 `v.mic is None`；进入采集必须真开且幂等 |

### 2.2 迟到 ASR / 取消回复不再落 sink（审计 F-002 / I01·I05·I22）

| 项 | 内容 |
|---|---|
| 问题 A | `_handle_utterance` 只在阻塞 ASR **前**查模式，返回后无条件写 transcript/WAV/Memory |
| 修复 A | ASR 前快照 Core epoch，返回后过 `_utterance_effect_allowed()`；IDLE 或 epoch 移动即丢弃，gate 异常按拒绝 |
| 问题 B | `_run_turn` 取消/被取代后仍把 reply 写 history/旧 Memory |
| 修复 B | 回复按 turn 开始时的 epoch 门禁（`_effect_allowed()`） |
| 证据 | `test_red_r41_fix002_late_asr_sink.py`（3）、`test_red_r40_t03_cancelled_reply_sinks.py`（3），均含「正常输入不受影响」的反向断言 |

### 2.3 文本执行闭环 + typed 生命周期（审计 F-003）

| 项 | 内容 |
|---|---|
| 问题 | `turn.send_text` 只建 Turn 不执行；typed `turn.started/completed/cancelled` 声明却从不发射 |
| 修复 | 注入 `turn_runner` 真正执行；`turn_runner_suppressed` 让 `/api/ask` 独占；发射三个 typed 事件；失败返回 `rejected` 并收尾 Turn |
| 证据 | `test_red_r40_t04_turn_send_text_executes.py`（5） |

### 2.4 Player 身份由 Core 唯一生成（审计 F-004）

| 项 | 内容 |
|---|---|
| 问题 | 新 turn 推 `VoiceCore._generation`，Player 只在 flush 时推进，正常新 turn 音频被当旧包丢弃（有文字无声音） |
| 修复 | `Player/NullPlayer.set_generation()`；`_run_turn` 入队前发布 turn 身份；比较仍严格等值 |
| 证据 | `test_red_r41_fix004_player_generation.py`（2）：正常 turn 渲染非零且 `stale_dropped==0`；旧包仍被拒 |

### 2.5 推理跟随已提交绑定（审计 F-005）

| 项 | 内容 |
|---|---|
| 问题 | Core 提交 binding B，生产 `LLM.stream` body `model` 仍取配置默认 A |
| 修复 | `RuntimeController.bound_inference_model()`；`TurnExecutor` 与 live turn 传入该模型；无绑定返回 `None` 保持默认 |
| 证据 | `test_red_r41_fix005_bound_inference.py`（3） |

### 2.6 capture 请求/ack 生产闭环（审计 F-006，契约变更）

| 项 | 内容 |
|---|---|
| 问题 | Core 记录 capture operation，但无任何传输；`acknowledge_capture_operation` 无生产调用者 |
| 修复 | 新增出站事件 `capture.operation_requested` + 入站命令 `capture.ack`；`set_mode` 后发布最新 pending operation；dispatcher settle 并重算 privacy scope；同 kind 新请求取代未应答旧请求 |
| 契约 | `codegen.py` 重新 pin（`aad1911e…`），三个制品由 `python -m lva.contracts.codegen` 生成，未手改 |
| 证据 | `test_red_r41_fix006_capture_ack.py`（4）：发布 operation、肯定 ack → VERIFIED、报未停止 → 不 VERIFIED、未知 operation → 拒绝 |

### 2.7 bootstrap deadline 真正生效（审计 F-009）

| 项 | 内容 |
|---|---|
| 问题 | `core_supervisor.rs` 的 `read_line` 阻塞到换行/EOF，围绕它的 elapsed 检查从不触发 |
| 修复 | 读线程 + 主线程 `mpsc::recv_timeout`；超时/EOF/断连分别明确返回并 kill child |
| 证据 | **未运行**（见 §4） |

### 2.8 T01 导入水位（数据完整性）

| 项 | 内容 |
|---|---|
| 问题 | ①水位之下后到的记录不可达；②补扫达页数上限无续传；③补扫续传被水位推进清空；④坏记录永久阻塞 |
| 修复 | 有界重开扫描（窗口锚定、offset 持久化续传、未排空标记）；坏记录**仅记录并告警**，放弃纯手动；水位推进保留 `sweep` 字段 |
| 证据 | `test_red_r40_t01_reopen_and_quarantine.py`（8） |

### 2.9 T02 停止保护

| 项 | 内容 |
|---|---|
| 修复 | `stop-all.ps1` 身份校验已实现，仅补 PID 复用**执行式**测试（fixture 记 PID 4=System，实测 `refusing to stop (PID reuse, I04)`） |
| 证据 | `test_red_r40_t02_stopall_pid_reuse.py`（2） |

### 2.10 T05/T06 外部契约（可编码部分）

| 项 | 内容 |
|---|---|
| 修复 | `SourceCapabilities`（未观测即 unknown，绝不默认）+ `ScreenpipeReconciler`（**缺席不等于删除**；派生 ID 拒绝对账） |
| 证据 | `test_red_r40_t05_t06_source_contract.py`（6） |

---

## 3. 门禁（本轮实测）

```ini
定向 R40/R41 RED                                                     39 passed
九组门禁 tests/run_groups.py --all:
  contract 5 / invariants 23 / unit 47 / fault 7 / integration 11
  migration 2 / ux 11 / harness 43 / red-v121 441
  expected-red groups failing: []      all groups passed
pytest tests/{red_v121,unit,invariants,contract,integration,migration,ux,fault}
  547 passed
ruff check（本轮改动文件）                                          All checks passed
```

---

## 4. 未运行 / 未闭合（诚实记录）

| 项 | 状态 | 原因 |
|---|---|---|
| FIX-007 Rust 行为测试 | **未运行** | 本机 GNU toolchain 缺 `dlltool.exe`；MSVC 缺 `link.exe`，均在链接前失败，与改动无关。`rustfmt --check` 可解析该文件 |
| T05 实机 Screenpipe | **关闭** | `127.0.0.1:3030` connection refused（服务未运行） |
| T06 真实 Hub 身份锚点 | **关闭** | `127.0.0.1:8080` connection refused + 需所有者确认实例 |
| T08 硬件性能门禁 | **关闭** | 无设备/live 模型；仅记录可编码基线（导入 5000 条约 29.7k 条/秒，命令派发 p95 0.014ms） |
| EXP-001 / VERIFY-001 | **未做** | 需固定 Hub/Screenpipe 实例与资源独占 |
| 远端 CI 结论 | **未读取** | 本机 `gh` 未认证 |

---

## 5. 契约与权限边界

- 唯一契约变更：`capture.ack`（入站）+ `capture.operation_requested`（出站），属审计 F-006 的最小修复，经用户授权，程序化 pin 记录于 `codegen.py`。
- 未改动架构分权（Core/Tauri/Hub/Journal 边界不变）；审计 Part O 的 `Architecture Change Requests = NONE` 仍成立。
- 未解冻任何冻结计划约束；冻结文本仍自称 **Freeze Candidate**，故「计划行号」引用只是候选依据。
- 密钥、DPAPI 密文、完整账户 ID 未写入代码/日志/报告。

---

## 6. 结论

审计修复队列中，**FIX-001、FIX-002、FIX-003、FIX-004、FIX-005、FIX-006** 已在代码层完成并由走真实入口的 RED 覆盖；
**FIX-007** 代码完成但 Rust 行为门禁未运行；**T01/T02/T05(可编码)/T06(可编码)** 已实施。

**不宣布总体 GREEN**：T05/T06 实机、T08 硬件、FIX-007 Rust 测试均未运行。远端 CI 通过也不改变这一结论。

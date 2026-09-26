# R41 EXECUTION REPORT — 修复队列 FIX-002/004/005/006/007（2026-09-26）

- 执行者：Codex（经用户「实施修复队列」授权）
- 基线：`f31b712`（R40 已推送）+ 干净工作树
- 依据：`LVA-Post-Freeze-Audit-20260926/AUDIT-REPORT.md` Part D/E/M 的修复队列
- 性质：**执行报告**。不自行宣布总体 GREEN；实机门禁按事实保持关闭

> FIX-001 / FIX-003 已在 R40（T02 / T04）完成，本报告不重复。

---

## FIX-002 剩余腿 — 迟到 ASR 不再落 sink（P0）

### 缺口

`_handle_utterance` 只在**阻塞式 ASR 之前**检查模式；返回后无条件 emit transcript →
写 WAV → `memory.add`。Privacy Pause / Standby / 中断在 ASR 期间发生，转录照样落库。

### 修复

1. 在 ASR **之前**快照 Core effect epoch（`epoch_at_utterance`）；
2. ASR 返回后先过 `_utterance_effect_allowed(epoch)`：模式为 IDLE 或 epoch 已移动即丢弃，
   gate 抛异常按拒绝处理（fail closed）；
3. 与 `_run_turn` 的 reply 侧门禁同型，只是提前到 transcript/WAV/Memory 之前。

### RED

`tests/red_v121/test_red_r41_fix002_late_asr_sink.py`（3 项）：ASR 期间模式转 IDLE → 不落库、
不发 transcript 事件；ASR 期间 epoch 增加 → 不落库；**正常录音仍落库**（防过度修复）。

---

## FIX-004 — Player 身份由 Core 唯一生成（P1）

### 缺口

新 turn 推进 `VoiceCore._generation`，但 `Player._generation` 只在 `flush` 时移动。于是
正常新 turn 以 gen1 入队、Player 仍 gen0，callback 把它当旧包丢弃：文字生成成功但**没有声音**。

### 修复

1. `Player.set_generation()` / `NullPlayer.set_generation()` 接收 Core 身份；
2. `_run_turn` 在入队前把 turn 身份发布给 Player（`player.set_generation(gen_id)`）；
3. 比较仍是严格等值，真正过期的包照样被拒。

### RED

`tests/red_v121/test_red_r41_fix004_player_generation.py`（2 项）：正常新 turn 的样本**实际渲染非零**且
`stale_dropped==0`；身份前进后旧包**仍被拒**（不削弱 stale-drop）。

---

## FIX-005 — 推理跟随已提交绑定（P1）

### 缺口

Core 提交 binding B，但生产 `LLM.stream` 的 body `model` 仍取配置默认 A。用户选择失效。

### 修复

1. `RuntimeController.bound_inference_model()` 返回已提交绑定的模型（无绑定返回 `None`）；
2. `TurnExecutor` 与 `VoiceCore._run_turn` 的 `LLM.stream` 传入该模型；
3. 无绑定 → 不强制模型，非 Hub 路径保持默认（不破坏既有路径）。

### RED

`tests/red_v121/test_red_r41_fix005_bound_inference.py`（3 项）：runtime 暴露已提交模型 / 无绑定为 None；
live turn 用绑定模型流式；无绑定 turn 保持默认。

---

## FIX-006 — capture 请求/ack 生产闭环（P1，契约变更）

### 缺口

Core 把 managed-capture operation 记进自己的列表，**没有任何东西把它送到拥有录音器的进程**，
`acknowledge_capture_operation` 无生产调用者，Privacy Pause 永远无法被确认。

### 修复（含**契约变更**，经批准，hard constraint 5）

1. 契约新增：出站事件 `capture.operation_requested`（`operation_id`/`kind`）；
   入站命令 `capture.ack`（`operation_id`/`managed_stopped`/`external_detected`）；
2. `set_mode` 后 `_publish_capture_operation()` 把最新 pending operation 发到执行者；
3. dispatcher 新增 `capture.ack` 分支：settle 匹配 operation、重算 privacy scope；
   未知/已结算 operation → `INVALID_TRANSITION` 拒绝（不移动 scope）；
4. **同 kind 的新请求取代未应答旧请求**（`superseded`）：进入 Live 与 Privacy Pause 各产生一个 stop，
   旧实现里单个 ack 永远无法结算 scope；
5. `codegen.py` 重新 pin（`aad1911e…`），**用完整 codegen 链重新生成**三个制品（未手改）。

### RED

`tests/red_v121/test_red_r41_fix006_capture_ack.py`（4 项）：进入 Privacy Pause 必须发布 operation；
肯定 ack → scope 变 `VERIFIED_ALL_LVA_MANAGED_CAPTURE_OFF`；
执行者报「未停止」→ scope **不得**变 VERIFIED；未知 operation ack → 拒绝。

---

## FIX-007 — bootstrap deadline 真正生效（P1）

### 缺口

`core_supervisor.rs` 的 `read_line` 阻塞到换行/EOF，围绕它的 elapsed 检查**从不触发**：
子进程只写半行或不写就永久挂住 supervisor。

### 修复

读放在独立线程，主线程用 `mpsc::recv_timeout` 按剩余预算等待；超时 / EOF / 断连分别返回明确错误，
每种错误都 `child.kill()`。deadline 现在是真实的，不是装饰。

### 验证状态（诚实记录）

**Rust 未能编译/测试**：本机默认 toolchain 为 `stable-x86_64-pc-windows-gnu` 但缺 `dlltool.exe`；
`stable-x86_64-pc-windows-msvc` 缺 `link.exe`。`cargo build` 两种 toolchain 均在链接前的工具缺失阶段失败，
与本次改动无关。`rustfmt --check` 能解析该文件（证明显式语法有效）。**FIX-007 的 Rust 行为测试未运行，门禁保持关闭**。

---

## 门禁（本轮实测）

```ini
pytest tests/red_v121 tests/unit tests/invariants tests/contract tests/integration tests/migration tests/ux tests/fault
-> 546 passed, 1 failed
```

唯一失败是 `test_contracts.py::test_codegen_zero_diff`：它把**工作树制品**与 **HEAD 制品**比对，
因此必须在本提交落盘后才转绿（不是缺陷）。ruff 通过。

### 未运行

- Rust `cargo build` / `cargo test`（toolchain 缺 `dlltool`/`link.exe`）；
- 九组门禁的完整重跑（本轮跑的是等价的目录集合）；
- 真实 Hub / Screenpipe / 声卡 / GUI（服务未运行）；
- T08 硬件性能门禁。

---

## 契约变更说明（审计 hard constraint 5）

本轮的 IPC 契约变更（`capture.ack` + `capture.operation_requested`）不是重构，而是审计 F-006 的**最小修复**：
没有这条出站事件与入站 ack，capture 请求永远到不了执行者。变更经用户「实施修复队列」授权，
程序化在 `codegen.py` Re-pin 注释中记录；三个生成制品由 `python -m lva.contracts.codegen` 生成，未手改。

---

## 与审计队列的对照

| 包 | 状态 |
|---|---|
| FIX-001 | 已由 R40 T02 完成 |
| FIX-002 | **本轮完成剩余腿**（迟到 ASR sink gate） |
| FIX-003 | 已由 R40 T04 完成 |
| FIX-004 | **本轮完成** |
| FIX-005 | **本轮完成**（本地入口；真实 Hub 一致性待实机） |
| FIX-006 | **本轮完成**（契约 + 闭环；真实 executor 传输待实机） |
| FIX-007 | **代码完成**；Rust 测试因 toolchain 未运行 |
| EXP-001 | 未做（需固定 Hub/Screenpipe 实例） |
| VERIFY-001 | 未做 |

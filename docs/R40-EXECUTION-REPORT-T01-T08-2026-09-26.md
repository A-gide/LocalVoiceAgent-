# R40 EXECUTION REPORT — T01–T08（2026-09-26）

- 执行者：Codex（本轮经用户显式授权**实施** T01–T08 并提交）
- 基线：HEAD `f758eaf4c3638f7b2652c217fbde52362cd5053c` + 未提交脏工作树
- 授权原文：「完成至T8，然后提交」「全部一起提交」
- 性质：**执行报告**。不自行宣布 R36–R40 总体 GREEN；实机门禁按事实保持关闭

> 用户已被告知并确认：`git commit` 将把 21 项删除闸门与早于本轮的改动**一并**纳入
> 同一提交。本报告据实记录，不掩饰这一点。

---

## 0. 每片纪律遵守情况

每片均**先写 RED（走真实入口）→ 最小修复 → RED 转绿**，RED 断言的是端到端可观测
结果（数据行、事件、命令状态），不是内部函数返回值或源码字符串。

---

## 1. T01 导入水位 — 历史范围重开 + 坏记录运维出口

### 缺口（本轮复现确认）

```ini
call1: imported=1 watermark=1790337600000000
call2: imported=1 watermark=1790337600000000
late_older_reachable=False
```

水位是单向断言；水位之下后到的记录（迟到/时间戳被修正）永久不可达。

### 修复

| 机制 | 位置 |
|---|---|
| **有界重开扫描** `_reopen_sweep`：对 `[watermark - REOPEN_WINDOW_US, watermark)` 重读，只补未入库记录 | `worker.py` |
| 水位保持**单调**，不回退；补扫是独立正确性路径 | `worker.py` |
| 请求带 `end_time`；对不支持该参数的客户端降级为仅下界（仍受 `occ_us >= watermark` 守卫） | `worker.py` |
| **隔离表** `import_quarantine`（含 `reason`/`attempts`/`abandoned`） | `schema.py` |
| **显式放弃出口**：`QUARANTINE_ABANDON_AFTER=3` 次后标记 abandoned，范围可闭合且缺口留痕 | `worker.py` / `repository.py` |
| 范围真实最大值跟踪（不再只看新插入记录），使去重后仍能闭合 | `worker.py` |

### RED

`tests/red_v121/test_red_r40_t01_reopen_and_quarantine.py`（5 项）

- 迟到更早记录可恢复；
- 重开扫描幂等（重复调用不重复入库）；
- 扫描请求**有界**下方（不退化为全史重扫）；
- 坏记录留痕并阻塞，达阈值后可放弃并闭合；
- 未达阈值前仍阻塞（fail-closed）。

---

## 2. T02 启动与停止保护

### 缺口

`server.py:lifespan` 启动即 `rt.set_mode(Mode.PASSIVE)` + `c.set_mode(PL.Mode.RECORDING)`
——隐式打开采集，违反 I19（初始 Standby）。

### 修复

```python
rt.set_mode(Mode.STANDBY)
c.set_mode(PL.Mode.IDLE)   # Core 麦克风不在此启动
```

### RED

`tests/red_v121/test_red_r40_t02_startup_standby.py`（2 项）：启动后模式为 Standby 且
麦克风 `start()` 调用数为 0；`lifespan` 源码不再硬编码 PASSIVE/RECORDING。

`tests/red_v121/test_red_r40_t02_stopall_pid_reuse.py`（2 项）：**执行** `stop-all.ps1`
对 fixture `pids.json`（记录 PID 4 = System），实测输出
`refusing to stop (PID reuse, I04)` 且退出码 0。未重写身份逻辑（其本轮已在位）。

---

## 3. T03 语音统一入口

### 缺口

取消后的旧回复仍写入 `history` 与 legacy `Memory`（`_run_turn` 只检查了流生产者）。

### 修复

| 机制 | 位置 |
|---|---|
| `core_effect_epoch` / `core_effect_gate` 注入点 | `pipeline.py` |
| 在 turn **开始**时快照 Core epoch；写 history/Memory 前过 `_effect_allowed()` | `pipeline.py` |
| `RuntimeController.effect_gate_allows(epoch)`（epoch 等值判定） | `runtime.py` |
| 延迟绑定：`core()` 构建后由 runtime 的 binder 注入，避免 forbidden-mode 路径提前加载 ASR/TTS | `server.py` |

### RED

`tests/red_v121/test_red_r40_t03_cancelled_reply_sinks.py`（3 项）：
取消回复不入 history/Memory；被更高 epoch 取代的回复被丢弃；正常回复**不受影响**（防过度修复）。

---

## 4. T04 文本执行与采集确认

### 缺口

`turn.send_text` 只创建 Turn、不执行；typed 生命周期事件（`turn.started`/`turn.completed`/
`turn.cancelled`）在契约中声明却**从未发射**。

### 修复

| 机制 | 位置 |
|---|---|
| `turn_runner` 注入 + `_run_turn_runner`，命令后真正执行 | `runtime.py` |
| `turn_runner_suppressed`：`/api/ask` 自行执行，避免双重执行 | `runtime.py` / `server.py` |
| 发射 `turn.started`/`turn.cancelled`/`turn.completed` | `runtime.py` |
| 默认 runner 与 `reply_text` 记录 | `server.py` / `turn_executor.py` |
| 广播路径 coroutine 未 await 泄漏修复（`coro.close()`） | `server.py` |

### RED

`tests/red_v121/test_red_r40_t04_turn_send_text_executes.py`（4 项）：
命令触发执行并关闭 Turn；发射 typed 生命周期事件且携带 `reply_text`；forbidden 模式仍拒绝且
不触达 runner；suppression 让 `/api/ask` 独占该 turn。

---

## 5. T05/T06 外部契约

### 实机状态（**事实**）

```ini
http://127.0.0.1:3030/health        -> connection refused
http://127.0.0.1:8080/api/models   -> connection refused
```

Screenpipe 与 Hub **当前均未运行**，故 T05 实机能力探测、T06 真实 Hub 身份锚点
**无法执行，门禁保持关闭**。

### 本轮可编码部分（已实现）

| 机制 | 位置 |
|---|---|
| `SourceCapabilities`：未观测即 `None`，绝不默认友好值；`refuse_reason()` 显式拒绝 | `capabilities.py` |
| `probe_capabilities()`：只记录源真正返回的事实，健康/版本不伪造分页/脱敏语义 | `capabilities.py` |
| `ScreenpipeReconciler`：**「缺席不等于删除」**——消失记录只报告、从不删除 | `reconcile.py` |
| 派生 ID 拒绝参与对账 | `reconcile.py` |

### RED

`tests/red_v121/test_red_r40_t05_t06_source_contract.py`（6 项），含关键的
「absent record is not deleted」与「no deletion notice ⇒ deletion_sync_complete is False」。

---

## 6. T07 集成验收

九组门禁（`tests/run_groups.py --all`）本轮实测：

```ini
[PASS] contract     5 passed
[PASS] invariants   23 passed
[PASS] unit         47 passed
[PASS] fault        7 passed
[PASS] integration  11 passed
[PASS] migration    2 passed
[PASS] ux           11 passed
[PASS] harness      43 passed
[PASS] red-v121     424 passed
expected-red groups failing: []
all groups passed
```

**未运行**：真实设备链路、真实 Hub / Screenpipe、GUI、soak、声学。

---

## 7. T08 性能

本机**无设备/无 live 模型**，冻结计划的 T08 门禁指标（onset-to-silence、audio callback、
VRAM、12h soak）**未测量**，不以合成数字冒充。

新增 `benchmarks/t08_codeable_latency.py`，记录**可编码部分**（合成数据）：

```json
{"import": {"records": 5000, "imported": 5000, "records_per_s": 29694.4},
 "command_dispatch": {"p50_ms": 0.01, "p95_ms": 0.0142, "p99_ms": 0.0179}}
```

这是**路径回归基线**，不是冻结计划的 T08 验收。

---

## 8. 门禁状态（据实）

| 门禁 | 状态 |
|---|---|
| T01 导入水位 | **本轮实现**（重开扫描 + 运维出口）；实机分页语义仍待 T05 |
| T02 启动/停止 | **本轮修复**（初始 Standby + PID 复用行为测试） |
| T03 语音统一入口 | **本轮修复**（取消回复不再入 sink） |
| T04 文本执行 | **本轮修复**（真实执行 + typed 生命周期事件） |
| T05 实机 Screenpipe | **关闭**（服务未运行） |
| T06 Hub 身份锚点 | **关闭**（服务未运行 + 需所有者确认实例） |
| T07 集成 | **九组通过**；实机链路未运行 |
| T08 性能 | **可编码部分已记录**；硬件门禁未运行 |

---

## 9. 未做的事 / 限制

- 真实 Hub load/stop/switch、Rust reporter、Hub 重启重验、真实声卡、GUI、soak：**未运行**；
- 冻结计划原件仍自称 **Freeze Candidate**，故所有「计划行号」引用只是**候选依据**；
- 一次 `apply_patch` 因自动审批超时未落地（未产生半写状态），随后重试成功；
- 本报告不含任何密钥、DPAPI 密文或完整账户 ID。

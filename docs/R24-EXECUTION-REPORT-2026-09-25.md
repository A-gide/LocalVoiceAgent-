# R24 执行报告 — B5 冲突可见化 + `hub.refresh` 标签纠正

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：审查方复验结论中的两个非阻断观察 + B5 裁决建议

---

## 0. 本轮做两件小事（均按审查方建议，语义不变）

| # | 事项 | 性质 |
|---|---|---|
| 1 | **B5 冲突可见化** | 审查方建议：「保持『加载无需先停旧』，但把 `MODEL_CONFLICT_REQUIRES_CONFIRMATION` 从日志提升为可见信号」。**不改产品语义**，只消除「死错误码」 |
| 2 | **`hub.refresh` 标签纠正** | 审查方观察①：「经调度器返回 `delegated_to_saga`，但 `_run()` 对它无操作——标签略误导」 |

---

## 1. B5 修复：冲突可见化（语义不变）

### 1.1 问题

原实现（`hub_runtime.py` L124-129）：旧模型是 preexisting 且未授权停止时，**只 `log.warning` 后继续 Step 3 加载**。后果：

- `MODEL_CONFLICT_REQUIRES_CONFIRMATION` 是**死错误码**——调用方与 UI 都无法感知冲突；
- 用户不知道旧模型仍占用 VRAM。

### 1.2 一个我在实现时才发现的陷阱

**朴素的 `last_error = ...` 会被下一次 `_update_status` 抹掉。** `_update_status(status, last_error=None)` 每次都把 `binding.last_error` 赋成参数值（默认 `None`），而冲突分支之后紧接 `_update_status("loading")`。所以冲突必须存在**自己的字段**，否则写完立刻被清空。

`test_conflict_survives_the_subsequent_status_updates` 正是守护这一点——**这条 RED 在写实现前就抓出了该陷阱**。

### 1.3 实现

```python
# 新增字段（独立于 last_error，故不会被状态更新抹掉）
self.pending_conflict: str | None = None

# 冲突分支：记录 + 日志，然后照常继续加载
self.pending_conflict = (
    f"{ErrorCode.MODEL_CONFLICT_REQUIRES_CONFIRMATION.value}: "
    f"old model {old_model} was preexisting/unknown and was left "
    "running; stopping it requires explicit confirmation"
)

# 新增两个方法
def consume_conflict(self) -> str | None:   # 读取并清除（只报告一次）
def publish_conflict(self) -> None:         # 写到 binding.last_error，不消费
```

`publish_conflict()` 在 COMMIT 步**状态稳定之后**调用——因为 `_update_status` 会自己赋 `last_error`。

### 1.4 语义保持（审查方裁决）

**加载仍不阻断。** `test_conflict_does_not_block_the_load` 断言冲突分支**不含 `raise`**，并验证它继续走到 Step 3。理由（计划 5.5）：`confirm preexisting stop` 约束的是**停止**旧模型，不是**加载**新模型。

---

## 2. `hub.refresh` 标签纠正

### 2.1 问题（审查方观察①）

`hub.refresh` 走调度器分支，返回 `data.status = "delegated_to_saga"`，但 `_run()` 里**没有对应操作**——标签声称委托了一件不存在的事。

### 2.2 修复

`_schedule_hub_saga()` 现在显式识别 `hub.refresh` 并返回 `False`（无操作可委托），于是它落回原有的 `hub.refresh` 分支返回 `accepted`——**语义与修复前一致（仍是 accepted），但不再谎称委托**。

---

## 3. 已修改（本轮，逐文件）

| 文件 | 改动 |
|---|---|
| `src/lva/providers/hub_runtime.py` | 新增 `pending_conflict` 字段、`consume_conflict()`、`publish_conflict()`；冲突分支记录该字段（语义不变，仍继续加载）；COMMIT 步末尾调用 `publish_conflict()` |
| `src/lva/core/runtime.py` | `_schedule_hub_saga()` 显式识别 `hub.refresh` 并返回 `False`，不再谎称委托；移除 `_run()` 中已无意义的注释 |
| `tests/red_v121/test_red_conflict_visibility.py` | **新增 RED 套件**（4 项） |

---

## 4. 实测

| 项 | 结果 |
|---|---|
| 新 RED 套件 | 改前 **2 failed / 2 passed** → 改后 **4 passed** |
| `tests/red_v121` 全量 | **253 passed / 0 failed**（起始 249P；+4 全为本轮新增） |
| v12 层 7 组 | **all groups passed**（contract 5 / invariants 23 / **unit 43** / fault 7 / integration 11 / migration 2 / ux 11） |
| ruff | All checks passed |

### 4.1 一处需要说明的读数变化（不是回归）

本轮 v12 层显示 `unit 43 passed`，而我此前多轮记录的是 `unit 8 passed`。**核实结论：不是回归，是我此前的读数有误。**

- `tests/unit` 下实有 **7 个文件**（`test_commands` / `test_effects` / `test_journal_schema` / `test_legacy_migration` / `test_observability` / `test_screenpipe_importer` / `test_temporal_recall`），`--collect-only` 实测 **43 项**；
- `git status -- tests/unit` 为空、7 个文件**全部在 `3a7ce44` 提交内**——即它们是**用户既有的**测试，不是本轮或近几轮新增；
- 其中 4 个文件 mtime 为 `2026-09-24 21:29–21:30`，属**用户在本会话之外的写入**（我未触碰）；
- `run_groups.py` 的 `unit` 组定义是 `("tests/unit",)`——目录整体，**没有**收窄。

**所以 `unit` 一直是 43，我此前写的 `unit 8` 是错的。** 该错误在 R04 起的所有报告中反复出现（抄自早期记录），本轮更正。**这是我第二次发现自己的报告数字与磁盘不符**（前一次是 R19 的 `-uall` 计数），已记入 §6。

---

## 5. 未运行 / N/A

| 项 | 状态 | 原因 |
|---|---|---|
| Rust 单测 | 未重跑 | 本轮零 Rust 改动（沿用 R23 的 55 passed） |
| 真实 Hub 端到端 | 未重跑 | 本轮改动在 Python 侧、不触及 attestation 路径；R23 已复验 `READY` |
| Tauri release、soak、CI 实跑、GUI | 未运行 / N/A | 沿用既有状态 |

---

## 6. 差异报告（只报告，未自行修正）

1. **`unit 8` 是我长期抄错的数字**（见 §4.1）。已更正为 43。**建议审查方在后续核验中以此为准**。
2. **`consume_conflict()` 目前无调用方**：它供未来的 UI/调用方读取冲突，当前生产代码只用 `publish_conflict()` 把冲突写进 `binding.last_error`。若审查方认为应改为在 `CommandResult.data` 里直接返回冲突，需改动命令返回结构（属契约面之外的实现细节，可另行裁决）。
3. **B9/B10 仍挂低优先队列**（未改）；**B7 单源收敛**仍待授权。
4. **放行路径验证**（Hub 改绑 127.0.0.1）仍待用户决定。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 .venv / venv / benchmarks/；**未执行 git 写操作**；未改动用户的 Hub 配置。**本轮零契约改动、零新增依赖。**

## 8. 下一片

| 项 | 说明 |
|---|---|
| **R20–R24 成果 commit + push** | 工作树已累积较多，建议尽快 |
| B7 单源收敛 | 需授权 |
| 放行路径验证 | 需 Hub 改绑 127.0.0.1 |
| PR-020/021（C 链） | 依赖已满足 |
| PR-016..019 验收映射 | 实现已在，缺逐条映射 |
| PR-023/030/031（窗口能力） | 承接 S-UI-01 的 R11 |


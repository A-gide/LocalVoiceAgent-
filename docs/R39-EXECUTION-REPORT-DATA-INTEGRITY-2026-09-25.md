# R39 EXECUTION REPORT — R38 三处数据完整性问题（2026-09-25）

- 执行者：Codex（实现方执行位）
- 授权：用户裁决——「先补上述三条失败路径的 worker RED，做到未确认排空绝不推进水位，
  并明确无稳定来源 ID 时不能承诺无损幂等；再用 Rust 实际调用解析与裁决函数替换 F1 字符串断言」
- 基线：`f758eaf4` + 脏工作树

---

## 0. 撤回声明

R38 报告称 S3「已完成」、S2「保唯一」。**两者都宣布过头**：

| R38 的说法 | 实际 |
|---|---|
| S3「分页已完成」 | 达到 `MAX_PAGES` 上限后**仍推进水位**，上限之外的记录永久不可达 |
| S2「保唯一」 | 派生 ID 公式**仍会合并不同记录**（`file_path` 不同但其余相同），且**破坏旧数据重放幂等** |

三处均由审查方在当前工作树独立复现，我逐条复核**全部成立**。

---

## 1. 三处缺口与修复

### 缺口 1 — 未确认排空就推进水位

**复现（201 条 / 每页 1 条 / `MAX_PAGES=200`）**：

```ini
round1=200 round2=0 round3=0 total stored=200/201  wm=1790294400000000
-> GAP CONFIRMED: the cap stopped the drain but the watermark moved
```

**根因**：`import_page` 在循环结束后无条件执行 `if max_seen_ts > watermark: update_watermark(...)`，
没有记录循环是**因排空而退出**还是**因达到上限而退出**。

这与我在 R38 报告里写「部分排空不得声称进展」是**同一个错误**——我写了那句话，却没有让代码实现它。

**修复**：

1. 引入 `drained` 标志：只有「收到空页」或「返回页不满」才算排空；
2. **水位只在 `drained` 为真时推进**；未排空时保持不变并记录 warning；
3. 未排空时记录 `_resume_offset`，**下次调用从该 offset 续读**——否则不推进水位会导致每次调用都重读同样的页，同样无法前进。

**修后验证**：

```ini
after cap+resume: stored=201/201   -> FIXED
```

**残留限制（已写入代码注释，不隐藏）**：resume offset 在来源**只增不减**时安全；
若记录在两次调用之间从结果集中**消失**（删除或移除式脱敏），offset 会外移并可能跨过一条。
这正是**水位本身不推进**（范围保持开放）的原因，也是**消失的记录必须走 S5 对账路径**、
不能由缺席推断的原因。

### 缺口 2 — 派生 ID 合并不同记录

**复现**（时间/设备/时长/文本相同，仅 `file_path` 不同）：

```ini
id_a=audio_1790294400000000_f19c9f5b9f9c  file=/a.wav
id_b=audio_1790294400000000_f19c9f5b9f9c  file=/b.wav
-> GAP CONFIRMED: two distinct captures collapse to one id
```

**根因**：我的 ID 身份串是 `时间戳|设备|时长|文本`，**漏了 `file_path`**。

**修复**：身份串加入 `file_path`。`file_path` 是捕获属性，不随脱敏改变，
所以既区分不同录音，又保持脱敏前后稳定。

```ini
id_a=audio_1790294400000000_d26ff05c999a
id_b=audio_1790294400000000_f8e974cb26bb   -> FIXED
```

### 缺口 3 — 新 ID 公式破坏旧数据重放幂等

**复现**（用旧公式 `sha256(transcription)` 已入库的记录重放）：

```ini
legacy id = audio_1790294400000000_d6527f261cfc
new    id = audio_1790294400000000_204286bd2e26
same record stored 2 time(s)  -> GAP CONFIRMED: replay duplicates the record
```

**根因**：改变派生 ID 公式后，已入库的行用新公式**认不出来**，重放即重复插入。
这是**升级路径**问题，不限于本轮改动——任何 ID 公式变更都有此风险。

**修复**：normalizer 额外产出 `legacy_external_ids`（旧公式为该记录生成的 ID 列表），
worker 去重查询同时检查**当前 ID 与 legacy ID**，命中即视为同一记录。

```ini
stored=1 (expected 1)   -> FIXED
```

### 附带 — 无稳定来源 ID 时不得承诺无损幂等

按裁决要求，把限制**写进依赖它的代码路径**（`import_page` docstring）：
来源 ID 稳定 → 重放可识别；**派生 ID 不承诺无损幂等**，记录带 `stable_id: false`，
对账必须拒绝依赖它。

---

## 2. F1 断言方式替换（按裁决）

**裁决**：「用 Rust 实际调用解析与裁决函数替换 F1 字符串断言」。

### 新增 4 项 Rust 行为测试（`network_attestation.rs`）

| 测试 | 覆盖 |
|---|---|
| `a_loopback_port_whose_owner_cannot_be_read_does_not_verify` | PID 缺失 → `UNVERIFIED_BIND` + `ProcessUnmapped`，owner 报 `None` |
| `a_loopback_port_shared_by_two_processes_does_not_verify` | 多 owner → 同上（端口未被关联到**单一**已识别进程） |
| `a_loopback_port_with_one_process_on_both_stacks_still_verifies` | 同一进程双栈 → **仍为 VERIFIED**（防止修复过度） |
| `an_unreadable_pid_is_kept_as_a_row_but_a_malformed_row_is_dropped` | 两类丢弃的区分：PID 不可读**保留行**，行格式坏则**丢弃** |

### Python 侧断言改为「覆盖存在性」而非「源码字符串」

`test_red_r37_s1_s2_s3_f1.py` 的两项改为断言**这 4 个 Rust 测试用例存在**——
即负向逻辑必须由 Rust 测试**执行**，而不是被 Python 搜索到。

**我承认原做法的缺陷**：Python 断言 Rust 源码字符串，只要那段文本在就通过，
与逻辑是否真的工作无关——这正是裁决指出的问题。

---

## 3. 验证结果（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| R39 RED | `pytest tests/red_v121/test_red_r38_data_integrity.py` | **4 passed**（修复前 4 failed） |
| Rust 单测 | `cargo test --lib --offline` + `rusttest.ps1` | **79 passed / 0 failed / 1 ignored**，`stray_ping=0`（新增 4 项） |
| red_v121 + unit | `pytest tests/red_v121 tests/unit` | **443 passed** |
| 九组门禁 | `tests/run_groups.py --all` | **all groups passed**，`expected-red groups failing: []`（red-v121 **396 passed**） |

### 三处原始复现的修后状态

```ini
after cap+resume: stored=201/201      -> FIXED
id_a != id_b (different file_path)     -> FIXED
replay of legacy record: stored=1      -> FIXED
```

---

## 4. 门禁状态（不自行宣布 GREEN）

| 门禁 | 状态 |
|---|---|
| S1 字段对齐 | **已完成**（R38，审查方已确认可保留） |
| S2 派生 ID | **本轮修复**（含 `file_path` + legacy 兼容 + 诚实标记）；**对账仍须拒绝依赖派生 ID** |
| S3 分页 | **本轮修复**（排空确认 + resume）；**实机兼容性验收仍待 S4** |
| S7 F1 行为验收 | **本轮补 Rust 行为测试**；**F1 身份锚点仍关闭** |
| S5 历史脱敏对账 | **仍关闭**（需 S4 实机能力证据） |
| F1 进程身份 | **仍关闭**（需所有者确认 Hub 实例身份） |
| S4 实机 Screenpipe | **仍关闭**（需运行中的实例） |
| S6 所有者确认身份锚点 | **仍关闭**（需所有者） |
| R36/R37/R38/R39 总体 | **不得宣布 GREEN** |

---

## 5. 我在本轮犯的错误（如实记录）

1. **宣布过头**：R38 说 S3「已完成」，但我自己写的注释说「部分排空不得声称进展」，代码却没实现它。
2. **ID 公式疏漏**：加了 `file_path` 之外的属性，却漏了 `file_path` 本身——
   而我在同一段注释里正好声称「每个能区分两次捕获的属性都应参与」。
3. **F1 断言方式**：Python 断言 Rust 源码字符串，无法执行被测逻辑。

这三条的共同点：**我写下正确的原则，但没有让代码或测试实现它**。
与 R33 的 `refresh_hub_inventory()` 无调用点、R35 的注释与返回路径相矛盾，是同一个模式。

---

## 6. 硬约束遵守情况

| 约束 | 状态 |
|---|---|
| 不得 git add/commit/push/reset | **遵守**（未执行任何 git 写操作） |
| 不得弱化/跳过/xfail RED | **遵守**（本轮 RED 先失败后通过，无跳过） |
| 不得手改三个生成制品 | **遵守**（本轮未触及契约） |
| 禁用 F2/F3 / Astra | **遵守** |
| 密钥不得写入仓库/日志/报告 | **遵守** |


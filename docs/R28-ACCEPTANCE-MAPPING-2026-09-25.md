# R28 执行报告 — PR-016..019 验收映射复核 + 两项边界闭合

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「PR-016..019 验收映射」
- 前置文档：`docs/PR-016-019-FORMAL-ACCEPTANCE-2026-09-24.md`（审查方 2026-09-24 出具，四片全 PASS）

---

## 1. 本轮性质：复核而非重做

审查方已于 2026-09-24 出具正式验收裁决（四片 PASS），但该文档的**证据基线是 HEAD `292b23c`**，其后已有 4 个提交（R20–R27）。因此本轮做的是：

1. **核对该文档引用的 37 项测试是否仍然在档且全绿**（基线漂移检查）；
2. **闭合文档自列的、可在代码层处置的开放边界**；
3. 其余边界如实保留，不回填 PASS。

### 1.1 引用核对结果

逐名核对文档引用的 10 个关键测试（`test_i06_raw_text_immutable_trigger`、`test_i17_replay_idempotency`、`test_atomic_revision_and_fts_sync`、`test_nullable_confidence_constraint`、`test_migration_idempotent_rerun`、`test_schema_unknown_safety_stop`、`test_event_relative_time_anchor`、`test_repeated_expression_mention_index_and_spans`、`test_timezone_offset_midnight_anchoring`、`test_parse_failure_unrestricted_fts`）：

- **全部在档**（`tests/unit/test_journal_schema.py`、`test_legacy_migration.py`、`test_screenpipe_importer.py`、`test_temporal_recall.py`）；
- **37 passed / 0 failed**（`pytest tests/unit/test_journal_schema.py tests/unit/test_legacy_migration.py tests/unit/test_screenpipe_importer.py tests/unit/test_temporal_recall.py tests/migration -q`）。

**结论：文档引用未因 R20–R27 失效，四片 PASS 裁决继续成立。**

---

## 2. 边界 1（PR-016「DB lock rollback」）：已闭合

### 2.1 原文边界

> 并发锁竞争专项测试缺失；现有证据为单连接原子性回滚。建议在 PR-035 前补一项多连接锁竞争测试，或正式裁决单写者（single-writer repository）架构下该场景不适用。

### 2.2 开工前核实

- `tests/unit` 全目录 lock/rollback **零命中**（确认文档判断）；
- `repository.py` 无 `BEGIN`/`ROLLBACK`/`IntegrityError` 显式处理（确认）；
- 但 `schema.py` L6 `PRAGMA journal_mode=WAL` 在档，说明 WAL 语义是设计的一部分。

### 2.3 新增 `tests/unit/test_journal_lock_contention.py`（4 项）

| 测试 | 断言 |
|---|---|
| `test_a_second_writer_cannot_steal_an_open_transaction` | 仓库持有写事务时，第二个连接被 SQLite 锁**拒绝**（非静默接受） |
| `test_the_losing_writer_leaves_no_partial_state` | 输家**不留任何残留**——这正是验收条要的 rollback |
| `test_the_winner_transaction_stays_readable_and_consistent` | 竞争后赢家事务完整，且 **FTS 镜像与基表一致** |
| `test_readers_are_not_blocked_by_a_writer_in_wal_mode` | WAL 下读者看到已提交状态，**看不到未提交写入** |

### 2.4 实现过程中我犯的两处测试错误（记录在案）

写这组测试时我三次猜错产品事实，全部由测试自身抓出：

1. **列名错**：我以为 `events` 有 `turn_id` 和 `current_text` 列。实际是 `turn_sequence`，而 `current_text` **是视图**（`schema.py` L109-115 `CREATE VIEW current_event_text`）不是基表列。
2. **`current_revision` 语义错**：我断言新事件 `current_revision == 1`，实测 **0**。0 才是正确语义——「尚无修订，raw 文本仍是权威」，首次修正才变 1（`schema.py` L40 默认值 0）。
3. **FTS 中文查询错**：我用中文子串查 FTS 得 0 命中。原因是既有 `_segment_text` 把 CJK **按字切分**（探针实测 `锁竞争后的` → `锁 竞 争 后 的`），子串自然查不中。这不是缺陷——CJK 短语精度另有 `test_cjk_fts_phrase_query_precision` 覆盖；该测试的目的是**镜像一致性**，故改用 ASCII 文本，避免分词掩盖丢失的更新。

这三处都是**测试断言错、产品正确**。我按产品实际语义修正断言，而非改产品迁就测试。

---

## 3. 边界 2（PR-019「DST」）：已闭合，且含一次正式撤回

### 3.1 原文边界

> `test_timezone_offset_midnight_anchoring` 覆盖固定 offset；真实 IANA 时区夏令时跳变日场景未单列。

### 3.2 调查中发现并**撤回**的一个假缺陷

探针显示本机 `zoneinfo` **没有时区数据库**（`tzdata` 未安装，`available_timezones()` 返回 0），`Asia/Shanghai` 解析抛异常。据此我初判：`_resolve_timezone` 的 `except Exception: pass` 会**静默回落 UTC**，使 23:30 UTC 的事件本地日算错一天（09-20 vs 09-21），并写了 3 项 RED。

**RED 跑出 2 失败**，但进一步核对调用链后确认：**这是我测试越界，产品无此缺陷。**

关键事实（逐行核实）：

| 位置 | 事实 |
|---|---|
| `screenpipe_importer/normalize.py` L24 | 生产写入的 `event_timezone` 是 **`UTC+08:00` 这种 offset 字面量**，不是 IANA 名；且**同时**给出 `utc_offset_minutes` |
| `worker.py` L95/L96 | 两者一并传入 repository |
| `repository.py` L28-29 | 名字解析失败后**回落到 offset**，不是回落 UTC |
| 全仓 grep | **没有任何生产者写 IANA 名**（`Asia/`、`Europe/`、`America/` 在 src 零命中） |

实测四种形状（探针）：

```
name+offset（生产形状 UTC+08:00/480） -> 2026-09-21  ✓
unknown name + offset 480            -> 2026-09-21  ✓
offset only                          -> 2026-09-21  ✓
utc only                             -> 2026-09-20  ✓（对照）
```

我的失败断言传的是「IANA 名 + `offset_mins=0`」——**生产不可能产生的组合**。断言要求产品对不可达输入给出行为，这是测试缺陷。

**撤回声明**：该假缺陷结论予以撤回。`_resolve_timezone` 的降级路径**是正确的**——offset 才是消歧依据，名字解析失败不会让调用方丢掉本地日边界。

### 3.2 改写后的 `tests/red_v121/test_red_timezone_anchor_shapes.py`（5 项）

改为测试**真正到达 repository 的形状**：

| 测试 | 断言 |
|---|---|
| `test_the_stored_screenpipe_shape_resolves_to_the_right_local_day` | 生产形状（`UTC+08:00`+480）落对本地日 |
| `test_an_unresolvable_name_still_uses_the_offset_not_utc` | 名字不可解析时**用 offset 而非 UTC**——降级路径不是静默 UTC |
| `test_the_offset_alone_is_enough_to_anchor_the_day` | 仅 offset 也能锚定 |
| `test_utc_events_stay_on_their_utc_day` | 对照组：无 offset 不位移，使上面的断言有意义 |
| `test_a_stored_event_anchors_today_to_the_local_day` | 端到端：存储的 provenance 与实际锚点描述**同一天** |

一处测试瑕疵也由运行抓出：我断言 `range_end - range_start == 1 天` 整数相等，实测差 **1 微秒**（实现用排他末端）。改为比较日边界（差 < 1 秒），并注明原因。

### 3.3 保留的边界（不回填 PASS）

**真正的 IANA 夏令时跳变日仍未测试**，理由是**没有代码路径会存 IANA 名**。若未来切片开始存名字，本文件即为补该用例的位置，且「静默回落」问题届时才真正成立。这一点如实保留。

---

## 4. 验证（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 文档引用核对 | 4 个 unit 文件 + tests/migration | **37 passed / 0 failed** |
| 新增锁竞争 | `pytest tests/unit/test_journal_lock_contention.py` | **4 passed** |
| 新增时区形状 | `pytest tests/red_v121/test_red_timezone_anchor_shapes.py` | **5 passed** |
| red_v121 | `pytest tests/red_v121 -q` | **280 passed / 0 failed**（R27 为 275，+5） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / **unit 47**（43→47，+4 锁竞争）/ fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |

**零契约改动**：`contracts/` 未触碰，三个生成制品字节未变。

**零产品代码改动**：本轮只新增测试文件。两处边界均经核实后判定为「产品正确、测试缺失」，故不需要修改产品。

---

## 5. 四片裁决的最终状态（更新后）

| 切片 | 审查方裁决（2026-09-24） | 本轮更新 |
|---|---|---|
| PR-016 | PASS（DB lock 部分覆盖） | **边界已闭合**，4 项新测试支撑 |
| PR-017 | PASS | 引用核对通过，无变化 |
| PR-018 | PASS | 引用核对通过，无变化 |
| PR-019 | PASS（DST 未单列） | **边界已闭合**（5 项新测试）；真实 IANA 跳变日如实保留为未测试 |

---

## 6. 其余开放项（如实保留，不回填 PASS）

| 项 | 状态 |
|---|---|
| **全部证据仍为单测/fixture 级** | 无真实 Screenpipe 服务、无真实生产旧库迁移演练（文档 §边界 2） |
| **真实 IANA DST 跳变日** | 未测试（无代码路径存 IANA 名，见 §3.3） |
| **PR-018 `real_client` 命名** | 测试名含 `real_client` 但目标是受控 mock/fixture（文档已标注） |
| **B 链交付轮数字瑕疵** | `197 passed` 应为 `204`（文档已记录，不影响裁决） |

---

## 7. 提交范围

- `tests/unit/test_journal_lock_contention.py`（新增，4 项）
- `tests/red_v121/test_red_timezone_anchor_shapes.py`（新增，5 项）
- 本报告

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪）。


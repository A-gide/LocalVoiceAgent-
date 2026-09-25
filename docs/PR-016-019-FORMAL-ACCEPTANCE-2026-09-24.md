# PR-016..019 正式验收裁决（审查方独立执行）

- **日期**：2026-09-24
- **执行方**：独立审查方（非实现方）；依据冻结计划 `ARCHITECTURE-PLAN-2026-09-v1.2.1.md` L1290–1328 逐字条文
- **证据基线**：HEAD `292b23c`；`red_v121` 228P/0F；v12 层 7/7 全绿（审查方本人重跑）；37 项切片专属单测逐一收集映射
- **方法**：逐条验收文 → 测试名/代码行号双向映射；未映射项如实标注，不回填 PASS

---

## PR-016 — Journal v2 schema and repository（计划 L1290–1298）：**PASS（1 项部分覆盖）**

| 验收条（L1297） | 证据 | 判定 |
|---|---|---|
| I06（raw 不可变） | `test_i06_raw_text_immutable_trigger` + `test_i06_event_revisions_immutable_trigger`；触发器源码 `schema.py` L118–126（`trg_events_prevent_raw_update` / `trg_revisions_prevent_update`） | ✅ |
| I17（幂等） | `test_i17_replay_idempotency`（importer 侧重放）+ invariants 组 `test_i17_importer_idempotent_replay` | ✅ |
| raw update abort | 同上 I06 触发器测试（UPDATE raw 触发 ABORT） | ✅ |
| revision/FTS atomic | `test_atomic_revision_and_fts_sync` | ✅ |
| DB lock rollback | **部分覆盖**：原子性回滚由 `test_atomic_revision_and_fts_sync` 覆盖；**"DB 锁竞争"专项场景无对应测试**（tests/unit 全目录 lock/rollback 零命中，`repository.py` 亦无 ROLLBACK/IntegrityError 显式处理） | ⚠️ 部分 |
| nullable confidence | `test_nullable_confidence_constraint` | ✅ |

步骤面（L1295）补证：WAL/FK = `schema.py` L6/L7（`PRAGMA journal_mode=WAL` / `foreign_keys=ON`）；hard-delete service/audit = `test_privacy_deletion_service_audit` + `test_privacy_deletion_actual_count_matches_existing_rows`（rowcount 真实计数）；schema 8 表（sessions/turns/events/event_revisions/temporal_mentions/import_checkpoints/deletion_audit/events_fts）已在 B 链核验轮坐实。

## PR-017 — Legacy memory migration（计划 L1300–1308）：**PASS**

| 验收条（L1307） | 证据 | 判定 |
|---|---|---|
| repeated migration idempotent | `test_migration_idempotent_rerun` + `test_dry_run_with_existing_records_detects_skipped` + `tests/migration/test_legacy_migration_idempotent` | ✅ |
| 故障不切 active DB | `test_missing_or_corrupt_legacy_db` | ✅ |
| 报告 counts 守恒 | `test_migration_conservation_and_revisions` + `tests/migration/test_legacy_migration_conservation_and_revisions` | ✅ |

步骤面（L1305）补证：snapshot/checksum = `test_checksum_calculation`；invalid quarantine = `migrate_legacy.py` L40/53/73/83/165/170（invalid/quarantine 处理链）；CLI script = `test_cli_execution`。

## PR-018 — Screenpipe REST importer（计划 L1310–1318）：**PASS**

| 验收条（L1317） | 证据 | 判定 |
|---|---|---|
| I17 | `test_i17_replay_idempotency` | ✅ |
| crash/replay 不重复 | `test_atomic_page_transaction_and_checkpoint` + `test_i17_replay_idempotency` | ✅ |
| schema unknown 安全停 | `test_schema_unknown_safety_stop` | ✅ |
| 原 timestamp/timezone 保留 | `test_normalization_with_timezone_and_redaction` | ✅ |

步骤面（L1315）补证：capability probe = `test_real_client_probe_capabilities_and_type_hints`；checkpoint = 同原子页测试；external unique id = `test_normalization_fallback_id_generation`（sha256 兜底）；redaction handling = 同上 normalization 测试；optional read-only adapter = `test_optional_sqlite_adapter`。

## PR-019 — Temporal recall and correction history（计划 L1320–1328）：**PASS**

| 验收条（L1327） | 证据 | 判定 |
|---|---|---|
| "2026-09-10 明天"锚定 09-11 | `test_event_relative_time_anchor` | ✅ |
| "明天上午…明天下午…"两个不同 mention_index/span | `test_repeated_expression_mention_index_and_spans` | ✅ |
| DST/offset | `test_timezone_offset_midnight_anchoring`（offset 锚定；真时区库级 DST 场景未单列，见边界） | ✅ |
| 失败不缩到最近时段 | `test_parse_failure_unrestricted_fts` | ✅ |

步骤面（L1325）补证：parser adapter/version = `temporal.py` L153（`"parser_version": "1.0"`）+ L154 `parse_status`；query routing / parse-failure unrestricted FTS = `recall.py` L49 `search()` + 对应测试；revision UI DTO = `test_event_history_dto`（`models.py` L67/89/98/109 DTO 族）；修订隔离 = `test_revised_event_isolates_superseded_temporal_mentions`（`tm.revision = e.current_revision`，`recall.py` L79）；CJK 短语精度 = `test_cjk_fts_phrase_query_precision`（`_fts_query` 引号化，L29–40）；停用词条件清理 = `test_non_temporal_query_preserves_filler_nouns`。

另：invariants 组 `test_temporal_recall_dual_anchor` + `test_temporal_recall_full_scenario` 双场景在 v12 层全绿（审查方重跑）。

---

## 总裁决

| 切片 | 裁决 |
|---|---|
| PR-016 | **PASS**（DB lock 竞争场景部分覆盖，见下） |
| PR-017 | **PASS** |
| PR-018 | **PASS** |
| PR-019 | **PASS** |

## 边界与开放项（不回填 PASS，随 PR-035 复核）

1. **PR-016「DB lock rollback」**：并发锁竞争专项测试缺失；现有证据为单连接原子性回滚。建议在 PR-035 前补一项多连接锁竞争测试，或正式裁决单写者（single-writer repository）架构下该场景不适用。
2. **全部证据为单测/fixture 级**：无真实 Screenpipe 服务、无真实生产旧库的迁移演练。PR-018 的 capability probe 测试名含 `real_client` 但目标为受控 mock/fixture。
3. **DST**：`test_timezone_offset_midnight_anchoring` 覆盖固定 offset；真实 IANA 时区夏令时跳变日场景未单列（offset 语义下可推导，但未实测）。
4. B 链交付轮报告数字瑕疵（`197 passed` 应为 `204`）已在该轮审查记录，不影响本裁决。

—— 独立审查方，2026-09-24

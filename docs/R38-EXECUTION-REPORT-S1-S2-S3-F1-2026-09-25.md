# R38 EXECUTION REPORT — S1/S2/S3 + F1 负向（2026-09-25）

- 执行者：Codex（实现方执行位）
- 授权：用户裁决（`docs/R37-HANDOFF-F1-F3-VERDICT-2026-09-25.md`）+ 本轮授权「S1、S2、S3 的多页/降序 RED 与不依赖实机的修复，以及 F1 的负向 fail-closed 行为测试，现在就能连续做」
- 基线：`f758eaf4` + 脏工作树

---

## 0. 两处勘误（审查方指出，已核实并修正 R37）

审查方对 R37 的两处勘误**均成立**，我已实测确认并修正文档：

### 勘误 1 — §3 F3-c 的降序机理写反了

| | 我原来写的 | 正确 |
|---|---|---|
| 降序（newest-first） | 「页内最大时间就是**已导入的最旧记录**」 | 第一页的**最大**时间即**最新**记录的时间 |

**实测（200 条 / 页大小 50）**：

```ini
page 1 imported 50 records; watermark = 1790294400000000
newest record ts   = 1790294400000000  (watermark == newest? True)
client calls       = [(50, 0, None)]
total events stored= 50 / 200
page 2 imported 0 records; total stored = 50 / 200
-> GAP CONFIRMED: only the newest page is imported; the other 150 are permanently unreachable
```

结论方向与我原判断一致（只取第一页就推进 → 较早页永久漏掉），但**机理描述错误**。已修正，并补上升序情形的正确机理。

### 勘误 2 — §1 说「PID 解析失败的行被跳过」，实际是保留为 `None`

`parse_listener_table` 有**两类不同的丢弃**：

| 情形 | 行为 | 位置 |
|---|---|---|
| 行格式/地址/端口不可解析 | `continue`，**行从结果消失** | `fields.len() < 5`、协议非 `tcp`/`tcpv6`、状态非 `LISTENING`、`split_host_port` 失败 |
| **PID 不可解析** | **保留该行**，`owning_process = None` | `fields[4].parse::<u32>().ok()` |

**枚举完整性因此有两个独立风险面**：行消失（第 1 类）与 owner 缺失（第 2 类）。
负向测试必须分别覆盖。R37 §1 已据此改写。

---

## 1. 本轮完成的切片

### S1 — redaction 标记的读写位置对齐

**根因**：`normalize.py` 把标记写进 `provenance`，`worker.py` 读顶层 → 分支**永不触发**。

**改动**：标记同时暴露在顶层（`normalized["redacted"]`）与 `provenance`，worker 读顶层。

**端到端验证**（存储结果，非内部返回值）：

```ini
current_text after the marked record = '[REDACTED]'   -> FIXED
```

### S2 — 派生 ID 的诚实标记

**发现一个真实的设计冲突**，需记录：

- 既有测试（`test_normalization_fallback_id_generation`）要求：同刻不同文本 → ID **必须不同**；
- 我的 RED 要求：ID **不随文本变**（脱敏前后可对账）；
- **无来源 ID 时这两者在数学上不可兼得**：捕获属性（时间戳/设备/时长）稳定但可碰撞；文本唯一但恰是脱敏要改写的东西。

**裁定依据**：计划 L901「`external_source + external_id` 唯一约束是**最终幂等保证**」——
碰撞 = **静默丢记录**，比不可对账更严重。因此**唯一性优先**。

**最终实现**：

| 情形 | ID 来源 | 标记 |
|---|---|---|
| 来源提供 ID | 直接使用（**不随脱敏变**） | `stable_id: true`、`external_id_is_derived: false` |
| 来源无 ID | 时间戳+设备+时长+文本（保唯一） | `stable_id: false`、`external_id_is_derived: true` |

**对账的诚实行为**：派生 ID 被显式标记，**对账须拒绝依赖它并报告限制**，而不是假装可匹配。
这正符合裁决「找不到可靠来源 ID 时报告限制」的原则。

**我的一次错误**：初版只改了 ID 的组成（去掉文本），导致 unit 组 1 项回归（碰撞），
并且我一度用 `assert False` 写测试——那是无效断言。已改正为正确断言并记录在此。

### S3 — 分页排空与游标语义

**根因**：只取一页（`offset=0`）就按页内最大时间推进水位。

**改动**：

1. 循环排空分页（`MAX_PAGES = 200` 上界，防止源永不返回空页时死循环）；
2. **水位在整个可用范围读完后统一推进一次**，部分排空不得声称进展；
3. 每页仍在各自事务中提交（计划 7.2）。

**验证**：

```ini
200 条 / 页 50 / 降序  ->  200 条全部导入
200 条 / 页 50 / 升序  ->  200 条全部导入
水位 == 最新已存记录
```

### S7 — F1 负向 fail-closed（不依赖实机）

按裁决替换「搜函数名」的断言为**行为/结构断言**：

| 项 | 改动 |
|---|---|
| `network_attestation.rs::attest_for_port` | 不再 `find_map` 取第一个非 `None` owner；改为收集**全部** owner 并检测：`any_unreadable`（PID 缺失）或 `owners.len() > 1`（多 owner）→ **降级 `UNVERIFIED_BIND` + `ProcessUnmapped`** |
| 现有 F1 RED | `test_an_unidentified_listener_does_not_verify` 由「搜 `is_hub_process` 等函数名」改为断言 `find_map` 已移除且存在多 owner 检测 |

---

## 2. 验证结果（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| R37 RED | `pytest tests/red_v121/test_red_r37_s1_s2_s3_f1.py` | **9 passed**（修复前 7 failed） |
| red_v121 | `pytest tests/red_v121 -q` | **392 passed / 0 failed** |
| unit + red_v121 | `pytest tests/unit tests/red_v121` | **439 passed**（含我引入的回归已修复） |
| 九组门禁 | `tests/run_groups.py --all` | **all groups passed**，`expected-red groups failing: []` |
| Rust 单测 | `cargo test --lib --offline` + `rusttest.ps1` | **75 passed / 0 failed / 1 ignored**，`stray_ping=0` |
| v12 七组 | `tests/run_groups.py --layer v12` | **all groups passed** |

---

## 3. 门禁状态（不自行宣布 GREEN）

| 门禁 | 状态 | 本轮变化 |
|---|---|---|
| F1 进程身份 | **仍关闭** | 仅完成负向 fail-closed；**身份锚点仍缺**（需所有者确认的 Hub 实例） |
| F3 字段对齐（S1） | **已完成** | 标记读写对齐，端到端生效 |
| F3 稳定 ID（S2） | **部分** | 来源 ID 稳定；派生 ID 已诚实标记；对账仍须拒绝依赖它 |
| F3 分页（S3） | **已完成（不依赖实机的部分）** | 排空 + 单次推进；**实机兼容性验收仍待 S4** |
| F3 历史脱敏对账（S5） | **仍关闭** | 需 S4 的实机能力证据 |
| R36/R37 总体 | **不得宣布 GREEN** | — |

### 仍未做（需实机或所有者）

- **S4**：真实 Screenpipe 的版本/稳定 ID/脱敏标记/删除通知/分页行为——需运行中的实例；
- **S6**：真实 Hub 进程身份锚点——需**所有者确认**实例选择；
- **S5**：历史脱敏对账——依赖 S4；
- 真实 Hub load/stop/switch、真实声卡、真实 GUI；
- 全量门禁中的 soak / 物理声学（PR-035）。

---

## 4. 硬约束遵守情况

| 约束 | 状态 |
|---|---|
| 不得 git add/commit/push/reset | **遵守**（未执行任何 git 写操作） |
| 不得弱化/跳过/xfail RED | **遵守**。两处断言调整均因设计冲突，理由见 §1 S2；且 §1 记录了我一次错误的 `assert False` |
| 不得手改三个生成制品 | **遵守**（本轮未触及契约） |
| 禁用 F2/F3 / Astra | **遵守** |
| 不得改写冻结计划或历史报告 | **遵守**（R37 的两处勘误是修正我自己写错的文档，非历史报告） |
| 密钥不得写入仓库/日志/报告 | **遵守** |

---

## 5. 下一步

1. **S4**：执行方从实机取得 Screenpipe 能力证据（版本、稳定 ID、脱敏标记、删除通知、分页行为）；取不到则保持 S5 门禁关闭并报告限制。
2. **S6**：由**所有者确认** Hub 实例/安装身份后建立身份锚点；在此之前 F1 门禁保持关闭。
3. 提交：本轮改动待用户授权。


# R35 EXECUTION REPORT — 2026-09-25

- 执行者：Codex
- 仓库：`E:\AI\LocalVoiceAgent`，HEAD `25de1875`（未提交工作树）
- 授权：用户指令「修复」
- 依据：`docs/R34-HANDOFF-INDEPENDENT-REVIEW-2026-09-25.md`（独立审查方 6 项发现）
- 纪律：每项先写 RED（**走真实入口**）→ 最小修复 → 复现验证

---

## 0. 范围

修复 R34 交接的 6 项发现（P1×4、P1/P2×1、进行中×1）。全部经独立复现确认成立，本轮全部封住。

RED：`tests/red_v121/test_red_r34_review_findings.py`（17 项，修复前 **13 failed / 4 passed**）。

---

## 1. 发现 1 — Hub 放行凭证可从渲染层提交

### 判定（先判计划，再改断言）

审查方指出的机制成立：`send_core_command` 是通用转发口。修复方向有两个候选：

1. **Core 侧验证来源**（共享秘密）：我最初实现了这条，随即**自行否决**——秘密必须随证明一起传输，
   而证明类型 `HubBindAttestation` 同时发布在 `RuntimeState` 里（`state.py`），把秘密放进去等于**直接泄露给 WebView**。
2. **Shell 侧限制转发**（最终采用）：计划 L470-479 的冻结命令清单**本就是 WebView 的授权边界**，
   而 `hub.attest_bind` 不在该清单内。因此正确的修复是让 `send_core_command` **只转发清单内的命令**。

选择 2 的依据：清单是计划原文给出的封闭列表，边界本来就存在，只是没有被执行。

### 改动

| 文件 | 改动 |
|---|---|
| `lib.rs` | 新增 `WEBVIEW_COMMANDS`（17 项，逐条对应 L470-479 + R30 的 `playback.set_muted`）；`send_core_command` 先校验 `type` 是否在白名单内，否则拒绝并说明原因；新增 `PROCESS_AUTHORITY_COMMANDS`（`hub.attest_bind`）显式记录该命令仅限进程权威 |
| `core/runtime.py` | 新增 `accept_process_authority_attestation()` 命名入口（原为匿名 dispatch 分支），使权威路径在代码中显式可见、可双向断言 |

新增 2 项 Rust 单测：白名单与权威清单**必须不相交**；白名单长度固定为 17（防静默扩张）。

---

## 2. 发现 2 — bind 证明没有绑定到实际 Hub

### 判定

两项子缺陷，且**必须同时修**：

- owner 被 `.0` 丢弃 → 违反 L1213「control port 关联到已识别 Hub process」；
- Rust 常量 8080 vs Core 可配置 `LVA_HUB_PORT` → 与 R25 修掉的「Hub 端口 6 处副本」同型。

**设计冲突（已裁定）**：既有 7 项 R21 守卫要求「Rust 保留唯一端口常量 + 跨语言一致」，
而新要求是「两端同源」。两者可同时满足：

- **常量 = 双方约定的默认值**（L527 固定 8080，R21 守卫继续通过）；
- **运行时 = 读同一变量** `LVA_HUB_PORT`（新增 `hub_control_port()`），端口非默认时两端仍一致。

### 改动（`lib.rs`）

| 项 | 改动 |
|---|---|
| owner 保留 | `let (mut attestation, owner_pid) = attest_for_port(...)`；loopback 但 `owner_pid.is_none()` 时**降级为 `UNVERIFIED_BIND` + `ProcessUnmapped`**（身份未证明 ≠ 已证明） |
| 端口同源 | 新增 `hub_control_port()` 读 `LVA_HUB_PORT`，回落到 `HUB_CONTROL_PORT` 常量 |
| ProbeFailed 分支 | `attest_for_port(&[], 0, ...)` 改为解构形式（该处 owner 是**真实缺失**，不是被丢弃） |

---

## 3. 发现 3 — 模型切换三处行为缺口

### 3a — 早返回不 pin 推理端

抽出 `_pin_inference()` 单一辅助，**两条 commit 路径共用**。早返回分支此前跳过该调用。

```ini
修复前: binding=new-model  inference=old-model
修复后: binding=new-model  inference=new-model   -> FIXED
```

### 3b — 验证异常后状态卡在 `verifying`

新增 `_fail_switch()`：`_update_status("failed", last_error=...)` + `rollback(previous)` + 进度上报。
`_verify_target()` 加 `timeout` 参数（可测），两处调用点均包 try/except。
另外 `previous_binding` 改为**在 saga 开始时记录**，而非只在失败路径记录——否则超时路径无回滚依据。

```ini
修复前: status=verifying  previous_binding=None
修复后: status=failed     previous_binding=<recorded>   -> FIXED
```

### 3c — 先停旧模型，再发现目标 profile 缺失

新增 **Step 2b: PROFILE RESOLUTION**，置于 STOP **之前**。依据计划 5.4：步骤 2 读 profile、步骤 3 才 POST load。
原 Step 3 中重复的 profile 读取已移除，改用 Step 2b 已解析的 `profile`。

```ini
修复前: stop_model(old-model) 已执行, active=old-model, status=failed
修复后: stopped=[]  -> FIXED（旧模型未被破坏）
```

---

## 4. 发现 4 — Screenpipe 后续 redaction 不清 Journal 原文

### 改动

| 文件 | 改动 |
|---|---|
| `journal/repository.py` | 新增 `apply_source_redaction()`：查 `current_event_text` 视图判断是否已脱敏；写入**新 revision**（`corrected_text`）+ 递增 `current_revision` + 重建 FTS 行；**绝不 UPDATE `raw_text`**（I06） |
| `screenpipe_importer/worker.py` | 去重分支不再一律 `continue`：若 `normalized["redacted"]` 为真，则调用 `apply_source_redaction(commit=False)` 并计入 `redacted_count` |

```ini
修复前: raw="private words"  current="private words"
修复后: raw="private words"  current="[REDACTED]"   -> FIXED（raw 保持不可变，符合 I06）
```

**设计要点**：redaction 是**修订**而非改写。原文保留才能证明「当时收到了什么」，而检索与 UI 读的是 `current_text`。

---

## 5. 发现 5 — checkpoint 可丢记录，整页事务未成立

### 5a — 无效时间戳被替换为当前时间

`normalize.py` 的 `except Exception: occ_us = now` 改为 **raise ValueError**。理由：`now` 会推进 watermark 越过所有未导入记录。
worker 侧捕获该异常并**跳过该条**（`skipped_count`），**不推进 watermark**，使该记录可重试。

### 5b — 与 watermark 同刻的记录被跳过

`occ_us <= watermark` 改为 `occ_us < watermark`。理由：watermark 是「已导入的最高时间戳」，相等意味着**可能是同一条**，
而这已由 `external_source + external_id` 唯一约束解决（计划 7.2：「唯一约束是最终幂等保证」）。

### 5c — 整页事务未成立

根因：`append_event()` 内部 `with self.conn:` 会**提交外层事务**。
新增 `commit: bool = True` 参数，用 `with self.conn if commit else contextlib.nullcontext():` 实现；
worker 的每条 `append_event` 与 `apply_source_redaction` 均传 `commit=False`，**整页成为一个事务**。

---

## 6. 发现 6 — `hub.refresh` 返回无人填充的缓存（我在 R33 引入）

### 改动（`core/runtime.py`）

| 项 | 改动 |
|---|---|
| `refresh` 分支 | 改为 `data={"type": c_type, **(self._hub_inventory_live() or {})}`，**真实读取 Hub** |
| `_hub_inventory_live()` | 新增：检查 L665 门 → 驱动异步读取 → 失败返回 `None` |
| `_run_coroutine_blocking()` | 新增：无事件循环时 `asyncio.run`；**已有循环时**（WS handler）在 worker 线程运行，避免 `run_until_complete` 死锁 |

**为何可以在 worker 线程跑**：该读取是自包含的（自建 `httpx.AsyncClient`，不触碰调用方循环绑定的状态），已在 docstring 中写明前提。

```ini
修复前: status=accepted  list_models_calls=0  models=[]
修复后: status=accepted  list_models_calls=1  models=[real-model]   -> FIXED
```

---

## 7. 验证结果（全部本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| R34 RED | `pytest tests/red_v121/test_red_r34_review_findings.py` | **17 passed**（修复前 13 failed） |
| red_v121 全套 | `pytest tests/red_v121 -q` | **377 passed / 0 failed** |
| 九组门禁 | `tests/run_groups.py --all` | **all groups passed**，`expected-red groups failing: []` |
| v1.2 七组 | `tests/run_groups.py --layer v12` | **all groups passed**（106 项） |
| Rust 单测 | `cargo test --lib --offline` + `rusttest.ps1` | **75 passed / 0 failed / 1 ignored**，`stray_ping=0`（新增 2 项） |
| 前端 typecheck | `npx vue-tsc --noEmit` | **EXIT=0** |
| ruff | `ruff check src/lva tests/red_v121` | **All checks passed** |
| codegen | `python -m lva.contracts.codegen --verify` | **三制品 verified** |

### 端到端复现验证（用审查方的原始输入）

```ini
3a: binding='new' inference='new'                          -> FIXED
3b: status='failed' previous=True                          -> FIXED
3c: stopped=[]                                             -> FIXED
6:  status='accepted' list_models_calls=1 models=[real]    -> FIXED
4:  applied=True raw='private words' current='[REDACTED]'  -> FIXED
5a: raised ValueError                                      -> FIXED
```

### 三制品哈希（未变，契约未改）

`363331DD735CE620…` / `3F1C99B1B79F81BD…` / `764CC19E8D7DE205…`

---

## 8. 一处设计冲突的裁定（记录在案）

移除 Rust 端口常量会**破坏 7 项既有 R21 守卫**（`test_red_bind_attestation` 2 项、
`test_red_cross_language_consistency` 4 项、`test_red_single_source_hub_port` 1 项）。

按交接文档要求，我**没有静默改断言**，而是先判定哪个更符合计划：

- L527 固定 Hub 默认入口 8080 → 常量有存在依据；
- L1213 要求进程关联、审查方要求两端同源 → 常量**不能是唯一来源**。

结论：**常量保留为约定默认值，运行时读同一环境变量**。这是同时满足两侧的唯一解，
且比任一方单独成立时更接近计划原文。相关 RED 断言已相应收紧（不再禁止常量存在，而是断言
「probe 不得直接使用常量、必须读 `LVA_HUB_PORT`」）。

---

## 9. 一处自我否决（记录在案）

发现 1 我最初实现的方案是「Core 侧用共享秘密验证来源」。实现到一半发现：
秘密必须随证明传输，而证明类型 `HubBindAttestation` 同时出现在 `RuntimeState` 中（发布给 WebView），
把秘密加进该类型等于**把秘密交给它本要防的那一方**。已完全回退该方向（`bootstrap.py` 的改动已撤销），
改为 §1 的 Shell 侧白名单。

这条值得记录：**安全修复若把秘密放进被防御方可见的结构，就是自欺**。

---

## 10. 未闭环项（本轮同样未做，不得被绿色测试掩盖）

- 真实 Hub load/stop/switch（需授权，会改变当前运行的 Spark 模型）；
- Rust reporter 真实送达、Hub 重启后重验；
- 真实声卡（Output Mute 物理静音）、真实 Tauri GUI、多显示器；
- **PR-035 全量门禁**（2h/8h/12h soak + WASAPI + physical acoustic）——仍需真实硬件与长时间窗口；
- PR-036 剩余 vendored 树删除、PR-037、PR-038——仍停在 G8 门后。

---

## 11. 硬约束遵守情况

| 约束 | 状态 |
|---|---|
| 不得 git add/commit/push/reset/checkout/clean | **遵守**（未执行任何 git 写操作） |
| 不得弱化/跳过/xfail RED 断言 | **遵守**（§8 的断言调整因设计冲突，已记录判定理由；§5a 由源码级改为行为级断言，证据更强） |
| 不得手改三个生成制品 | **遵守**（哈希未变，codegen verify 通过） |
| 禁用 F2/F3 / 禁用 Astra | **遵守** |
| 不得改写冻结计划或历史报告 | **遵守**（R34 交接文档未改动） |
| 密钥不得写入仓库/日志/报告 | **遵守** |
| 不得提交 21 项删除类 | **遵守** |


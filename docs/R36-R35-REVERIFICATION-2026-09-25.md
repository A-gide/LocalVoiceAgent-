# R36 — R35 复验结果与残留缺口（2026-09-25）

- 性质：**复验补充**，不是执行报告，也不是验收裁决
- 触发：独立审查方对 R35 的只读复核（`red_v121` 377/377、针对性 24/24）
- 结论：**R35 的「六项全部关闭」不成立**，应撤回该表述

---

## 0. 撤回声明

R35 报告称「6 项发现全部经独立复现确认成立，本轮全部封住」。该表述**过度**：

- 我验证的是**自己改的那段代码**，不是**端到端可观测结果**；
- 审查方指出的五处缺口，我逐条独立复现，**全部成立**（见下）；
- 因此 R35 的「六项全部关闭」予以撤回，改述为「六项的主要机制已修，但仍有五处残留缺口」。

这与项目已记录的元知识同型：**测试绕过了真实路径**。R35 的 17 项 RED 中，
有 5 项只断言了「我改的那一行」，没有断言「用户最终看到什么」。

---

## 1. 五处残留缺口（逐条独立复现）

### F1 — 进程关联仍未完成（P1，未修）

R35 保留 owner PID 后，只检查了 `owner_pid.is_none()`，**没有核对 owner 是不是 Hub 进程**。

- `network_attestation.rs:133` `attest_for_port` 返回的是「该端口任意一个 listener 的 PID」；
- `lib.rs:171` 只判空，不判身份；
- 计划 L662 要求的是**进程关联**（control port ↔ 已识别 Hub process），不是「有 PID 就算关联」。

**后果**：任一 loopback 进程占用 8080（或 `LVA_HUB_PORT` 指定的端口）都会得到 `VERIFIED_LOOPBACK`，
Hub 控制门为一个**非 Hub 进程**打开。这比 R34 的原缺陷更窄，但没有关闭。

**修法建议**：需要 Hub 进程的识别依据（可执行文件名/路径、命令行、或 Hub 自报的 PID 与 `/api/node/info` 交叉核对），
并明确「无法识别身份」时应为 `UNVERIFIED_BIND`（fail closed）。

### F2 — 脱敏原文仍可从 `memory.search` 返回（P1，未修）

R35 的 redaction 只改了 `current_text`，**搜索结果载荷仍带 `raw_text`**。

```ini
query='[REDACTED]' -> raw_text='private words'  current_text='[REDACTED]'
经真实 Core 命令: core hit: raw='private words' current='[REDACTED]'
-> GAP CONFIRMED: the Core returns the pre-redaction text to the caller
```

- `recall.py:109` 的 SELECT 列清单包含 `e.raw_text`；
- `runtime.py:773` 把 `hits` 原样放进 `data`；
- 前端 Memory UI 用 `item.raw_text` 渲染「原始事实 (只读)」。

**后果**：脱敏**没有达到目的**——被标记脱敏的原文仍可经 UI 和任何命令调用方读到。
这使 R35 的发现 4 修复**只完成了一半**：数据层面有了脱敏 revision，但投递层面照旧泄露。

**修法建议**：区分「内部读」（需要 raw 做审计/溯源）与「对外读」（UI/命令）。
对外路径必须**省略** `raw_text` 或返回占位符；若确需展示原始事实，须有独立授权与审计，
且**默认关闭**。RED 必须断言 `memory.search` 的返回载荷**不含**脱敏前的文本。

### F3 — 旧记录的后到脱敏标记仍可能漏掉（P1，部分修）

R35 让去重分支处理 redaction 标记，但**请求本身从 checkpoint 时间开始**：

```ini
request start_time = ['1970-01-01T00:00:05+00:00']   # = watermark
current_text after page = 'old private'
-> GAP CONFIRMED: the old record is never re-fetched, so its redaction is missed
```

- `worker.py:58` 用 watermark 作为 `start_time`；
- 若 Screenpipe 按该参数过滤（探针按此行为建模），早于 watermark 的旧记录**根本不会返回**，
  于是 `worker.py:92` 的 redaction 分支永远不会被触发。

**这是「修复依赖一个未被保证的前提」**：R35 的修复假设旧记录会再次出现在页里，但分页语义使它不可能出现。

**修法建议**：redaction 需要一个**独立的扫描路径**（例如按 `external_id` 定期回查，或单独的 redaction 拉取），
不能依赖增量分页。同时须明确：Screenpipe 是否真的按 `start_time` 过滤——若不确定，按**会过滤**设计（fail closed）。

### F4 — 缺失时间戳仍会污染 checkpoint（P1，半修）

R35 修了「**不可解析**」的时间戳（改为 raise），但「**缺失**」的时间戳仍替换为当前时间：

```ini
occurred_at_utc_us=1790334814390911 (delta from now = 0.00s)
-> GAP CONFIRMED: missing timestamp became now

经真实 worker:
watermark after page = 1790334814394425 (was 5,000,000)
earlier valid record stored? False
-> GAP CONFIRMED: the now-timestamp pushed the watermark past the earlier record
```

- `normalize.py:18` 的 `else: occ_us = now` 分支未改；
- 后果与 R34 发现 5a **完全相同**：水位被推到「现在」，较早的有效记录被永久跳过。

**这是我修得不彻底**：只处理了 `except` 分支，漏了同文件同一函数的 `else` 分支——两者是同一个缺陷的两个入口。

**修法建议**：缺失时间戳应与不可解析时间戳**同等对待**（拒绝该记录、不推进 watermark）。

### F5 — Hub 刷新失败仍是假成功（P2，未修）

R35 让读取失败返回 `None`，但**命令仍返回 `accepted`**：

```ini
status='accepted'  data={'type': 'hub.refresh'}  error=None
-> GAP CONFIRMED: an unreadable Hub is reported as a successful refresh
```

- `runtime.py:930` 返回 `accepted`，`_hub_inventory_live()` 的 `None` 只导致 data 里没有 `models` 键；
- `settings.ts:83` 前端判 `accepted || applied` 即视为成功，于是 `hubModels=[]`、`hubError=null`、
  显示「Hub 模型列表已刷新 (0 个)」。

**后果**：Hub 不可达时用户被告知「有 0 个模型」，而不是「读不到」。
这正是我在 R35 注释里写「不能让两种情形看起来一样」、却在返回路径上**又让它们一样**了。

**修法建议**：读取失败必须返回 `rejected` + `HUB_UNAVAILABLE`（或 `degraded`），前端据此显示错误并**保留**上一次的列表。
RED 必须断言失败时 `status != accepted` 且错误码存在。

---

## 2. 可以保留的部分（审查方确认）

- 事务化分页（`append_event(commit=False)`）；
- 同时间戳记录不再被跳过（`<` 替代 `<=`）；
- 部分 saga 路径（3a pin、3b 状态落定、3c profile 前置）；
- 测试隔离修复（`setdefault` → 无条件赋值）。

这些在审查方的只读复核中未发现问题。

---

## 3. 为什么 R35 的 17 项 RED 没有抓到这五处

| 缺口 | R35 的断言实际检查了什么 | 漏掉了什么 |
|---|---|---|
| F1 | `owner_pid.is_none()` 分支存在 | owner **是不是 Hub** |
| F2 | `apply_source_redaction` 把 `current_text` 改成 `[REDACTED]` | 搜索**返回载荷**含什么 |
| F3 | 去重分支里有 `redact` 调用 | 该分支**是否会被触发** |
| F4 | `except` 分支不再用 `now` | `else` 分支仍在用 |
| F5 | `_hub_inventory_live()` 失败返回 `None` | 命令**状态码**是什么 |

**共同点**：断言停在「我改的那一行」，没有走到「用户/调用方最终看到什么」。
这与 R08/R14/R15/Output Mute 四次事故、以及 R33 的 `refresh_hub_inventory()` 无调用点，是**同一个错误**。

**对后续切片的要求**：每项 RED 必须包含至少一条**端到端可观测断言**（命令返回载荷 / UI 状态 / 实际数据），
不能只有「某个内部函数返回值正确」。

---

## 4. 交接（交回实现方）

| 序 | 切片 | 内容 | 依赖 |
|---|---|---|---|
| S1 | F1 进程身份 | Hub 进程识别 + 无法识别时 fail closed | 需先定 Hub 识别依据（文件名/命令行/自报 PID 交叉核对） |
| S2 | F2 投递脱敏 | 对外读路径省略/占位 `raw_text`；内部审计路径独立授权 | 无 |
| S3 | F3 redaction 回查 | 独立扫描路径，不依赖增量分页 | 需确认 Screenpipe `start_time` 语义 |
| S4 | F4 缺失时间戳 | `else` 分支与 `except` 同等对待 | 无（小改动） |
| S5 | F5 刷新失败语义 | 失败返回 rejected + HUB_UNAVAILABLE；前端保留旧列表 | 无（小改动） |

## 4a. 本轮已修（同一会话内）

| 项 | 改动 | 端到端验证 |
|---|---|---|
| **S4** | `normalize.py` 的 `else` 分支（**缺失**时间戳）与 `except` 分支同等对待：拒绝该记录、不推进 watermark | 探针确认 watermark 保持 `5_000_000`，较早的有效记录不再被跳过 |
| **S5** | 新增 `_hub_refresh_result()`：读取失败返回 **`rejected` + `HUB_UNAVAILABLE`**，成功才 `accepted` | 探针确认抛错时 `status != accepted` 且有错误码；成功路径仍返回模型列表 |
| **F2** | `recall.py` 新增 `_withhold_redacted_raw_text()`：三处返回点统一把**脱敏事件**的 `raw_text` 置 `None` 并标 `raw_text_withheld`；原值仍在库中（I06 不可改写），只是不再投递 | 经真实 Core 命令确认搜索载荷不再含脱敏前文本 |

RED：`tests/red_v121/test_red_r36_residual_gaps.py`（6 项；修复前 5 failed，现 **5 passed / 1 failed**）。

**未修 1 项**：`test_an_unidentified_listener_does_not_verify`（F1）—— 见 §4b。

## 4b. 仍需裁决的两项（未修，不自行发明依据）

### F1 — Hub 进程识别依据

修 F1 必须先回答：**凭什么认定一个 PID 是 Hub？** 候选：

1. 可执行文件名/路径包含 `llama.cpp-hub`（`process_manager.rs` 的 `is_port_listening` 已按端口探测，但无身份判定）；
2. 命令行匹配（需读 WMI/`Get-CimInstance`，本机实测**沙箱内被拒绝访问**）；
3. 与 Hub 自报信息交叉核对（`/api/node/info` 返回的 `selfNode`，但那是 Hub 自己的声明，不是 OS 事实）。

**这三条的信任强度不同**，且 1 可被同名进程冒充、2 需要权限、3 是自证。我不替你选。

### F3 — Screenpipe `start_time` 语义

修 F3 必须先确认：**Screenpipe 是否真的按 `start_time` 过滤？**

- 若**会**过滤：旧记录不会再次返回，必须新增独立的 redaction 回查路径（按 `external_id` 定期回查，或单独拉取 redaction 列表）；
- 若**不会**过滤：当前去重分支已足够，只需补一条回归测试锁定该前提。

这是**外部服务语义**，我不凭猜测实现。按项目纪律，未确认前应按「会过滤」设计（fail closed），
但那会引入一条新路径，属设计决策，需你确认。

---

## 4c. 原交接表（保留）

| 序 | 切片 | 内容 | 状态 |
|---|---|---|---|
| S1 | F1 进程身份 | Hub 进程识别 + 无法识别时 fail closed | **待裁决依据** |
| S2 | F2 投递脱敏 | 对外读路径省略 `raw_text` | **已修** |
| S3 | F3 redaction 回查 | 独立扫描路径，不依赖增量分页 | **待裁决语义** |
| S4 | F4 缺失时间戳 | `else` 分支与 `except` 同等对待 | **已修** |
| S5 | F5 刷新失败语义 | 失败返回 rejected + HUB_UNAVAILABLE | **已修** |

每片仍按纪律：**先写 RED（含端到端可观测断言）→ 最小修复 → 行为回归**。

---

## 5. 验证口径（本文件所用）

- 本文件所有复现由 **Codex** 执行，均为内存数据库 / 假客户端探针，**未调用真实 Hub**；
- 审查方的口径：`red_v121` 377/377、针对性 24/24（只读复核，未改产品树）；
- **Rust 75 项、九组总门禁、真实 Hub/硬件门禁本轮未由审查方独立重跑**——
  R35 报告中的通过数**不得**冒称为审查方的验收结果；
- 本文件未修改任何产品代码。

# R37 HANDOFF — F1/F3 裁决与 F3 字段级缺口（2026-09-25）

- 性质：**交接文档**。本文件不改产品代码，把裁决整理成可执行切片交给实现方（DeepSeek）。
- 基线：`f758eaf4` + 脏工作树（3 项修改：`runtime.py`/`recall.py`/`normalize.py`）
- 来源：用户裁决（本轮只读，未修改产品代码）+ Codex 独立复现
- 前置：`docs/R36-R35-REVERIFICATION-2026-09-25.md`（R35 撤回与五处缺口）

> **不得以新增函数名或测试总数宣布 R36/R37 GREEN。**
> 若来源能力或 Hub 身份锚点无法证明，**保持相应门禁关闭并报告限制**。

---

## 0. 裁决要点

| 项 | 裁决 |
|---|---|
| **F1 进程身份** | 不能按现状关闭，**也不得在候选方案中单选一个充当证明**。必须先建立**独立身份锚点**，再做端口关联。 |
| **F3 `start_time`** | **按过滤器处理**（Screenpipe 官方文档列为 *Filter start*）。不得以「也许不过滤」放行旧记录回查。另建**有证据的对账路径**。 |
| F3 补充 | 独立复核发现三处**必须先补的直接缺口**（见 §3），其中一处使 redaction 分支**端到端不可达**。 |
| 新增原则 | **「listener 枚举完整性」**与**「删除不能由缺席推断」**纳入本次裁决。 |

---

## 1. F1 — 先有独立身份锚点，再做端口关联

### 现状（Codex 核实）

- `service_registry.rs:90` `ServiceRegistry::observe()` 启动时只登记 `lva_core`（`lib.rs:525` 起），
  **没有任何已识别的 Hub 进程可供比较**；
- `network_attestation.rs:139` `let owner = bound.iter().find_map(|row| row.owning_process)` ——
  取的是「该端口**任意一个** listener 的 PID」，**不是「全部 owner 是否一致」**，也不比对身份；
 - `network_attestation.rs:89` `parse_listener_table` 有**两类不同的丢弃**，负向测试必须分别覆盖：
   1. **行格式/地址/端口不可解析** → `continue`，该行**从结果里消失**（`fields.len() < 5`、
      协议非 `tcp`/`tcpv6`、状态非 `LISTENING`、`split_host_port` 失败）；
   2. **PID 不可解析** → **保留该行**，`owning_process` 为 `None`（`fields[4].parse::<u32>().ok()`）。
 
   因此枚举完整性有两个独立风险面：**行消失**（第 1 类）与 **owner 缺失**（第 2 类）。
   后者影响 §1 的交叉核对——`find_map(|row| row.owning_process)` 在多行中取第一个非 `None`，
   若其中一行 PID 缺失，该行**不参与**核对却也不报错。

### 裁决要求的实现方向

1. **身份锚点**：允许使用**经用户明确确认的 Hub 实例/安装身份**；
2. **交叉核对**：用 **OS 取得的进程实例信息**与控制端口**所有 IPv4/IPv6 listener 的 owner** 交叉核对；
3. **API 自报只作旁证**（`/api/node/info` 是 Hub 自己的声明，不是 OS 事实）；
4. **不得单凭 `java.exe`** 证明所运行的是 Hub 程序（`QueryFullProcessImageNameW` 只给出可执行文件路径）。

### 必须 fail closed 的情形（一律 `UNVERIFIED_BIND`）

- 身份无法取得；
- owner 不一致（同一端口有多个不同 owner）；
- 枚举不完整（存在无法解析 PID 的 listener 行）；
- 实例变化（PID 复用 / 重启）。

**流程要求**：先**撤销旧裁决**再重验——不能沿用上一次的 VERIFIED。

### 硬约束

**绝不把观测到的 PID 变成 kill 权限**（计划 L656 门禁；I04：只终止 Spawned 子进程）。

### Windows 原生接口（裁决引用）

- `GetExtendedTcpTable`（读取 listener 与 owner PID）：https://learn.microsoft.com/windows/win32/api/iphlpapi/nf-iphlpapi-getextendedtcptable
- `QueryFullProcessImageNameW`（进程映像路径）：https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-queryfullprocessimagenamew

### 现有 F1 RED 的问题

`tests/red_v121/test_red_r36_residual_gaps.py::test_an_unidentified_listener_does_not_verify`
**只搜索函数名**（`is_hub_process` / `identify_hub` / ...）。裁决明确要求替换为**行为测试**：

1. **异进程占端口**：一个非 Hub 的 loopback 进程占住该端口 → 不得 `VERIFIED_LOOPBACK`；
2. **多 owner**：同一端口出现两个不同 owner → 不得 VERIFIED；
3. **不可解析 listener**：存在无法解析 PID 的行 → 不得 VERIFIED（枚举完整性）；
4. **PID 复用**：实例 token 变化后旧裁决立即失效；
5. **真实 Hub**：对真实运行中的 Hub 做一次正向验证（需 GUI/实机）。

---

## 2. F3 — `start_time` 按过滤器处理，另建有证据的对账路径

### 裁决

- Screenpipe 官方文档明确把 `start_time` 列为 **Filter start**，因此**不能**以「也许不过滤」放行；
- 该文档**不是实机能力验收**，项目**尚未锁定实际运行版本**；
- **增量导入**与**历史脱敏对账**必须**分开**；
- 先探测并固定实际来源的：**版本**、**稳定 ID**、**脱敏标记**、**删除通知**、**分页行为**；
- **找不到可靠删除通知时**：不得把「搜索结果里消失了」当作删除证明，也不得宣称删除同步已完成。

### 新增原则

**「删除不能由缺席推断」**——缺失≠已删除。这是裁决明确纳入的原则。

---

## 3. F3 三处字段级缺口（Codex 独立复现，全部确认）

### F3-a — 脱敏标记写在 `provenance`，worker 读顶层 → 分支**永不触发**

```ini
normalized['redacted']                = None   <-- worker reads THIS
normalized['provenance']['redacted']  = True   <-- normalizer writes THIS
transcription = '[REDACTED]'
-> GAP CONFIRMED: the worker branch can never fire
```

- `normalize.py:47` 起：`is_redacted` 被写进 `provenance`（`normalize.py:72` 的 `"redacted": is_redacted`），
  顶层**没有**该键；
- `worker.py:98` 读 `normalized.get("redacted")` → 恒为 `None` → `apply_source_redaction` 永不调用。

**端到端复现**：即使记录带稳定 ID 与 redaction 标记再次返回，`current_text` 仍为原文：

```ini
current_text after the marked record = 'the original words'
-> GAP CONFIRMED: the mark is ignored, so the old text stays
```

**这是 R35 修复的根本失效点**：我写了 `apply_source_redaction()` 并让 worker 调用它，
但调用条件依赖一个**从未被填充的键**——与 R33 的 `refresh_hub_inventory()` 无调用点同型。

### F3-b — 无来源 ID 时 `external_id` 由转写文本生成 → 脱敏前后 ID 不同

```ini
before redaction: external_id='audio_5000000_998ce1d535f0' raw='the original words'
after  redaction: external_id='audio_5000000_e54b74eb9192' raw='[REDACTED]'
-> GAP CONFIRMED: the id changes with the text, so the two cannot be reconciled
```

`normalize.py:57` 起：无 `raw_id` 时 `external_id = f"audio_{occ_us}_{sha256(transcription)[:12]}"`。
脱敏后转写变成 `[REDACTED]`，哈希随之改变 → **同一记录的两个版本无法对账**。

**要求**：`external_id` 必须来自**来源稳定 ID**；来源不提供时，须有明确策略（例如记录「无稳定 ID」并**拒绝**参与对账，而不是伪造一个会变的 ID）。

### F3-c — 只取一页（`offset=0`），并按页内最大时间推进 checkpoint

```ini
calls client.search(...) once?          True
passes an offset?                       True
advances checkpoint from page max?      True
-> a second page is never fetched, so 'page max' is not 'source max'
```

- `worker.py:52` 起 `import_page()` 只调一次 `self.client.search(limit=limit, start_time=...)`，
  `client.search` 默认 `offset=0`；
- 随后按**页内最大时间戳**推进 watermark；
 - 在**未证明排序与分页语义前**，这不能算完整导入。

 **降序（newest-first）来源的机理（已实测，200 条记录 / 页大小 50）**：

 ```ini
 page 1 imported 50 records; watermark = 1790294400000000
 newest record ts   = 1790294400000000  (watermark == newest? True)
 client calls       = [(50, 0, None)]
 total events stored= 50 / 200
 page 2 imported 0 records; total stored = 50 / 200
 -> GAP CONFIRMED: only the newest page is imported; the other 150 are permanently unreachable
 ```

 第一页的**最大**时间即**最新**记录的时间；把 watermark 推到它之后，下一次请求的 `start_time`
 恰好排除了**所有更早的记录**，于是第 2 页起全部落空——150 条记录**永久不可达**。

 升序（oldest-first）来源下结论同样成立但机理不同：页内最大时间是该页最旧记录，
 推进后**同一页剩余记录**（若有）会被 `start_time` 排除。

 **两种排序都必须有 RED**，且断言「多页全部导入」而非「页内无重复」。

---

## 4. 交接切片（连续，交回 DeepSeek）

裁决给定的顺序：**先补 F3 字段、稳定 ID 和分页的真实 worker RED**；
确认实际 Screenpipe 能提供何种历史标记/删除信号，**再**实现对账；
并按 §1 门禁建立可信身份来源与行为测试。

| 序 | 切片 | 内容 | 前置 |
|---|---|---|---|
| **S1** | F3-a 字段对齐 | 统一 redaction 标记的读写位置（顶层与 provenance 二选一，或两处都读）；RED 必须走真实 worker 且断言 `current_text` 变化 | 无 |
| **S2** | F3-b 稳定 ID | `external_id` 只用来源稳定 ID；无稳定 ID 时的策略须显式（记录并拒绝参与对账） | 无 |
 | **S3** | F3-c 分页语义 | 多页 / 降序 / 升序的 RED 与**不依赖实机的修复**（分页循环、按来源排序方向推进游标）。RED 必须断言「多页全部导入」 | **无**（实机只约束 S4 兼容性验收） |
| **S4** | 来源能力探测 | 固定：版本、稳定 ID、脱敏标记、删除通知、分页行为；产出证据文档 | 需实机 Screenpipe |
| **S5** | 历史脱敏对账 | 独立于增量导入的对账路径；**删除不得由缺席推断**；无删除通知时报告限制 | S3/S4 |
 | **S6** | F1 身份锚点 | 用户确认的 Hub 实例身份 + OS 进程实例信息 + 控制端口**所有** listener owner 交叉核对；API 自报仅旁证。**实机取得证据由执行方负责** | 需所有者确认 Hub 实例选择 |
 | **S7** | F1 负向 fail-closed 行为测试 | 替换现有「搜函数名」的 RED：异进程占端口、多 owner、行消失（格式/地址/端口不可解析）、owner 缺失（PID 不可解析）、PID 复用。**这些用构造的 listener 表即可完成，不依赖实机** | **无** |
 | **S8** | fail-closed 与撤销 | 身份不可得/owner 不一致/枚举不完整/实例变化 → `UNVERIFIED_BIND`；先撤销旧裁决再重验 | S6/S7 |

**S7 与 S1–S3 可立即开始**：它们用构造的 listener 表与假客户端即可完成，不受实机能力约束。
实机约束只作用于 **S4（来源兼容性验收）** 与 **S6（真实 Hub 进程身份）**——
执行方应从实机取得证据；取不到就**保持对应门禁关闭**，但**不让其余切片停摆**。

### 每片纪律

1. **先写 RED，且必须走真实入口**（worker / 命令 → dispatcher → 真实调用链）；
2. RED 必须含**端到端可观测断言**（数据结果 / 命令载荷 / UI 状态），不能只有内部函数返回值；
3. 不得以「测试总数增加」或「新增函数名」作为完成证据；
4. 每片出 `docs/R<NN>-EXECUTION-REPORT-*.md`，引用计划行号与逐字条文；
5. **不得提交**（硬约束 1，需用户显式授权）。

---

## 5. 门禁状态（当前，不得自行宣布通过）

| 门禁 | 状态 |
|---|---|
| F1 进程身份 | **关闭**（无独立身份锚点） |
| F3 历史脱敏对账 | **关闭**（字段不对齐 + 无稳定 ID + 分页语义未证） |
| F3 增量导入 | **部分**（事务、同刻记录已修；分页与排序语义未证） |
| R36 总体 | **不得宣布 GREEN** |

### 本轮未由审查方重跑的项

- 全量门禁（九组）；
- Rust 单测；
- 真实 Hub / 真实声卡 / 真实 GUI。

审查方本轮口径：**R36 目标测试 5 passed / 1 failed**（未重跑全量）。

---

## 6. 本文件性质

 ### 撰写归属

 - 本文件由**实现方执行位（Codex，本会话）**撰写，属**交接文档**，不是执行报告，也不是验收裁决；
 - **审查方（独立会话）未撰写本文件**，也未执行本文列出的全部探针；
 - 审查方对本文件的贡献是**只读核对**：指出 §1 与 §3 F3-c 两处机理错误（本文件已勘误），
   并给出 F1/F3 的验收标准。审查方本轮未修改代码、未重跑全量门禁。
 - 项目保持**审查方与实现方证据分离**：审查方口径与实现方运行结果分别列明，不混同。

 ### 复现归属

 - §3 的 F3-a/b/c 与端到端不可达，由**实现方执行位（Codex，本会话）**独立复现
   （内存 Journal / 假客户端探针，未调用真实 Screenpipe）；
 - §3 F3-c 的**降序 200 条 / 50 条**实测数据同样由实现方执行位运行；
 - 审查方**未执行**上述探针；审查方独立重跑的是 R36 目标测试（5 passed / 1 failed）；
 - §1/§2 的裁决内容来自**用户裁决**，实现方未自行选择身份锚点或来源语义。
- **未修改任何产品代码**；未使用 Astra；未执行任何 git 写操作。

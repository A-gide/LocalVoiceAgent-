# R34 HANDOFF — Independent Review Findings (2026-09-25)

- 基线：HEAD `25de1875` + 未提交工作树（检查期间工作树 23 → 38 项）
- 来源：独立审查方（非实现方）的复现输入，**未修改产品代码，未使用 Astra**
- 性质：**交接文档**。本文件不改产品代码，只把已复现的缺陷整理成可执行切片交给实现方（DeepSeek）。
- 验证口径：v1.2 七组 106/106、RED 套件 357/357、相关 Hub 测试 24/24；下列反例来自**另行执行**的独立探针。

> **绿色测试不覆盖这些反例。** 审查方结论：本轮不能判为完整验收通过。

---

## 0. 复核结论（Codex 独立复现）

审查方提出 6 项。我在 `25de1875` + 工作树上**逐项独立复现**，全部成立：

| # | 发现 | 复现结果 | 状态 |
|---|---|---|---|
| 1 | Hub 放行凭证可从渲染层提交 | `send_core_command` 原样转发 → `hub.attest_bind` 未区分来源 | **确认** |
| 2 | bind 证明未绑定到实际 Hub | listener owner 被丢弃 + 固定探测 8080 | **确认** |
| 3 | 模型切换三处行为缺口 | 3a/3b/3c 全部复现（见 §3） | **确认** |
| 4 | Screenpipe 后续 redaction 不清原文 | watermark 先于去重/更新判断 | **确认** |
| 5 | checkpoint 可丢记录、页事务未成立 | 时间戳兜底 + `<=` 比较 + `append_event` 自行提交 | **确认** |
| 6 | PR-026 接线缺口（进行中） | `hub.refresh` 返回缓存，`refresh_hub_inventory()` 无生产调用点 | **确认（本轮引入）** |

发现 6 是**我在 R33 引入的缺陷**：我新增了 `refresh_hub_inventory()` 并为其写了测试，但 refresh 分支读的是 saga 缓存，
而没有任何生产代码去填充该缓存——我犯了与本轮所修三处缺陷（契约存在、生产者缺失）完全同型的错误。
这印证了审查方基线检查项③（命令→分发→真实调用链追踪）的必要性：我的测试直接调用 `refresh_hub_inventory()`，
因此**绕过了真实入口**，与 R08/R14/R15/Output Mute 四次事故的掩盖方式一致。

---

## 1. P1 — Hub 放行凭证可从渲染层提交

### 事实

- `apps/desktop-shell/src-tauri/src/lib.rs:328` `send_core_command` 把 WebView 传来的 JSON **原样**转发给 Core；
- `src/lva/core/runtime.py:805` `hub.attest_bind` 分支只做 `set_hub_bind_attestation(payload.attestation)`，
  **不校验该证明来自 Rust 观测**；
- `send_core_command` 在 Tauri 命令表内，渲染层可调用。

### 复现

构造一份带未来 `revalidate_after` 的 `VERIFIED_LOOPBACK` 并经该命令提交，`hub_control_allowed()` 由 `False` 变 `True`。

### 影响范围（不夸大）

需要**渲染层代码执行能力**。这不是「无需前提的远程攻击」，但它使「Rust 是进程权威」的设计声明失去技术保障：
证明的**来源**没有被验证，只有其**形状**被验证。任何能影响渲染层内容的手段（XSS、被篡改的前端资源、
恶意插件）都能开出 Hub 控制门，进而 load/stop/switch 模型。

### 计划依据

- L1256：`G 只消费 B 提供的 typed attestation`——B 是**进程权威**，不是渲染层；
- L659（审查方引用）：进程关联与重连重验要求。

### 建议修法（需实现方验证）

1. `hub.attest_bind` 必须**仅**接受来自 Rust 进程内通道的提交，而不是通用命令面；
2. 可选实现路径：Core 侧只接受带**进程内共享秘密**（启动时经 bootstrap stdin 下发、WebView 不可得）的证明；
   或 Rust 侧把 `hub.attest_bind` 从 `send_core_command` 的可达命令集中移除，改由桥接层专用方法转发并加来源标记；
3. 无论选哪条，RED 必须断言：**经渲染层命令面提交的 attestation 不能改变 `hub_control_allowed()`**。

---

## 2. P1 — bind 证明没有绑定到实际 Hub

### 事实

- `lib.rs:164` `attest_for_port(&rows, HUB_CONTROL_PORT, &attestation_id).0`——`attest_for_port` 的第二个返回值
  （listener owner PID）被 `.0` **丢弃**；
- `lib.rs:175` `HUB_CONTROL_PORT: u16 = 8080` 是 Rust 侧常量；
- `src/lva/config.py:51` `HUB_PORT = int(os.environ.get("LVA_HUB_PORT", "8080"))` **可配置**。

### 复现与影响

非默认端口时，Rust 探测 8080（可能是别的服务）而 Core 连另一个端口——**证明与目标可以完全不对应**。
8080 被其他进程占用时，attestation 会为**错误的进程**签发 `VERIFIED_LOOPBACK`。
Hub 重启后旧证明也不会被立即撤销，只靠 30 秒周期报告更新（`REATTEST_INTERVAL`），期间窗口内旧证明仍有效。

### 计划依据

L1213（PR-008 Steps）：`listener table、control-port↔Hub process 关联、typed bind attestation`——
**进程关联是明文要求**，当前实现只做了 listener table 与 typed attestation，中间的关联被丢弃。

### 建议修法

1. 保留 `attest_for_port` 的 owner 返回值，并把它**纳入证明**（或至少在 Rust 侧核对 owner 与 Hub 进程身份一致）；
2. Rust 的探测端口必须与 Core 的 `HUB_PORT` **同源**（经 bootstrap 下发，或由 Rust 从同一配置读取），
   不能各持一个常量——这与 R25 修掉的「Hub 端口 6 处副本」是同一类双源缺陷；
3. Hub 重启/端口变化时**立即撤销**旧证明（不能等下一个周期）。

---

## 3. P1 — 模型切换三处行为缺口

三项均以假客户端独立复现（无真实 Hub 调用）。

### 3a — 早返回不 pin 推理端

`hub_runtime.py:232` 附近：目标是**已加载**模型时，分支设 `active_model_id` 后直接 `return`，
**未调用 `self.inference.bind_model(...)`**（该调用只在完整加载路径的 COMMIT 步骤存在）。

```ini
binding.active  = new-model
inference.bound = old-model      <-- 不一致
VERDICT: GAP CONFIRMED
```

后果：绑定显示新模型，但推理请求仍带旧模型的 `X-LVA-Bound-Model` 头——正是该模块文档声称要防的
「切换后静默从旧模型回答」。

### 3b — 验证异常后状态卡在 `verifying`

`hub_runtime.py:293` 附近：`_verify_target()` 抛异常（超时）时**没有 try/except**，异常直接向上传播，
`binding.status` 停在 `verifying`，且**未记录前一 binding**。

```ini
raised: RuntimeError: Verification timed out
status           = verifying     <-- 不是 failed/degraded
previous_binding = None          <-- 无回滚依据
VERDICT: GAP CONFIRMED
```

后果：违反计划 L636（任一步失败 → `FAILED/DEGRADED`，且旧 turn 不可复活；重绑需**显式 rollback**）。
`verifying` 是既非成功也非失败的悬挂态，UI 会永远显示「验证中」。

### 3c — 先停旧模型，再发现目标 profile 缺失

`hub_runtime.py:244` 附近：STOP 旧模型（第 2 步）发生在 `get_profile(target)`（第 3 步）**之前**。
目标 profile 缺失时，旧模型已被停掉，而绑定回滚为 `active=old-model, status=failed`——
**声称的 active 与实际运行的模型不一致**（旧模型已死）。

```ini
stop_model(old-model) called
raised: RuntimeError: Model profile not found for target
status = failed, active = old-model    <-- 该模型已被停止
```

**正确顺序**：profile 可获取性应在 STOP 之前校验（计划 §5.4 步骤 2-4 的顺序就是先读 profile 再 POST load）。

### 共同要求

这三项**不能由「已有模型切换测试通过」代替**。现有测试直接调用 `switch_model()` 或只做源码级断言，
未覆盖上述分支。新 RED 必须走**真实入口**（`hub.bind_model` 命令 → dispatcher → saga）。

---

## 4. P1 — Screenpipe 后续 redaction 不会清除 Journal 原文

### 事实

`src/lva/screenpipe_importer/worker.py:79` 的 watermark 判断（`if occ_us <= watermark: continue`）
**先于**去重查询与更新逻辑；`normalize.py:37` 虽把 redaction 标记映射为 `[REDACTED]` 文本，
但**已入库的事件不会被更新**。

### 复现

同一 `external_id` 的记录，第二次带 `redacted` 标记返回时，Journal 中仍是原文 `private words`。

### 计划依据

L896（审查方引用）：source redaction 处理要求。

### 建议修法

1. watermark 跳过逻辑必须**允许**已入库记录的 redaction 更新（redaction 是更新，不是新事件）；
2. 更新须走 Journal 的修订机制（`current_revision` 递增），**不得**改写 `raw_text`（I06：raw 不可变）；
3. RED 必须断言：带 redaction 标记的重复记录使 `current_text` 变为脱敏值，而 `raw_text` 保持不变。

---

## 5. P1/P2 — 导入 checkpoint 可丢记录，整页事务未成立

### 5a — 无效时间戳被替换为当前时间

`normalize.py:26` `except Exception: occ_us = int(datetime.now(...))`：无法解析的时间戳被**静默替换为当前时间**。
该值随后推进 watermark，导致**较早的合法记录被永久跳过**。

### 5b — 与 watermark 相同的时间戳被跳过

`worker.py:79` `if occ_us <= watermark: continue` 使用 `<=`。同一微秒内的多条记录只有第一条会入库，
其余被静默丢弃。

### 5c — 整页事务未成立

`worker.py:72` 的外层 `with self.repo.conn:` 调用了 `repository.py:120` 的 `append_event()`，
而后者**自己也有 `with self.conn:`**。SQLite 中内层 `with` 会**提交**外层事务，因此外层不再是原子边界。

```ini
第二条记录非法时实测: events=1, watermark=0
期望: 整页回滚 -> events=0
```

### 建议修法

1. `append_event` 需要**不自行提交**的变体（或接受调用方事务），供批量导入使用；
2. 时间戳不可解析时必须**报错或跳过该条**，绝不能替换为当前时间并推进 watermark；
3. watermark 比较改 `<=` 为 `<`，或用 `(timestamp, external_id)` 复合游标消除同刻歧义；
4. RED 必须断言：页内任一条非法 → `events=0` 且 `watermark` 不变。

---

## 6. PR-026 接线缺口（本轮引入，须随该切片一起核验）

### 事实

- `src/lva/core/runtime.py:841` refresh 分支返回 `self._hub_inventory_result()`，读的是 **saga 缓存**；
- `src/lva/core/runtime.py:325` `refresh_hub_inventory()`（真正读 Hub 的方法）**无生产调用点**——
  全仓仅测试调用（`test_red_hub_inventory_and_force.py:154/193`）。

### 复现

```ini
refresh -> status=accepted models=[]
control.list_models ever called? False
VERDICT: GAP CONFIRMED - refresh returns cache, nothing populates it
```

### 后果

PR-026 的「刷新」按钮在真实运行中**永远返回空列表**——UI 看起来工作，实际什么都没读。
这正是计划 L1458 与 I21 想要避免的「UI 显示与真实状态不符」。

### 建议修法

1. refresh 必须**实际触发** `refresh_hub_inventory()` 并把结果返回；
2. 由于 dispatcher 是同步的而客户端是异步的，实现方式需与 `_schedule_hub_saga` 同形（调度 + 结果回填），
   或让 `hub.refresh` 走与 bind 相同的调度路径并在完成时发布事件/更新可读状态；
3. RED 必须走**真实入口**：发 `hub.refresh` 命令，断言 `control.list_models()` **确实被调用**且结果出现在返回值中。
   （现有测试直接调用 `refresh_hub_inventory()`，因此绕过了真实入口。）

---

## 7. 验证口径与未闭环项（不得被上述修复掩盖）

### 审查方本轮的通过口径

| 项 | 结果 |
|---|---|
| v1.2 七组 | **106/106** |
| RED 套件（本轮末） | **357/357** |
| 相关 Hub 测试 | **24/24** |

注：审查方观察到早一次 RED 运行有 8 个失败，原因是**并行编写中的 UI 文件**尚不完整；文件到位后定向与全套件均通过。
该瞬时失败**不作为**稳定回归。

### 仍未执行（R32 快照 L255 已列明，本轮同样未做）

- 真实 Hub load/stop/switch；
- Rust reporter 真实送达；
- Hub 重启后重新 attest；
- 真实声卡（Output Mute 物理静音）；
- 真实 Tauri GUI（capability 运行时、窗口几何、Live2D 渲染、多显示器）。

---

## 8. 交接建议（审查方给定顺序）

> 建议把上述复现输入交给 DeepSeek，**先封住 Hub 授权来源与模型切换**，再修 Journal 的隐私及 checkpoint 问题；
之后在**固定工作树**上重跑相应门禁。

据此的切片顺序：

| 序 | 切片 | 内容 | 前置 |
|---|---|---|---|
| S1 | Hub 授权来源 | §1 凭证来源 + §2 进程关联与端口同源 | 无 |
| S2 | 模型切换 | §3a/3b/3c + §6 refresh 接线 | S1（同属 Hub 面） |
| S3 | Journal 隐私 | §4 redaction 更新 | 无（可与 S1/S2 并行开发，按 contract 串行合并） |
| S4 | Journal checkpoint | §5a/5b/5c 事务与游标 | S3（同文件） |
| S5 | 门禁重跑 | 在固定工作树上重跑 v12 七组 + RED + Hub 24 项 + Rust + 前端 | S1–S4 |

每片仍按项目纪律：**先写 RED（走真实入口）→ 最小修复 → 出 `docs/R<NN>-EXECUTION-REPORT-*.md`**。

### 特别提醒实现方

1. **不要只加源码级断言**。本轮 6 项中有 4 项是「测试绕过了真实调用路径」才存活下来的：
   新增 RED 必须经真实入口（命令 → dispatcher → 真实调用链）；
2. **不要删除或改写本文件**（交接记录），修复完成在新报告中说明；
3. **不要提交**（硬约束 1，需用户显式授权）；
4. 修改 `lib.rs` / `runtime.py` 时注意既有 RED 的源码级断言（如 `test_red_hub_dispatch_wiring.py`），
   若新设计与旧断言冲突，**先判定哪个更符合计划条文**并在报告中说明，不得静默改断言。

---

## 9. 本文件的性质声明

- 本文件由 **Codex** 撰写，属**交接文档**，不是执行报告，也不是验收裁决；
- 所有 6 项均经 Codex **独立复现**（假客户端/内存数据库探针，未调用真实 Hub）；
- **未修改任何产品代码**；工作树保持检查时的状态；
- 未使用 Astra；未执行任何 git 写操作。


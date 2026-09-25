# R26 执行报告 — PR-020 隐私捕获协调器（ack 驱动）

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「完成后开始下一片」；冻结计划 L1330-1338（PR-020）

---

## 1. 计划条文与开工前的实际状态

### 1.1 权威条文（逐字核验）

| 行 | 内容 |
|---|---|
| L1332 | Branch / owner: `core/privacy-coordinator` / C |
| L1333 | Current → target: **只停 Core mic 就宣称隐私暂停 → acknowledgement-driven privacy scope** |
| L1334 | Files/new: `core/capture.py`；修改 RuntimeState/command handlers |
| L1335 | Steps: Core mic stop ack；**Standby/Privacy Pause 均发 managed-capture-off operation**；聚合 verified/unverified；restore_mode memory-only；**Live 根据 `record_reality_during_live` 发 intent** |
| L1336 | Dependencies: PR-009/006；可与 PR-021 并行开发，按 contract 串行合并 |
| L1337 | Tests: I09/I10/I19；**Core mic 物理帧停止**；Standby 的 LVA-managed capture 为 Off；**timeout 时 scope=unknown 而非 success** |
| L1338 | Rollback: **不允许回到虚假 success**；外部控制失效时降级为 Core-only + 明示 unverified |

§3.3 的模式表（L308-313）与 §3.4 的四个合法 scope 值（L327-332）是配套权威。

### 1.2 开工前的实际状态（逐项核对，非推测）

`tests/red_v121/test_red_capture.py` 的 7 项当时**已经全绿**——但绿的是表面。逐行读源码后确认：

| 计划要求 | 开工前实况 | 判定 |
|---|---|---|
| Core mic stop ack | `stop_core_mic()` 只把 `self.core_mic_stopped = True`，**从不驱动真实设备**；回调异常也不处理 | ✗ |
| Standby 发 managed-capture-off operation | 调用了 `request_managed_capture_off()`，但该方法**只是把标志置 True**，没有 operation id、没有 deadline、没有 ack 通道 | ✗ |
| Privacy Pause 发 managed-capture-off operation | 只调 `update_managed_capture_status(managed_stopped=None)`——**根本没向任何人发请求** | ✗ |
| 聚合 verified/unverified | `compute_privacy_scope` 只看两个布尔值，无「已请求但未应答」这个状态 | ✗ |
| restore_mode memory-only | 已实现（`_resume_mode`，不持久化） | ✓ |
| Live 按 `record_reality_during_live` 发 intent | `record_reality_during_live` 字段存在但**从未被读取**；进入 Live 时也不发任何 intent | ✗ |
| timeout → unknown | 无超时概念 | ✗ |
| `privacy.scope_changed` 事件 | 契约里有类型（`events.py` L30），**全库零生产者** | ✗ |

**结论**：既有 RED 覆盖的是「字段存在」与「纯函数分类」，没有覆盖「请求→应答→超时」这条链。这正是三次同型事故（8089 / version 信封 / saga 死路）的同一模式——**测试绕过了真实调用路径**。

---

## 2. 实现

### 2.1 `core/capture.py`：引入 operation 概念

新增 `CaptureOperation`（`@dataclass`）：

```python
@dataclass
class CaptureOperation:
    operation_id: str      # "cap-<n>"，用于关联 ack
    kind: OperationKind    # "stop" | "resume"
    requested_at: datetime
    deadline: datetime     # requested_at + ack_timeout
    status: OperationStatus = "pending"   # pending | acknowledged | timed_out
```

**为什么必须是 operation 而不是布尔标志**：布尔值无法表达「已请求但尚未应答」，而**那正是必须拒绝 verified 的状态**（L1337）。这是本片的核心设计判断。

`CaptureCoordinator` 从手写 `__init__` 改为 `@dataclass`，注入 `now`（可测试时钟）与 `ack_timeout`（默认 5s，模块常量 `CAPTURE_ACK_TIMEOUT`）。

新增/变更 API：

| 方法 | 语义 |
|---|---|
| `request_managed_capture_off(*, track=True)` | 发 stop 操作。`track=False` **仅供启动假设**：那时还没有被 spawn 的实例，无人可应答，也就没有 operation 可关联 |
| `request_managed_capture_on()` | 发 resume 操作（Passive / Live） |
| `acknowledge(operation_id, managed_stopped=None, external_detected=None)` | 结算指定操作；未知 id 或已结算 → 返回 `False` |
| `expire_overdue(now=None)` | 未应答的操作置 `timed_out`；stop 超时会把 `managed_screenpipe_stopped` **丢弃为 `None`**（不是保留旧值） |
| `pending_operations()` / `unsettled_stop_operations()` / `last_operation()` | 自省 |
| `unverified_reasons(mode)` | 逐条列出未验证原因（供事件负载） |

### 2.2 三处「拒绝虚假 success」的实现细节

1. **`stop_core_mic()` 按结果而非意图设标志**（L1338）：回调抛异常时 `core_mic_stopped = False` 并返回——设备没关掉就不能报「已停」。对应 `test_failed_physical_stop_does_not_report_stopped`。
2. **未结算的 stop 操作永远压在 verified 之下**：`compute_privacy_scope` 首判 `unsettled_stop_operations()`，命中即返回 `UNKNOWN`。对应 `test_verified_requires_the_stop_operation_to_be_settled`（缓存的 `stopped=True` 标志不能压过新发的未应答请求）。
3. **超时在读取时求值**：`compute_privacy_scope` 读之前先跑一次 `expire_overdue()`。理由——生产里没有任何外部 ticker 会来调用过期检查，如果只在显式 tick 时过期，一个从未应答的请求会**永远停在 pending**，而 pending 恰好也返回 UNKNOWN（结论相同），但 operation 状态会是错的。让读取即求值使两者一致。

### 2.3 `core/runtime.py`：intent 与事件接线

| 变更 | 说明 |
|---|---|
| 构造新增 `capture_now` 参数 | 把可测试时钟传进协调器；生产不传，走真实 UTC |
| 启动假设改 `track=False` | 启动时没有任何 LVA-managed 实例存在，发一个无人能应答的 operation 是错的 |
| Privacy Pause：`update_managed_capture_status(managed_stopped=None)` → `request_managed_capture_off()` | **本片最实质的一处**：原先只是记录「不知道」，从不请求任何人停止 |
| Standby 重复进入 | 补 `previous_scope` 计算，使重复进入只在 scope 真的变化时才发事件 |
| Passive / Live | Passive 恒发 resume（§3.3：进入该模式**即为**录制动作）；Live 按 `record_reality_during_live` 分流 |
| 新增 `_publish_privacy_scope(previous_scope)` | 单一发布点，使事件与 `RuntimeState.privacy_scope` 不可能漂移 |
| 新增 `acknowledge_capture_operation(...)` | ack 入口；未匹配到未结算操作时返回 `False` 且**不动 scope** |
| 新增 `expire_capture_operations()` | 显式超时驱动（测试与未来的 ticker 用） |
| 新增 `set_record_reality_during_live(bool)` | Live 期间即时生效，不必等下一次模式转换 |

### 2.4 `server.py` / `audio.py`：让 stop 真的落到设备

- `server.py` 在构造 RuntimeController 后注入 `capture_coordinator.on_stop_mic = _stop_core_mic_device` / `on_start_mic = _start_core_mic_device`，两个回调操作 legacy pipeline 的 `mic`。**Core 自身不持有音频设备引用**——沿用 registry/turn_executor 同一种注入形状。
- `audio.py::Microphone.start()` 补幂等守卫。原先重复调用会**泄漏前一个 stream** 并让两个回调争抢同一队列；PR-020 会在 Passive/Live 转换时重新 start，而启动路径已经开过流，所以这个守卫是必需的（不是顺手改）。

---

## 3. 验证（本轮实测）

| 项 | 命令 | 结果 |
|---|---|---|
| 新增 RED | `pytest tests/red_v121/test_red_privacy_coordinator.py -q` | **15 passed** |
| RED 全套 | `pytest tests/red_v121 -q` | **274 passed / 0 failed**（R25 为 259，+15） |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 43 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |

**逐文件哈希（SHA256）**：

| 文件 | 字节 | SHA256 |
|---|---|---|
| `src/lva/core/capture.py` | 10,429 | `D54E356A44D70ED9B1732F078185E875C6A08F898A61D5DDD6A349AB793E779C` |
| `src/lva/core/runtime.py` | 35,262 | `62BB6A80725663FDB13243D6037C42ECF3D8B1569E8DA25EF908E9E205A0440A` |
| `src/lva/server.py` | 25,896 | `F88B0679F923BD68F6F3AE06F0BF42F641638AB52F1C871352779FE725A1DD05` |
| `src/lva/audio.py` | 25,628 | `38BDFA831A2399445F8D9E364310E51AE3263A3811259704B18195F9910610A2` |
| `tests/red_v121/test_red_privacy_coordinator.py` | 11,175 | `94C9AF541F90A4CDC6F33B69DB78CF05FCF6C3E48B72337DD719AD5673226829` |

**零契约改动**：`contracts/` 未触碰，三个生成制品字节未变。

---

## 4. 一个被否决的实现（记录在案）

实现中途我曾把 ack 暴露为 `capture.ack` **命令**并接进 dispatcher，随后**撤回**。

撤回理由：

1. 冻结计划 L470-479 的首版命令清单是**封闭列表**，其中没有 capture 命令；
2. 新增命令类型要改 `contracts/commands.py`，会改变三个生成制品的哈希 —— 触发**硬约束 5**，需用户单独授权；
3. PR-020 的 Files/new 明确只有 `core/capture.py`（L1334），命令面不在本片范围。

**当前状态**：`acknowledge_capture_operation()` 已是公开方法，Core 内部与测试可用；把它接到跨进程命令面（供 Rust capture executor 回执）**属 PR-021 的 integration 面**（L1344「service registry/bridge integration」、L1345「operation id ack」），需要契约授权后单独切片。

---

## 5. 本轮未做 / 未验证（诚实边界）

| 项 | 状态 |
|---|---|
| **真实音频设备停止** | **未运行**。`_stop_core_mic_device` 只验证了接线与异常路径；没有真实麦克风调用 `mic.stop()` 并观测帧停止。I09 的「物理帧停止」仍是逻辑级证据 |
| **真实 Screenpipe 停止/恢复** | 未运行。Rust `ManagedCaptureExecutor` 仍是 09-21 遗留实现，**无任何调用方**（全库 grep 仅自身定义），ack 从未真实产生 |
| `capture.ack` 命令面 | **未实现**（见 §4，需契约授权） |
| 超时 ticker | 未接。`expire_capture_operations()` 需由未来调用方（定时器或命令）驱动；当前靠 `compute_privacy_scope` 读取时惰性求值兜底 |
| PR-021（Rust capture executor） | **未开工**。属 Wave 3 另一 owner PR，与 PR-020 并行开发、按 contract 串行合并（L1336） |

---

## 6. 提交范围

本次提交只含 PR-020 相关文件：

- `src/lva/core/capture.py`、`src/lva/core/runtime.py`、`src/lva/server.py`、`src/lva/audio.py`
- `tests/red_v121/test_red_privacy_coordinator.py`（新增，15 项）
- 本报告

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪，非本切片产物）、`tests/red_v121/_artifacts/`（运行产物，已在 .gitignore）。


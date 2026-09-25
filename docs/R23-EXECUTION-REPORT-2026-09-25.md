# R23 执行报告 — 修复 saga 接线死路（B1/B2/B3/B4/B6/B8）+ 真实 Hub 复验

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：审查方源码级排查报告（B1–B10），用户指示「修复下面内容」

---

## 0. 结论先行

审查方的 **B1/B2/B3/B4/B6/B8 全部成立**，我已逐条回源码核实并修复。**B5/B9/B10 属语义待决，本轮未改**（见 §5）。

**B1 与 B2 是同一件事的两半**：Hub 控制命令在生产路径上**从未真正执行**。这与 8089 事故**完全同型**——测试直调被测对象，dispatch 路径从未被走过。

---

## 1. 逐条核实结果

| # | 审查方结论 | 我的核实 | 判定 |
|---|---|---|---|
| **B1** | `switch_model` 在 src/ 零调用点；`delegated_to_saga` 不 delegate | `switch_model` 仅 `hub_runtime.py:75` 定义；`execute_command` 同步、`switch_model` 异步；L628-634 只返回字符串 | **成立** |
| **B2** | COMMIT 步不调 `inference.bind_model()` | `bind_model` 全库仅 `hub_inference.py:84` 定义，**零调用**；`bound_model_id` 恒 `None` | **成立** |
| **B3** | 未接线 `api_key` | `server.py` 构造两客户端只传 `base_url`；`config.py` 有 `LLM_API_KEY` 但未传 | **成立** |
| **B4** | 验证用子串匹配 | L178 `any(target_model_id in m for m in models)` vs L104 `in loaded_ids` | **成立** |
| **B5** | `MODEL_CONFLICT_REQUIRES_CONFIRMATION` 只记日志不阻断 | L123-128 仅 `log.warning` 后继续 Step 3 | **成立**（语义待决） |
| **B6** | 弃用 `asyncio.get_event_loop()` | L174/175 | **成立** |
| **B8** | `if False:` 死代码 | `runtime.py` L665 | **成立** |
| B7 | 端口 6 处重复定义 | 核实为 5 处 Python + 1 处 Rust | **成立**（R21 已加守卫，未收敛） |
| B9 | `recall.py` LIKE 未转义 `%`/`_` | L119/137 参数化但无 `ESCAPE` | **成立**（功能怪癖，非注入） |
| B10 | `list_loaded` 失败落空 | L97-99 | **成立**（fail-open，有 warning） |

审查方的「干净确认」我也抽验通过：控制闸三条件、SSE 按 `\n` 分行、零 bare `except`、1234 命中全为误报。

---

## 2. 已修改（本轮，逐文件）

| 文件 | 改动 |
|---|---|
| `src/lva/core/runtime.py` | **B1**：saga 分支由「返回 `delegated_to_saga`」改为 `self._schedule_hub_saga(c_type, payload)`，成功返回 `accepted`、无事件循环时返回 `rejected` + `HUB_UNAVAILABLE`；新增 `_schedule_hub_saga()`（`get_running_loop()` + `create_task`，异常经 `log.exception` 上报）；**B8**：删除 `if False:` 块 |
| `src/lva/providers/hub_runtime.py` | **B2**：COMMIT 步新增 `self.inference.bind_model(target_model_id)`；**B4**：验证改为 `target_model_id in set(models)`（精确身份）；**B6**：改用 `time.monotonic()`，并 `import time` |
| `src/lva/server.py` | **B3**：`hub_api_key = getattr(C, "HUB_API_KEY", "") or C.LLM_API_KEY`，两客户端均传 `api_key=`；顺带修复上一轮我引入的**缩进错位**（`control_client=`/`inference_client=` 曾被错误缩进） |
| `src/lva/config.py` | **B3**：新增 `HUB_API_KEY`（环境变量 `LVA_HUB_API_KEY`，默认空） |
| `scripts/probe_real_hub.py` | 修正探针**自身的**版本读取（它也读顶层，故打印过误导性的 `DEGRADED`） |
| `tests/red_v121/test_red_hub_dispatch_wiring.py` | **新增 RED 套件**（8 项） |

---

## 3. 关键修复的语义

### 3.1 B1：同步 dispatcher 如何驱动异步 saga

```python
def _schedule_hub_saga(self, c_type, payload) -> bool:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        log.warning("Hub command %s cannot be scheduled: no running event loop", c_type)
        return False          # -> 命令返回 rejected，而不是假装成功
    loop.create_task(_run())  # -> 真正执行 switch_model / sleep_bound_model
    return True
```

**为什么返回 `accepted` 而非 `applied`**：saga 是异步的，命令返回时模型尚未切换。`accepted` 是诚实语义；`applied` 会重复原来那个「报告成功但什么都没做」的错误。

**为什么无事件循环时返回 `rejected`**：同步调用方（如测试或 CLI）拿不到调度能力时，**必须被告知失败**，而不是收到一个假的 `applied`。

### 3.2 B2：绑定语义闭环

`inference.bind_model(target_model_id)` 使 `bound_model_id` 非空 → `X-LVA-Bound-Model` 头开始发送 → 客户端注释里那句「Leaving it to the Hub default would let a switch silently answer from the previous model」的防呆**首次真正生效**。

### 3.3 B4：精确身份

子串匹配会让目标 `qwen3-4b` 被已加载的 `qwen3-4b-instruct` 误判为「已加载」，从而绑定到一个并未加载的模型。改为 `set` 成员判断，与 L104 的冲突解决步一致。

---

## 4. 实测

| 项 | 结果 |
|---|---|
| 新 RED 套件 | 改前 **7 failed** → 改后 **8 passed** |
| `tests/red_v121` 全量 | **249 passed / 0 failed**（起始 241P；+8 全为本轮新增并转绿） |
| v12 层 7 组 | **all groups passed** |
| ruff | All checks passed |
| **真实 Hub 复验** | `reported version = '0.9.8.3' -> classify_version = READY`；`Core probe_handshake() = READY`；`Core supports(models.load) = True` |

### 4.1 真实 Hub 复验细节（用户启动的 Hub 0.9.8.3，`0.0.0.0:8080`）

```text
listener rows for port 8080: 1
  LISTENING 0.0.0.0:8080 -> AllInterfacesV4
PR-008 classifier verdict = VERIFIED_NON_LOOPBACK
control_allowed (plan L665) = False          <- 正确行为（L579/L1257）
GET /api/sys/version -> 200 {"success":true,"data":{"tag":"v0.9.8.3","version":"0.9.8.3"}}
GET /api/models/loaded -> 200 {"models":[],"success":true}
GET /api/models/list -> 200 {"models":[{"id":"Occamy-1.0",...}]}
GET /v1/models -> 200 {"object":"list","models":[],"data":[]}
reported version = '0.9.8.3' -> classify_version = READY
Core probe_handshake() = READY
Core supports(models.load) = True
```

**`control_allowed = False` 是正确的**：Hub 监听 `0.0.0.0`，按 L579/L1257 control 应被拒绝。本次验证覆盖的是**拒绝路径**，不是放行路径（放行需 Hub 改为仅监听 127.0.0.1）。

---

## 5. 未修改项与理由（B5/B9/B10 + B7）

| # | 为何未改 |
|---|---|
| **B5** | 审查方指出「要么实现确认闸，要么注明语义是有意的——源码无任何注释，含糊」。**这是一个产品语义决定**：`MODEL_CONFLICT_REQUIRES_CONFIRMATION` 是否应在加载前阻断？计划 5.5 只说「confirm preexisting stop」，未说「加载需先停旧模型」。**需用户/审查方裁决**，我不擅自改行为 |
| **B9** | `%`/`_` 未转义是**功能怪癖而非安全缺陷**（已参数化）。修它会改变搜索语义（用户搜 `50%` 会变成通配符），**属行为变更**，需裁决 |
| **B10** | fail-open 有 warning，审查方也判「可接受，建议显式注释」。**加注释是低风险改进**，但本轮聚焦高危项，未一并做 |
| **B7** | R21 已加 8 项一致性守卫（检测漂移），**收敛为单一事实源**需定义权威位置（契约 or 生成模块），会触及契约/构建流程，**需单独授权** |

---

## 6. 本轮我自己的两处失误（已修，记录在案）

1. **`server.py` 缩进错位**：我上一轮补 `api_key` 时的补丁把 `control_client=`/`inference_client=` 两行错误缩进，破坏了 `HubRuntimeSaga(...)` 的调用结构。本轮修复时发现并改正。
2. **`probe_real_hub.py` 复述了同一个错误假设**：探针自己读 `/api/sys/version` 的顶层 `version`，因此在 Core 已修好之后**仍打印 `reported version = None -> DEGRADED`**。这正是 R22 那个 bug 的同型复制——**我在写探针时重犯了它**。已修。

---

## 7. 对「同型缺陷」的第三次确认

| 事故 | 引入 | 掩盖方式 |
|---|---|---|
| 8089 端口 | R08 | Rust 单测夹具用同一错端口 |
| version 形状 | R14 | fixture 用同一错假设 |
| **saga 死路** | R15（接线）/PR-014 | 测试**直调** `switch_model`，dispatch 路径从未走过 |

**三次的共同点**：**测试绕过了真实调用路径**。审查方新增的基线检查项③（命令→分发→真实调用链追踪）**已被本轮证实是必要的**——它正是本轮唯一能发现 B1 的方法。

---

## 8. 硬约束遵守

未弱化/跳过/xfail 任何断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 .venv / venv / benchmarks/；**未执行 git 写操作**；**未改动用户的 Hub 配置**。E 盘写入经 apply_patch 与一次提权替换。**本轮零契约改动、零新增依赖。**

## 9. 下一片

| 项 | 说明 |
|---|---|
| **B5 语义裁决** | `MODEL_CONFLICT_REQUIRES_CONFIRMATION` 是否阻断加载？ |
| B9/B10 | 是否改变搜索语义 / 补显式注释 |
| B7 单一事实源收敛 | 需授权（触及契约/构建） |
| 放行路径验证 | 需 Hub 改为仅监听 127.0.0.1 |
| R20–R23 成果 commit + push | 工作树已累积较多 |


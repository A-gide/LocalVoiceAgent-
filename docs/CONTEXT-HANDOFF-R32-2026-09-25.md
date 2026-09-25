# CONTEXT HANDOFF — LocalVoiceAgent v1.2.1（R32 状态快照）

- 生成时间：2026-09-25（Asia/Shanghai）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`d5cf852`（`main...origin/main`，无 ahead）
- 本文件性质：**上下文迁移**，不是总结。新会话应仅凭本文件 + 仓库内文档即可接管。

---

# PROJECT_OBJECTIVE

按冻结计划 `C:\Users\a.gide\Documents\Codex\2026-09-20\new-chat-2\outputs\ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md`
（**1,858 行 / 108,041 B / SHA256 `E198B7BFEDE70093D78357A3718B44ACAA51420AEB88F284FD8A9550E9086D3D`**）
执行 v1.2.1 全部修复切片（PR-001…PR-038）与 G0–G8 门禁，交付一个隐私优先、本地优先的语音助手桌面应用。

**当前阶段**：Wave 2 收尾 / Wave 3 部分完成。G0 PASS、G1 PASS（12/12）。

执行纪律（用户设定，贯穿全项目）：

1. **先写 RED → 再最小修复**（每片必须如此）；
2. 每片交付 `docs/R<NN>-EXECUTION-REPORT-<date>.md`；
3. 计划条文是权威；报告必须引用行号与逐字条文；
4. 审查方（独立会话）复核实现方声明，发现不实即记录并撤回。

---

# CURRENT_STATE

## 仓库状态

| 项 | 值 |
|---|---|
| HEAD | `d5cf852` |
| 远端 | `github.com:A-gide/LocalVoiceAgent-.git`，`main` 已同步 |
| 工作树 | **23 条**：21 项 ` D` 删除类 + 2 个未跟踪文件（见下） |

**工作树 23 条明细（不得提交，见闸门）**：

- 17 个 OLV 核心文件（`conversations/*` 9 个、`memory_router.py`、`routes.py`、`server.py`、`service_context.py`、`websocket_handler.py`、`run_server.py`、`chat_group.py`、`chat_history_manager.py`）→ 计划 **L1730（PR-036 门）**
- 3 个旧 HTML（`apps/desktop-shell/patches/frontend-index-pet-mode.html`、`ui/index.html`、`ui/settings.html`）→ 计划 **L1732（PR-038 门）**
- `scripts/llm_serve.py` → 计划 **L1728（PR-015 门）**
- 2 个未跟踪：`apps/open-llm-vtuber/CODEOWNERS`、`apps/open-llm-vtuber/DEPRECATION.md`

## 测试与门禁

| 项 | 命令 | 当前值 |
|---|---|---|
| red_v121 | `pytest tests/red_v121 -q` | **317 passed / 0 failed** |
| v12 七组 | `python tests/run_groups.py --layer v12` | contract 5 / invariants 23 / unit 47 / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| Rust 单测 | `cargo test --lib --offline` | **73 passed / 0 failed / 1 ignored**，`stray_ping=0` |
| 前端 typecheck | `npx vue-tsc --noEmit` | EXIT=0 |
| 前端 build | `npx vite build` | EXIT=0 |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| codegen | `python -m lva.contracts.codegen --verify` | 三制品 **verified** |

## 三个生成制品（当前哈希）

| 制品 | 字节 | SHA256 |
|---|---|---|
| `schemas/lva-ipc-v1.json` | 57,730 | `363331DD735CE6204C791AC12CF3BFDDDBEF2EE0C1A445285D9ADE19174DB354` |
| `apps/desktop-ui/src/generated/lva-ipc.ts` | 17,733 | `3F1C99B1B79F81BD2D0034AE4B4DFCAEAAB660CCF7C1A45B59439CC1BB7A06FF` |
| `apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` | 80,980 | `764CC19E8D7DE20519C10FBA907EDA2991E534157E29F1AE3E4281CF41FAE59D` |

**契约摘要已重新 pin**：`src/lva/contracts/codegen.py` 的 `EXPECTED_SCHEMA_SHA256 = "cdfc93e03a0db36c3781e2fbc88e0e7f5fe56e382f6291da1ad36f590e664a27"`
（上一次 pin 为 `050a260d…`，PR-012 时）。

## Hub 运行时状态（重要）

| 项 | 值 |
|---|---|
| 进程 | `llama.cpp-hub` PID **30452**，正在运行 |
| 实际监听 | **`127.0.0.1:8080`**（回环绑定） |
| 配置文件 | `D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\config\application.json` |
| 文件内容 | `listenAddress: "0.0.0.0"`（**已还原**），495 B，SHA256 `C3ACAB6907F072F18E4D99738D17D2032A76502328434D865A9F7E42D71DB61A` |
| 备份文件 | 同目录 `application.json.before-loopback-test`（495 B，哈希同上，逐字节一致） |
| 其他键 | `webPort 8080` / `httpOnlyPort 8081` / `apiKeyEnabled: true` / `https.enabled: false` |
| 有活动连接 | 是：Chrome（PID 24888）与 Hub 之间 2 条 ESTABLISHED |

**关键矛盾（必须知悉）**：文件写 `0.0.0.0`，但**运行中的进程监听 `127.0.0.1`**——因为配置改动需重启才生效。下次重启 Hub 会回到 `0.0.0.0`。若希望长期回环，需把改绑作为常驻配置。

**Hub API key**：明文存于上述配置文件（`security.apiKey` 字段）。**不得写入仓库、日志或任何报告**——本文件不复制其值。

---

# COMPLETED_WORK

## 提交历史（全部已推送）

```
d5cf852 docs: record the first real VERIFIED_LOOPBACK observation (PR-012 gate opens)
8222071 feat: persist the window position, resubscribe events, guard secret writes
1909eef feat: Output Mute reaches the Core, and the window clamps on restore
77c29d2 fix(ui): grant the window permissions the UI calls, align the settings DTO
bec0836 test: close the PR-016/019 acceptance boundaries (lock contention, tz shapes)
adc7b2f feat(shell): managed Screenpipe capture executor (PR-021)
2b48e84 feat(core): ack-driven privacy scope (PR-020)
e4989c6 refactor(config): single source for the Hub endpoint (R25/B7)
07e2d2d fix: real-Hub defects, saga dispatch wiring, cross-language guards (R20-R24)
c916fce docs: formal G1 verdict (Secure IPC/Supervisor) -- PASS 12/12
292b23c docs: document the locked uv install/test flow in README
e035746 feat(shell): PR-015 remove direct llama lifecycle (red_v121 reaches zero)
43177e5 feat(providers): PR-013 inference provider + PR-014 saga acceptance
3a7ce44 feat: land v1.2.1 R00-R17 fixes (introduce/migrate/verify slice)
cf1c967 feat: initialize LocalVoiceAgent monorepo ...
a35d9de Initial commit
```

## R25 — B7 单源收敛（Hub 端口）

- `config.py` 新增 `hub_base_url(*, with_v1=False)` 作唯一派生点；
- 三个 provider 的 `base_url` 默认由 `str = "http://127.0.0.1:8080"` 改为 `str | None = None` + `(base_url or C.hub_base_url())`；
- `server.py` 的 `base_url = C.hub_base_url()`；
- **发现并修复清单外第 7 处副本**：`config.py` 的 `LLM_BASE_URL` 原为 `os.environ.get("LVA_LLM_URL", "http://127.0.0.1:8080/v1")`，改为 `os.environ.get("LVA_LLM_URL", "") or hub_base_url(with_v1=True)`（用 `or` 而非 `,`，使显式空串也回落）；
- services 段上移到 llm 段之前（`LLM_BASE_URL` 现在依赖 `hub_base_url()`）；
- **反转** R21 的 `test_python_provider_defaults_actually_use_the_hub_port`：原断言要求 provider **必须含**端口字面量，改为**必须不含**且必须走 `hub_base_url`；
- Rust 保留一个常量（`lib.rs` 的 `HUB_CONTROL_PORT: u16 = 8080`），因无法 import Python，由 R21 跨语言守卫保一致——**这是有意例外**；
- 新增 `tests/red_v121/test_red_single_source_hub_port.py`（6 项）。

## R26 — PR-020 隐私捕获协调器（ack 驱动）

**开工前实况**：既有 7 项 `test_red_capture.py` 全绿，但绿的是表面——`CaptureCoordinator` 只有布尔标志，无 operation 概念。

- 新增 `CaptureOperation` dataclass：`operation_id`（`cap-<n>`）/ `kind`（`stop`|`resume`）/ `requested_at` / `deadline` / `status`（`pending`|`acknowledged`|`timed_out`）；
- `CaptureCoordinator` 改为 `@dataclass`，注入 `now`（可测试时钟）与 `ack_timeout`（默认 `CAPTURE_ACK_TIMEOUT = 5s`）；
- **核心设计判断**：布尔值无法表达「已请求但未应答」，而那正是必须拒绝 verified 的状态；
- `request_managed_capture_off(*, track=True)`：`track=False` **仅供启动假设**（那时无实例可应答）；
- `expire_overdue()`：stop 超时把 `managed_screenpipe_stopped` **丢弃为 `None`**（不保留旧值）；
- `compute_privacy_scope` 首判 `unsettled_stop_operations()` → 命中即 `UNKNOWN`；**超时在读取时惰性求值**（生产无 ticker）；
- `stop_core_mic()` **按结果而非意图**设标志：回调抛异常 → `core_mic_stopped = False`；
- Privacy Pause 由 `update_managed_capture_status(managed_stopped=None)` 改为 **`request_managed_capture_off()`**（原先只记录「不知道」，从不请求任何人停止）；
- Passive 恒发 resume；Live 按 `record_reality_during_live` 分流；
- 新增 `_publish_privacy_scope(previous_scope)` 单一发布点；`privacy.scope_changed` **首次有生产者**；
- `server.py` 注入 `on_stop_mic` / `on_start_mic` 驱动真实设备；
- `audio.py::Microphone.start()` 补**幂等守卫**（原先重复调用会泄漏前一个 stream）；
- 新增 `tests/red_v121/test_red_privacy_coordinator.py`（15 项）。

## R27 — PR-021 Rust capture executor

`managed_capture.rs` 原为 2026-09-21 遗留 stub（2,131 B，**零调用方**）。重写为 22,531 B：

- 三个显式类型：`CaptureCapability`（Controllable/Uncontrollable/Unknown）、`CaptureIntent`（Stop/Resume）、`CaptureExecutionStatus`（Applied/Uncontrollable/Failed）；
- `managed_screenpipe_stopped = None` 是 **fail-closed 答案**，Core 不得读成成功；
- capability 判定：Spawned 恒可控；Adopted 需**已证明通道**（`CaptureProbe { reachable, version_known }` 两者同时成立）；External/Unknown 只报告；
- **executor 接收 operation_id + intent，自己不读 mode**——否则出现第二个权威（与 Hub 端口双源同型缺陷）；
- **测试抓出两个真实缺陷**：
  1. `Supervisor::stop_spawned()` 成功后**移除所有权条目**（既有测试依赖此语义），导致 LVA 停掉的实例与从未见过的无法区分，永远无法恢复 → 新增 `stopped_by_us` 标志；
  2. Resume 原本无条件返回 `Applied`，会**宣称一个不存在的 recorder 正在运行** → 改为三分支（未停过→Applied 不 spawn；停过+有 spawner→真重启；停过+无 spawner→**Failed**）；
- `lib.rs` 接线：Tauri state + `get_capture_capability` / `execute_capture_operation` 命令；
- `probe_screenpipe_capability()` 恒返回 `version_known: false`（**故意的保守判定**，见 ASSUMPTIONS）；
- 新增 `test_red_cross_language_consistency.py::test_the_screenpipe_port_agrees_across_languages`；
- Rust 测试 12 项。

## R28 — PR-016..019 验收映射复核

审查方已于 2026-09-24 出具 `docs/PR-016-019-FORMAL-ACCEPTANCE-2026-09-24.md`（四片全 PASS），但基线停在 `292b23c`。

- **核对**：文档引用的 10 个关键测试全部在档，37 passed；四片 PASS 继续成立；
- **闭合边界 1（PR-016 DB lock）**：新增 `tests/unit/test_journal_lock_contention.py`（4 项）；
- **闭合边界 2（PR-019 DST）**：新增 `tests/red_v121/test_red_timezone_anchor_shapes.py`（5 项）；
- **正式撤回一个假缺陷**（详见 FAILED_ATTEMPTS）；
- 新增 `docs/R28-ACCEPTANCE-MAPPING-2026-09-25.md`。

## R29 — PR-023/024/025 UI

**开工前核对：三片 UI 骨架已存在**（router/stores/Controls Island 五项/6 个 settings section/write-only secret UX 全在），故不重复实现，只处置三处真实缺口：

1. **capability 缺口（S-UI-01 阻断级 R11）**：`capabilities/default.json` 只授予 `core:default`，而 `core:window:default` 只有 28 项**只读**权限；`windows` 列表只有 `main`。→ 重写为 5 个窗口标签 + 12 项权限（`core:default` + 11 项显式窗口权限）；
2. **前端 settings DTO 漂移**：`tauri-bridge.ts` 声明 `has_openai_key`/`has_screenpipe_key`/`autostart`，Rust 实际返回 `cloud_api_key_configured` 等 → **无论配置多少密钥 UI 永远显示「未配置」**。已逐字段对齐（17 字段含 `settings_revision`）；
3. **Output Mute 只改前端本地 ref**（记录待裁决，R30 已修）；
- 新增 `test_red_window_capability.py`（5 项）、`test_red_settings_dto_parity.py`（4 项）。

## R30 — Output Mute 端到端 + 窗口几何

**Output Mute**（用户授权契约改动）：

- 新增 `PlaybackSetMutedPayload`（`type: "playback.set_muted"`，`muted: bool`）；
- 重新 pin codegen 摘要并重跑生成器（三制品全部重写，**非手改**）；
- `runtime.py` 新增 `on_playback_mute` 回调 + 派发分支；**任何模式都不禁止**；回调抛异常 → `rejected` + `PROVIDER_DISCONNECTED` **且不写 `_playback.muted`**；
- `audio.py`：`Player` 与 `NullPlayer` 各加 `set_muted`/`muted`；进入 mute **先 flush**（generation bump 才真正停声）；**mute 期间 `play()` 直接丢弃而非入队**（否则 unmute 会播放已静音的语音）；
- `server.py` 注入 `_set_playback_muted`；
- `stores/runtime.ts`：`setMuted` 改为发送命令，本地赋值降级为乐观回显，被拒/抛错时**回滚并记 `lastError`**；
- `test_red_contract_cas.py` 三处冻结清单登记 `playback.set_muted`；
- 新增 `test_red_playback_mute_command.py`（10 项）。

**窗口几何**：

- 新增 `apps/desktop-ui/src/composables/window/geometry.js`（纯 ESM，Node 可执行）+ `geometry.d.ts`；
- `clampToWorkArea` 把窗口**整体**留在工作区内（不是仅相交）；窗口大于工作区时**钉到原点**（两端 clamp 会振荡）；
- `chooseWorkArea`：窗口所在显示器 → 相交 → primary → 首个；
- `parseSavedGeometry`：畸形记录**降级为 null** 而非抛错；
- `useWindowGeometry.ts` 接线；monitor 查询走 `@tauri-apps/api/window` 的**模块级函数**（`availableMonitors`/`primaryMonitor`，不在 `WebviewWindow` 上）；
- 新增 `apps/desktop-shell/src-tauri/src/geometry.rs`（`WindowGeometry` + `load/save/clear`）+ 三个命令（`get/set/clear_window_geometry`）；
- **几何独立文件而非塞进 `AppSettings`**：否则每次移动窗口都递增 `settings_revision`，作废用户正在进行的设置编辑；
- 新增 `test_red_window_geometry.py`（12 项）+ Rust 4 项。

## R31 — 窗口持久化 / 事件重连 / L463

- `watchPosition()` + `persistCurrentDebounced(400ms)`（拖动每帧发 move 事件，逐次写会重写配置数百次）；`CharacterView` 挂载时启动并立即 `persistCurrent()` 一次（**崩溃重启不产生 move 事件**）；
- 存**原始位置**而非 clamp 后位置（clamp 需要下一次启动的显示器列表）；
- `ensureEventSubscription`（幂等，先释放旧监听器——否则每次重载叠加，事件被处理两次）；`App.vue` 改走该路径；
- **L463 全合规**：`settings.rs` 新增 `set_secret_checked` / `clear_secret_checked`（先 `check_revision` 再写）；`lib.rs` 命令加 `settings_revision: Option<u64>`；前端写入时引用 UI 最后读到的 revision，未读过传 `null`；
- 新增 `test_red_window_persistence_and_reconnect.py`（6 项）+ Rust 2 项。

## R32 — 放行路径首次真实验证

**这是项目首个「开门」观测**。此前全部证据都是 fail-closed 侧（无 attestation → 拒绝）。

```
listener rows for port 8080: 1
  LISTENING 127.0.0.1:8080 -> LoopbackOnly
PR-008 classifier verdict = VERIFIED_LOOPBACK
control_allowed (plan L665) = True
GET /api/sys/version -> 200 {"success":true,"data":{"createdTime":"2026-09-07T03:55:53Z","tag":"v0.9.8.3","version":"0.9.8.3"}}
GET /api/models/loaded -> 200 {"models":[],"success":true}
GET /api/models/list -> 200 {"models":[{"name":"Occamy-1.0","size":21166757696,...}]}
GET /v1/models -> 200 {"object":"list","models":[],"data":[]}
reported version = '0.9.8.3' -> classify_version = READY
Core probe_handshake() = READY
Core supports(models.load) = True
```

**副产品**：`/api/models/list` 有 `Occamy-1.0`（21.1 GB）而 `loaded` 与 `/v1` 都空——**inventory 与 loaded 确实是两个面**，印证 PR-014「多 loaded model 不误标 current」为何必须分开读。

**配置处置**：改绑为验证而做，验证后**按预案还原**（哈希回到 `C3ACAB69…`）。

## 更早的会话（R00–R24）

见 `docs/R04-EXECUTION-REPORT-2026-09-23.md` … `docs/R24-EXECUTION-REPORT-2026-09-25.md`，以及 `docs/AUDIT-REVIEW-2026-09-24.md`（独立审查，含 V1–V11 编号与两条撤回）。

要点：G0 PASS；G1 PASS（12/12，`docs/G1-FORMAL-VERDICT-2026-09-24.md`）；R20–R24 修复真实 Hub 缺陷、saga dispatch 接线、跨语言守卫。

---

# PENDING_WORK

## 未开工的切片（按计划 Wave）

| 切片 | Wave | 计划行 | 依赖状态 |
|---|---|---|---|
| PR-005/007 剩余面 | Wave 1/2 | — | 主要面已完成（supervisor、bridge） |
| **PR-016..019 剩余** | — | — | 四片已 PASS；真实服务级验证仍缺 |
| PR-022 剩余 | Wave 0b | L1350-1358 | harness 已建；WASAPI loopback benchmark scaffold 未做 |
| PR-026 Hub model UI | Wave 5 | L1392-1400 | 依赖 PR-014/023/025（均已就绪） |
| PR-027 Hearing/Speech | Wave 3 | L1402-1410 | 骨架已在（HearingSection/SpeechSection） |
| PR-028 Chat | Wave 3 | L1412-1420 | 骨架已在（ChatView） |
| PR-029 Memory | Wave 3 | L1422-1430 | 骨架已在（MemoryView） |
| PR-032 Services/Diagnostics | Wave 4 | L1452-1460 | 骨架已在（ServicesView/DiagnosticsSection） |
| PR-033 OLV renderer bridge | Wave 4 | L1462-1470 | 未开工 |
| PR-034 Live2D embed | Wave 5 | L1472-1480 | Live2D 资源已在 `public/live2d/haru/`，未嵌入 |
| **PR-035 全量门禁** | Wave 6 | — | fault + migration + 2h/8h/12h soak + UX |
| **PR-036 OLV 删除** | Wave 7 | L1730 | 闸门：17 个 ` D` 文件等待此门 |
| **PR-037 Core facade 删除** | Wave 7 | — | `pipeline.py` 旁路、`_ws_ask`、legacy mode adapter |
| **PR-038 Legacy UI 删除** | Wave 7 | L1732 | 闸门：3 个旧 HTML 等待此门 |

## 明确未闭环的验证项（跨切片累积）

| 项 | 状态 | 归属 |
|---|---|---|
| **真实 model load/stop/switch** | 未验证。R32 时 `/api/models/loaded` 为空，未加载任何模型 | PR-014/G3 |
| **Rust 进程真实发送 attestation** | 未验证。R32 的 verdict 由 `probe_real_hub.py` 侧计算；`start_attestation_reporter` 的真实送达需 GUI | PR-012 |
| **Hub 重启后重新 attest** | 未验证。§5.8 要求重连后重验；R32 只观测一次运行中的 Hub | PR-012 |
| **Output Mute 真实音频** | 未在真实声卡上断言静音（测试用与真实 player 同语义的 `NullPlayer` + 真实 dispatcher） | PR-024 |
| **窗口几何运行时行为** | 未验证。clamp 算术经 Node 实测、持久化经 Rust 单测；真实 Tauri 的 `setPosition`/monitor 查询/`onMoved` 需 GUI | PR-030/031 |
| **多显示器场景** | 本机单显示器（`\.\DISPLAY5` 1707x1067，primary，缩放 150%）；多显示器分支只有 Node 级证据 | PR-030 |
| **WebView2 主动 reload** | 未实现。重连路径已就绪，但触发 reload 需 Rust 暴露命令（JS 侧无 reload API） | PR-030/031 |
| **capability 运行时实证** | 未验证（无 GUI）。ACL 层已通（`cargo check` 通过），运行时行为需真实 GUI | PR-023 |
| **真实 Screenpipe 停止** | 未运行。R27 测试用 `ping.exe` 哨兵验证真实 spawn/stop/恢复路径 | PR-021 |
| **真实 Adopted Screenpipe 受控** | 未打通。`probe_screenpipe_capability()` 恒返回 `version_known: false` | PR-021 |
| **`CaptureSpawner` 未注入** | 「LVA 停掉 → 恢复」在生产接线中返回 `Failed` 而非真重启；`with_spawner` 语义与测试已就绪 | PR-021 |
| **`capture.ack` 跨进程回执** | 未接。executor 能回显 id 并返回结果，但 Rust→Core 的命令面需新增命令类型（硬约束 5） | PR-021 |
| **PR-016「全部证据为单测/fixture 级」** | 无真实 Screenpipe 服务、无真实生产旧库迁移演练 | PR-035 前 |
| **真实 IANA DST 跳变日** | 未测试。因无代码路径存 IANA 名（见 ASSUMPTIONS） | PR-019 边界 |

## 待用户决定的事项

1. **Hub 长期绑定策略**：当前文件写 `0.0.0.0`、进程监听 `127.0.0.1`。若希望长期回环，需把改绑作为常驻配置（下次重启会回到 `0.0.0.0`）。
2. **`_enc` 密钥轮换**：**已由用户裁定可关闭**（见 DECISIONS_AND_RATIONALES 的 DPAPI 条目）。
3. **真实模型加载验证**：现在 attestation 门已开（`control_allowed = True`），具备做一次真实 `hub.bind_model` 全链路验证的条件。

---

# ARCHITECTURE

## 三层职责（计划 §2、§8.1）

```
Vue desktop-ui  --invoke/events only-->  Tauri Shell (Rust)  --WS-->  LVA Core (Python)
                                              |                            |
                                              |                            +-- Hub (HTTP)
                                              +-- Supervisor (Spawned-only)      /api/* + /v1/*
                                              +-- ServiceRegistry (identity/readiness)
                                              +-- NetworkAttestation (read-only listener table)
```

## 关键不变量（I01–I22，计划 L1580-1610）

| 编号 | 内容 | 现状 |
|---|---|---|
| I01 | stale Turn 永不到 playback/UI/history/Journal | 绿（StaleEffectGate 三道 gate） |
| I04 | 只终止 Spawned 子进程 | 绿（`Supervisor`，R27 加 `stopped_by_us`） |
| I06 | raw transcript 不可变 | 绿（SQLite 触发器） |
| I09/I10/I19 | Privacy 相关 | 绿（R26 ack 驱动） |
| I17 | importer 幂等 | 绿 |
| I21 | Hub management endpoint 只从 Core 可达 | 绿（R20-R24） |
| I22 | 所有 conversation entry 经 dispatcher | 绿（R13） |

## 数据流要点

- **事件序列**：`EventEnvelope.sequence` 同一 `runtime_instance_id` 内严格递增；bridge 检测 gap → 强制 snapshot resync；`runtime_instance_id` 变化 → 丢弃 stale command（`bridge.rs`）。
- **CAS 矩阵**（计划 L459-466）：`runtime.set_mode`/`restore_mode` → `runtime_control_revision`；`hub.bind_model`/`sleep_bound_model` → `hub_binding_revision`；settings update/clear secret → `settings_revision`（**Rust 边界**，L463）；`memory.correct`/`hard_delete` → 目标 event 的 `current_revision`；`turn.send_text`/`cancel` 无 CAS。
- **L463 的边界裁定**（既有 RED 已裁定，`test_red_contract_cas.py::test_settings_commands_are_boundary_owned_not_core_enforced`）：settings CAS **属 Rust 边界**，不进 Core 全局 RuntimeState CAS（§4.2 L397 + 权威矩阵 L293）。R31 据此在 Rust 命令层实现。
- **attestation 门**（计划 L665）：状态只有 `VERIFIED_LOOPBACK | VERIFIED_NON_LOOPBACK | UNVERIFIED_BIND`；**只有第一种允许 load/stop/switch control**；`revalidate_after` 是**截止时间**，一次性 VERIFIED 不能永久授权。

---

# FILES_AND_CHANGES

## 本轮（R25–R32）改动的文件

### Python（`src/lva/`）

| 文件 | 改动 |
|---|---|
| `config.py` | 新增 `hub_base_url()`；services 段上移；`LLM_BASE_URL` 改为派生 |
| `providers/hub_control.py` | `base_url: str \| None = None` + `C.hub_base_url()` |
| `providers/hub_inference.py` | 同上 |
| `providers/openai_compatible.py` | `(base_url or C.hub_base_url(with_v1=True))` |
| `server.py` | `C.hub_base_url()`；注入 `on_stop_mic`/`on_start_mic`/`on_playback_mute`；`_set_playback_muted()` |
| `core/capture.py` | 重写：`CaptureOperation` + ack/超时/`unverified_reasons` |
| `core/runtime.py` | `capture_now`/`on_playback_mute` 参数；intent 与 scope 事件；`acknowledge_capture_operation`/`expire_capture_operations`/`set_record_reality_during_live`；`playback.set_muted` 分支 |
| `audio.py` | `Microphone.start()` 幂等；`Player`/`NullPlayer` 的 `set_muted`/`muted` |
| `contracts/commands.py` | 新增 `PlaybackSetMutedPayload` + union 成员 |
| `contracts/codegen.py` | `EXPECTED_SCHEMA_SHA256` 重新 pin 为 `cdfc93e0…` |

### Rust（`apps/desktop-shell/src-tauri/src/`）

| 文件 | 改动 |
|---|---|
| `managed_capture.rs` | 重写（2,131 → 22,531 B）：capability/intent/status + operation_id ack |
| `supervisor.rs` | 新增 `take_child_for_test`（test-only） |
| `geometry.rs` | **新增**：`WindowGeometry` + `load/save/clear` + 4 项单测 |
| `settings.rs` | 新增 `set_secret_checked`/`clear_secret_checked` + 2 项 L463 单测 |
| `lib.rs` | executor 接线 + `get_capture_capability`/`execute_capture_operation`；几何三命令；`set_secret`/`clear_secret` 加 `settings_revision` 参数 |
| `capabilities/default.json` | 5 个窗口标签 + 12 项权限 |
| `generated/lva_ipc.rs` | 由 codegen 重生成 |

### 前端（`apps/desktop-ui/src/`）

| 文件 | 改动 |
|---|---|
| `stores/runtime.ts` | `setMuted` 发送 `playback.set_muted`，乐观回显 + 失败回滚 |
| `stores/settings.ts` | `setSecret`/`clearSecret` 传 `settings_revision` |
| `bridge/tauri-bridge.ts` | `PublicAppSettings` 逐字段对齐 Rust；`SavedWindowGeometry` 类型 + 三方法；`ensureEventSubscription` + 模块级 `eventSubscription` |
| `composables/window/geometry.js` | **新增**（纯 ESM：clamp/choose/isInside/overlaps/resolve/parse） |
| `composables/window/geometry.d.ts` | **新增**（类型声明） |
| `composables/window/useWindowGeometry.ts` | 接线 clamp + 持久化 + `watchPosition` + 防抖 |
| `features/character/CharacterView.vue` | 挂载时恢复几何 + `watchPosition` + `persistCurrent`；`onUnmounted` 释放 |
| `features/settings/ModelSection.vue` | 改读 `cloud_api_key_configured` |
| `app/App.vue` | 改走 `ensureEventSubscription` |
| `generated/lva-ipc.ts` | 由 codegen 重生成 |

### 测试（新增）

| 文件 | 项数 | 覆盖 |
|---|---|---|
| `tests/red_v121/test_red_single_source_hub_port.py` | 6 | B7 单源 |
| `tests/red_v121/test_red_privacy_coordinator.py` | 15 | PR-020 ack 驱动 |
| `tests/unit/test_journal_lock_contention.py` | 4 | PR-016 锁竞争 |
| `tests/red_v121/test_red_timezone_anchor_shapes.py` | 5 | PR-019 时区形状 |
| `tests/red_v121/test_red_window_capability.py` | 5 | R11 capability |
| `tests/red_v121/test_red_settings_dto_parity.py` | 4 | DTO 对齐 |
| `tests/red_v121/test_red_playback_mute_command.py` | 10 | Output Mute 端到端 |
| `tests/red_v121/test_red_window_geometry.py` | 12 | clamp 算术 |
| `tests/red_v121/test_red_window_persistence_and_reconnect.py` | 6 | 持久化 + 重连 |

### 文档（`docs/`，本轮新增）

`R25`…`R32` 执行报告；`R28-ACCEPTANCE-MAPPING-2026-09-25.md`；`R32-HUB-LOOPBACK-VERIFICATION-2026-09-25.md`；本文件。

**注意**：`docs/ARCHITECTURE-PLAN-2026-09-v1.2.1.md`（108,041 B）是冻结计划的**仓内副本**，与外部原件哈希一致。

---

# CONFIGURATION

## 环境变量（`src/lva/config.py`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `LVA_ROOT` | `E:\AI\LocalVoiceAgent` | 仓库根 |
| `LVA_HUB_PORT` | `8080` | Hub 控制面端口（唯一源：`HUB_PORT`） |
| `LVA_HUB_API_KEY` | `""` | Hub 密钥，**内存 only**，从不写盘/日志 |
| `LVA_LLM_URL` | `""`（空 → 派生） | 空串也回落到 `hub_base_url(with_v1=True)` |
| `LVA_LLM_KEY` | `""` | 从不写日志 |
| `LVA_LLM_MODEL` | `local-live-llm` | |
| `LVA_LLM_TIMEOUT` | `180` | |
| `LVA_LLM_CONTEXT` | `8192` | |
| `LVA_LLM_MAX_TOKENS` | `512` | |
| `LVA_LLM_DEEP_MAX_TOKENS` | `2048` | 深度问题用更大上限 |
| `LVA_PORT` | `8765` | Core 端口（bootstrap 模式下为 ephemeral） |
| `LVA_MUTE` | `0` | `1` → 加载静音 player |
| `LVA_TEST_ARTIFACT_DIR` | `tests/red_v121/_artifacts` | RED 失败工件目录（沙箱内须重定向到 X 盘） |

`SERVICE_HOST = "127.0.0.1"`（硬编码回环，永不 `0.0.0.0`）。

**端口常量**：Hub `8080`、Screenpipe `3030`、Core `8765`（`SERVICE_PORT`）。

## 依赖（`pyproject.toml`）

```
python >=3.11,<3.13
fastapi>=0.110.0 / uvicorn>=0.28.0 / pydantic>=2.6.0 / python-multipart>=0.0.9
pypinyin==0.55.0 / numpy>=1.24.0 / sounddevice>=0.4.6
sherpa-onnx>=1.10.0 / sherpa-onnx-core==1.13.8   # 显式 pin（R04/D22）
httpx>=0.27.0 / websockets>=12.0
dev: pytest>=8.0.0 / pytest-asyncio>=0.23.0
lint: ruff==0.16.8
```

## Rust（`apps/desktop-shell/src-tauri/Cargo.toml`）

`tauri 2.11` + `tauri-plugin-log 2` + `tauri-plugin-single-instance 2` + `tauri-plugin-global-shortcut 2` + `sysinfo 0.33` + `tokio 1` + `uuid 1` + `reqwest 0.12` + `chrono 0.4`（typify 需要）。

## 前端（`apps/desktop-ui/package.json`）

`vue ^3.5.13` / `pinia ^2.3.1` / `vue-router ^4.5.0` / `@tauri-apps/api ^2.2.0`；dev：`@vitejs/plugin-vue ^5.2.1` / `json-schema-to-typescript 16.0.0` / `typescript ^5.7.3` / `vite ^6.1.0` / `vue-tsc ^2.2.0`。

## 模型选择（本机实测，`benchmarks/`）

| 用途 | 模型 | 依据 |
|---|---|---|
| live ASR | SenseVoice | 科学术语纠正后 CER 0.180（paraformer 0.187 / qwen3-asr 0.220）；RTF 0.034；297 MB；0 MB VRAM |
| archive ASR | SenseVoice | 同上（常开录制必须便宜） |
| TTS | MeloTTS | zh_en 原生 44100 Hz |
| LLM | Hub 管理（当前 inventory 含 `Occamy-1.0` 21.1 GB） | Hub 是模型运行时权威 |

## Hub（外部）

- 路径：`D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\`
- 版本：**0.9.8.3**（与 pinned 一致，R32 实测确认）
- JRE：`java.base ... java.net.http`（JAVA_VERSION 26.0.2.1）
- 启动：`llama.cpp-hub.exe`（launcher）或 `jre\bin\javaw.exe -classpath ./classes;./lib/* org.mark.llamacpp.server.LlamaServer`
- **沙箱内无法启动**：JVM 死在 `McpClientService` 静态初始化（`java.net.SocketException: Invalid argument: connect` @ `sun.nio.ch.UnixDomainSockets.connect0`）——环境限制，非 Hub 故障

---

# DECISIONS_AND_RATIONALES

## 本会话新增决策

| # | 决策 | 理由 |
|---|---|---|
| 1 | 只提交「引入/迁移/验证」，保留 21 项删除类 | 计划 L1730/L1732 闸门 + L1646「不得一次性提交全部」 |
| 2 | `hub.bind_model` 返回 `accepted` 而非 `applied` | saga 是异步的；`applied` 会重蹈「谎报成功」 |
| 3 | 无事件循环时返回 `rejected` + `HUB_UNAVAILABLE` | 同步调用方必须被告知失败，不能给假成功 |
| 4 | B5 冲突**不改语义**，只让信号可见 | 计划 5.5 的 confirm 约束的是**停止**旧模型，不是加载新模型 |
| 5 | 冲突存 `pending_conflict` 独立字段 | `_update_status` 每次赋 `last_error`，写那里会被下次状态更新抹掉 |
| 6 | `config.hub_base_url()` 作单一来源 | R20 事故：同一事实 6 处副本，一处错 |
| 7 | Rust 保留一个端口常量 | Rust 无法 import Python，靠 R21 跨语言守卫保一致 |
| 8 | **`LLM_BASE_URL` 也用 `or` 而非 `,` 回落** | 环境变量显式设为空串时也要回落，避免端点变成 `"/v1"` |
| 9 | **`CaptureOperation` 而非布尔标志** | 布尔值无法表达「已请求但未应答」，而那正是必须拒绝 verified 的状态 |
| 10 | **超时在 `compute_privacy_scope` 读取时惰性求值** | 生产无 ticker；只在显式 tick 过期会让 operation 状态永远停在 pending |
| 11 | **executor 不读 mode，只接收 operation_id + intent** | 否则出现第二个权威，与 Hub 端口双源同型 |
| 12 | **`stopped_by_us` 标志** | `stop_spawned` 消费 handle 后移除所有权条目，否则 LVA 停掉的实例与从未见过的无法区分 |
| 13 | **Resume 三分支** | 无条件 `Applied` 会宣称不存在的 recorder 正在运行 |
| 14 | **capability 显式列 11 项而非 `core:window:default`** | 「授权 UI 实际调用的操作」与「放开一切」是不同主张 |
| 15 | **几何独立文件而非塞进 `AppSettings`** | 否则每次移动窗口都递增 `settings_revision`，作废用户正在进行的设置编辑 |
| 16 | **存原始位置而非 clamp 后位置** | clamp 需要下一次启动的显示器列表 |
| 17 | **`ensureEventSubscription` 先释放旧监听器** | 否则每次重载叠加，每个事件被处理两次 |
| 18 | **L463 在 Rust 命令层实现** | 既有 RED 已裁定 settings CAS 属 Rust 边界（L293 + L397） |
| 19 | **`playback.set_muted` 无需 CAS** | 输出控制，没有会被并发覆盖的 aggregate |
| 20 | **mute 期间 `play()` 丢弃而非入队** | 入队会让 unmute 播放用户已静音的语音 |

## 关于 DPAPI 密文（用户裁定）

用户于 2026-09-25 明确裁定：**那三个 DPAPI 都是捏造的**。

核实结果（`git show cf1c967:settings.json`）：

- 实际只有 **1 个非空密文** `cloud_api_key_enc`（358 字符，带 `dpapi:` 前缀）；
- `asr_api_key_enc` 与 `tts_api_key_enc` 都是**空串**；
- `services.json` 无任何 `_enc` 字段；`user_profile.json` 无密文；
- **此前多轮记录的「3 个 DPAPI 密文」有误**（实为 1 个）；
- 该串的 base64 头部含 **.NET `ProtectedData`** 的已知 ASCII 标记（`NcMnd8BFdERjHoAwE`，不复制完整值），而本项目 `dpapi_encrypt` 用直接 `CryptProtectData` + 自定义熵 `APP_ENTROPY = b"LocalVoiceAgent-DPAPI-Entropy-v2"`，输出**不带**该标记 → 该值**非本项目加密函数产生**。

**结论**：密钥轮换项**可关闭**——值为捏造，且跨用户/跨机器也无法用本项目的熵解开。

## 审查方已裁定的边界（不得推翻）

- **G1 PASS**（`docs/G1-FORMAL-VERDICT-2026-09-24.md`）：PR-003..008 全部通过；PR-004 按「方案 a」过门，L463 挂起不阻塞 G1（R31 已完成 L463 全合规）。
- **G1 缺 PR-003/004 正式收口**的说法**已被撤回**——G1 判据是 L1680「PR-003..008」，PR-003/004 已核验通过。
- **I21/I22 属 G2**（L1681），不是 G1。
- **PR-015 依赖 PR-005/014**（L1286），不是 PR-013。
- **PR-009 机制已存在**（`runtime.py` 的 Standby→managed-capture-off、Passive hard guard、snapshot 单调、TurnId），「PR-009 未实现」的说法**已被撤回**。

---

# FAILED_ATTEMPTS

## 本会话的失败与撤回（全部记录在案）

### 1. R28 — 假缺陷（正式撤回）

**做了什么**：探针显示本机 `zoneinfo` 无时区库（`tzdata` 未安装，`available_timezones()` 返回 0），`Asia/Shanghai` 解析抛异常。据此判定 `_resolve_timezone` 的 `except Exception: pass` 会**静默回落 UTC**，使 23:30 UTC 事件本地日算错一天（09-20 vs 09-21），并写 3 项 RED。

**RED 跑出 2 失败**，但核对调用链后确认**是测试越界，产品无此缺陷**：

| 位置 | 事实 |
|---|---|
| `screenpipe_importer/normalize.py` L24 | 生产写入的 `event_timezone` 是 **`UTC+08:00` 这种 offset 字面量**，不是 IANA 名；且**同时**给出 `utc_offset_minutes` |
| `worker.py` L95/L96 | 两者一并传入 repository |
| `repository.py` L28-29 | 名字解析失败后**回落到 offset**，不是回落 UTC |
| 全仓 grep | **无任何生产者写 IANA 名**（`Asia/`、`Europe/`、`America/` 在 src 零命中） |

实测四种形状：`UTC+08:00`/480 → 09-21 ✓；unknown name + 480 → 09-21 ✓；仅 offset → 09-21 ✓；仅 UTC → 09-20 ✓。

**撤回声明**：该假缺陷结论予以撤回。`_resolve_timezone` 的降级路径**正确**。我的失败断言传的是「IANA 名 + `offset_mins=0`」——**生产不可能产生的组合**。测试改写为 `test_red_timezone_anchor_shapes.py`（测试真正到达 repository 的四种形状）。

### 2. R28 — 三处测试断言错（产品正确）

写 `test_journal_lock_contention.py` 时三次猜错产品事实：

| # | 我的假设 | 实际 |
|---|---|---|
| 1 | `events` 有 `turn_id` 和 `current_text` 列 | 是 `turn_sequence`；`current_text` **是视图**（`schema.py` L109-115 `CREATE VIEW current_event_text`）不是基表列 |
| 2 | 新事件 `current_revision == 1` | **0** 才正确（「尚无修订，raw 文本仍权威」，`schema.py` L40 默认 0） |
| 3 | 中文子串可查 FTS | `_segment_text` 把 CJK **按字切分**（探针：`锁竞争后的` → `锁 竞 争 后 的`），子串查不中。改用 ASCII（CJK 短语精度另有 `test_cjk_fts_phrase_query_precision`） |

三处均为**测试断言错、产品正确**。按产品实际语义修正断言，未改产品。

### 3. R28 — `range_end - range_start` 整数相等断言

断言 `== 1 天`，实测差 **1 微秒**（实现用排他末端）。改为比较日边界（差 < 1 秒）。

### 4. R29 — capability 文件的尾随逗号（构建抓出）

我第一版把说明写在自定义的 `"comment"` 数组键里并带尾随逗号。**PowerShell 的 `ConvertFrom-Json` 接受该文件**（含尾随逗号），但 **Tauri 的解析器拒绝**：

```
failed to parse JSON: trailing comma at line 16 column 3
```

**教训**：本地用 PowerShell 校验 JSON 不足以证明 Tauri 能读。改为合法 JSON，说明并入 `description` 字符串，并加尾随逗号检测到 RED。

### 5. R30 — Node ESM 绝对路径（Windows）

初版测试用 `import * as g from "E:/…"`，Node 报：

```
Error [ERR_UNSUPPORTED_ESM_URL_SCHEME]: Only URLs with a scheme in: file, data, and node are supported
```

**Windows 上绝对 ESM specifier 必须是 `file://` URL**。改用 `Path.as_uri()`。

### 6. R30 — Tauri monitor API 落点错

初版调 `win.availableMonitors()` / `win.primaryMonitor()`，typecheck 报 `Property does not exist on type 'WebviewWindow'`。实际是 **`@tauri-apps/api/window` 的模块级函数**（`window.d.ts` L1805/L1817/L1839）。

### 7. R31 — 断言实现细节而非职责归属

最初 RED 断言 `CharacterView.vue` 必须出现 `onMoved`/`onResized`。实际订阅在 composable 中（Tauri API 调用属于那里），视图的职责是**启停**该订阅。改为检查 `watchPosition` + `persistCurrent`。

### 8. 迁移文档本身（本文件）

第一版把 Hub API key **明文写入**本文档，被自动审批审查拦截——**审查正确**，这违反项目自己的约束（密钥不得写入仓库/日志）。已改为不复制其值。

### 9. 环境级失败（非代码问题）

| 尝试 | 结果 | 原因 |
|---|---|---|
| 沙箱内启动 Hub（`javaw.exe`） | 失败 | JVM 死在 `McpClientService` 静态初始化：`java.net.SocketException: Invalid argument: connect` @ `sun.nio.ch.UnixDomainSockets.connect0` |
| 提权 `Start-Process javaw.exe` | 被拒 | 审批返回「操作已被用户取消」 |
| 官方 launcher `llama.cpp-hub.exe` 提权启动 | JVM 同样死在同处 | 同上 |
| 换可写临时目录 `-Djava.io.tmpdir` | 被拒 | 审批拒绝 |
| `cargo check` 直接跑（沙箱内） | 失败 | `拒绝访问 (os error 5)`——需写 `gen/schemas` 生成产物；提权后通过 |
| `npx vite build` 直接跑 | 失败 | `EPERM: open 'node_modules\.vite-temp\…'`；提权后通过 |
| `git add` 直接跑（沙箱内） | 失败 | `fatal: unable to write new index file`（E 盘索引需提权） |

### 10. 前序会话的失败（须记住，勿重犯）

| 事故 | 掩盖方式 | 状态 |
|---|---|---|
| 8089 端口（R08 引入） | Rust 单测夹具用**同一错端口** | R20 已修 |
| version 信封（R14 引入） | fixture 用**同一错假设** | R22 已修 |
| saga 死路（R15 引入） | 测试**直调** `switch_model`，dispatch 路径从未走过 | R23 已修 |
| **Output Mute 只改本地 ref** | 既有 RED 只断言 handler 不调 `setMode`、标签正确，**从未断言声音停止** | R30 已修 |

**共同点：测试绕过了真实调用路径。** 审查方据此新增基线检查项③（命令→分发→真实调用链追踪）。

### 11. 更早的撤回（前序会话，见 `docs/AUDIT-REVIEW-2026-09-24.md` §7）

- 「FROZEN 实为 1,352 行而非 1,858 行」——**撤回**。根因：该文件无 BOM，PS 5.1 的 `Get-Content` 默认按系统 ANSI（本机 GBK）解码，GBK 双字节序列吞掉部分 `0x0A`。**1,858 行是物理事实**。教训：对该仓库任何文本的行数测量必须显式 `-Encoding UTF8`。
- 「`service_registry.rs` 不存在」——**修正**：该文件存在（1,225 B，2026-09-21），但当时是**死代码**（`update_status`/`get_all_services` 无调用方）。
- 「R15 引用是幻影」——**撤回**：该引用真实存在于 `C:\Users\a.gide\Documents\Codex\…\CONTEXT-HANDOFF-2026-09-22.md`（L343/L356/L1219），在我的搜索根之外。

---

# BUGS_AND_WORKAROUNDS

## 环境陷阱（全部踩过，必须遵守）

| # | 陷阱 | 对策 |
|---|---|---|
| 1 | **E 盘对沙箱只读** | 写 E 盘用 `apply_patch`；`git` 写操作、codegen 写制品、`cargo` 写 `gen/`、`vite build`、新建嵌套目录、改 D 盘配置**都需 `require_escalated`** |
| 2 | **提权命令以另一用户运行**（`CodexSandboxOffline`） | 纯 `git status` 会报 `dubious ownership` 失败；**必须始终**用 `git -c safe.directory=E:/AI/LocalVoiceAgent -C E:/AI/LocalVoiceAgent …` |
| 3 | `PYTEST_ADDOPTS=--basetemp=…` | **必须用正斜杠**（反斜杠被吞） |
| 4 | RED 失败工件写入 E 盘被拒 | 设 `LVA_TEST_ARTIFACT_DIR` 到 X 盘可写目录 |
| 5 | Rust 测试 exe 无法启动（`0xC0000139 STATUS_ENTRYPOINT_NOT_FOUND`） | 需**内嵌 Common-Controls 6.0 清单**（`mt.exe`）**且** `WebView2Loader.dll` 同目录。脚本：`X:\Codex\State\visualizations\2026\09\23\01a0cd49-18d6-79c1-afd6-41261b729efe\scratch\rusttest.ps1`，用法 `$env:TEMP_ROOT='<scratch>'; & rusttest.ps1 -SourceExe <exe> -Repeat 1` |
| 6 | 同一根因两种呈现 | `0xC0000139` 在有控制台宿主时直接退出，在某些会话宿主下弹模态错误框**等待交互而表现为挂起**。**先查进程是否存活再查退出码** |
| 7 | Rust 构建需 PATH | 前置 `E:\AI\LocalVoiceAgent\tools\w64devkit\bin`；`CARGO_TARGET_DIR` 指 X 盘；加 `--offline` |
| 8 | **PS 5.1 `Get-Content` 无 `-Encoding UTF8` 会 GBK 误解码** | 行数测量必须显式 `-Encoding UTF8`（曾导致错误的「1,352 行」结论） |
| 9 | `apply_patch` 无法创建嵌套目录 | 先建目录，或让补丁写已存在的父目录 |
| 10 | 正则里引号易导致 patch 语法失败 | 用字符类 `["']` 或把整个 patch 用数组拼接 |
| 11 | `apply_patch` 标记行 | 必须以 `*** Begin Patch` 开头、`*** End Patch` 结尾，各自独占一行且**无多余星号** |
| 12 | PowerShell JSON 校验不够 | `ConvertFrom-Json` 容忍尾随逗号，Tauri 不容忍——**capability/tauri.conf 类文件必须以 Tauri 构建验证** |
| 13 | Node ESM 绝对路径 | Windows 上必须是 `file://` URL（`Path.as_uri()`） |
| 14 | Hub 无法在沙箱内启动 | 需用户在沙箱外启动（见 FAILED_ATTEMPTS §9） |

## 已知技术债（未修，均有记录）

| # | 项 | 位置 | 说明 |
|---|---|---|---|
| B8 | `if False:` 死代码 | `runtime.py` | R20 已删 |
| B9 | LIKE 模式未转义 `%`/`_` | `recall.py` L125 | 非注入（已参数化），属功能怪癖；**改它会改变搜索语义，待裁决** |
| B10 | `list_loaded` 失败 → `loaded_models=[]` 落空 → 旧模型不会被停（VRAM 双开，fail-open） | `hub_runtime.py` L97-99 | 有 warning；建议补显式注释 |
| — | `_ws_ask` 形式绕行 | `server.py` L615 | 逻辑已收敛同路径；记入 PR-037 清理清单 |
| — | `ProcessManager` 重复所有权模型 | `process_manager.rs` | 与 `supervisor.rs` 各有一套；`unload_vram`/`cold_start_llm`/`switch_model` 为空壳；计划归 PR-015/PR-037 |
| — | `tray.rs` 仍有 direct model/process action | `tray.rs` | 归 PR-031（L1447「移除 direct model/process actions」） |
| — | `probe_screenpipe_capability()` 恒返回 `version_known: false` | `lib.rs` | 见 ASSUMPTIONS |
| — | `CaptureSpawner` 未注入 | `lib.rs` | 「LVA 停掉 → 恢复」返回 `Failed` |

---

# ASSUMPTIONS

## 待验证假设（未经验证即视为假设，不得当作结论）

| # | 假设 | 验证方式 |
|---|---|---|
| A1 | **Screenpipe 没有版本契约** → `probe_screenpipe_capability()` 恒返回 `version_known: false`，故 Adopted 实例当前一律判为不可控 | 需真实 Screenpipe 的 `/version` 响应形状；在拿到前把版本判定写成「总是已知」就是用错误假设写夹具（R14 version 信封事故同型） |
| A2 | **capability 修复使窗口操作可用** | ACL 层已通（`cargo check` 通过），但真实 Tauri 下 `setIgnoreCursorEvents`/`startDragging`/`setPosition` 返回成功**未验证** |
| A3 | **`NullPlayer` 与真实 `Player` 语义一致** | 已保持同形（generation、flush、mute、pending 模拟墙钟），但真实声卡的静音行为未验证 |
| A4 | **单显示器环境下 clamp 正确** | 多显示器分支只有 Node 级证据（本机 `\.\DISPLAY5` 1707x1067，缩放 150%） |
| A5 | **WAL 下读者不被写者阻塞** | R28 已测（4 项锁竞争测试），但未做长时间并发压测 |
| A6 | **真实 IANA DST 跳变日行为正确** | 未测试；因无代码路径存 IANA 名（见 FAILED_ATTEMPTS §1） |
| A7 | **Hub 重启后 attestation 会重新验证** | §5.8 要求，但只观测过一次运行中的 Hub |

## 已确认的事实（非假设）

- Hub 版本 **0.9.8.3**（R32 实测 `tag`/`version` 均为 `0.9.8.3`）；
- `classify_version('0.9.8.3') = READY`（R32 实测）；
- `probe_handshake() = READY`、`supports('models.load') = True`（R32 实测）；
- `VERIFIED_LOOPBACK` → `control_allowed = True`（R32 首次实测）；
- `sherpa-onnx-core==1.13.8` 已装（`.venv`）；
- 三个生成制品与 codegen 一致（`--verify` verified）。

---

# RISKS

| # | 风险 | 触发/影响 | 缓解 | 现状 |
|---|---|---|---|---|
| R1 | **工作树 23 条未提交** | 磁盘故障即丢失 | 已提交 15 个 commit；删除类按闸门等待 | **已大幅缓解**（早期 243 条 → 现 23 条且均为闸门等待项） |
| R2 | **Hub 配置与运行态不一致** | 文件 `0.0.0.0`、进程 `127.0.0.1`；下次重启会暴露到 LAN | 还原备份在档；需用户决定长期策略 | **活跃** |
| R3 | **大量验证仍是 fixture 级** | 真实 Hub/声卡/GUI/多显示器行为可能不同 | R32 已打开首个真实门；PR-035 全量门禁 | **部分缓解** |
| R4 | **attestation 新鲜度依赖 Rust reporter** | 一次性 VERIFIED 不能永久授权（`revalidate_after` 是截止时间） | 已有 30s 周期 + 90s 截止（R16）；真实送达未验证 | 中 |
| R5 | **`hub.bind_model` 真实切换未验证** | 即使门已开，切换链路可能仍有断点 | 需一次真实模型加载 | 中（条件已具备） |
| R6 | **密钥历史** | `cloud_api_key_enc` 曾入 HEAD 并已推送 | **用户裁定为捏造，可关闭** | **已关闭** |
| R7 | **测试绕过真实路径（第 4 次同型）** | Output Mute 类缺陷可能仍有 | 审查方基线检查项③（命令→分发→真实调用链追踪） | 持续 |
| R8 | **Hub API key 明文存于配置文件** | 若 Hub 绑 `0.0.0.0`，key 保护的管理面暴露到 LAN | 保持回环绑定 | 中 |

---

# NEXT_ACTIONS

## 立即可做（无需新授权）

1. **真实模型加载验证**（条件已具备：`control_allowed = True`）：加载 `Occamy-1.0` 或更小模型，走 `hub.bind_model` 全链路，验证 PR-014 的 saga 真实行为与 `X-LVA-Bound-Model` 头。
2. **PR-026 Hub model UI**（依赖 PR-014/023/025 均就绪，L1392-1400）。
3. **PR-028 Chat / PR-029 Memory / PR-027 Hearing-Speech**（骨架已在，需补功能与验收）。
4. **PR-032 Services/Diagnostics**（骨架已在）。

## 需要用户决定

5. **Hub 长期绑定策略**（回环常驻 vs 回到 `0.0.0.0`）。
6. **B9（`recall.py` LIKE 未转义）** 是否修改——会改变搜索语义。
7. **是否授权 `capture.ack` 命令面**（Rust→Core 的 operation 回执，需新增命令类型 → 契约 + codegen）。

## 后续 Wave

8. **PR-035 全量门禁**（fault + migration + 2h/8h/12h soak + UX）——Wave 6。
9. **PR-036 OLV 删除**（L1730 闸门，17 个文件）→ **PR-037 Core facade 删除** → **PR-038 Legacy UI 删除**（L1732 闸门，3 个文件）——Wave 7，严格串行。

---

# CRITICAL_CONTEXT

## 硬约束（用户设定，违反即失败）

1. **不得 `git add/commit/push/reset/checkout/clean`** —— 除非用户显式授权（本会话已多次授权 commit+push，且明确说「你来执行 push」）；
2. **不得弱化/跳过/xfail RED 断言**；
3. **不得手改三个生成制品**（`schemas/lva-ipc-v1.json`、`apps/desktop-ui/src/generated/lva-ipc.ts`、`apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs`）—— 只能由 `codegen.py` 生成；
4. **不得用 F2**（后处理生成制品）/ **F3**（更换生成器）；
5. **禁用 Astra**；
6. **不得改写冻结计划或任何历史报告**（包括自己写错的报告——「不重写历史」，错误在新报告中更正）；
7. **不得删除 `.venv` / `venv` / `benchmarks/`**；
8. **交付报告必须放 `E:\AI\LocalVoiceAgent\docs\`**（X 盘只放可丢弃的 scratch）；
9. **计划 L1730/L1732 + CONTEXT-HANDOFF L1646：21 项 ` D` 删除类不得提交**（OLV 属 PR-036、旧 HTML 属 PR-038、`scripts/llm_serve.py` 属 PR-015 门）；
10. **密钥不得写入仓库/日志/报告**（本文件因此不复制 Hub key 值）。

## AGENTS.md 指令

保持客观公正，不阿谀奉承；输出前自检一次，发现问题先修正再输出；不因自检额外启动工具/测试/独立复审。即使我表达不满或使用粗话，也依据证据判断：你错了就纠正；有证据支持原判断时，平静说明理由，不因措辞本身争辩。完成本次范围及必要验证后结束。仅在新增修改、失败或未解决风险出现时扩大或重复检查；已授权范围内继续执行，不因固定轮次再次请求确认。

## 模型分工（本项目实际使用）

| 角色 | 模型 | 职责 |
|---|---|---|
| **执行方** | **DeepSeek** | 实现切片、写 RED、跑测试、写执行报告（`docs/R<NN>-EXECUTION-REPORT-*.md` 的「执行者」字段均为 DeepSeek） |
| **审查方** | **Claude** | 独立复核实现方声明；出具正式验收裁决（`docs/DESKTOP-SHELL-P3-PLAN-REVIEW.md` 的「评审方：Claude（独立评审）」；`docs/PR-016-019-FORMAL-ACCEPTANCE-2026-09-24.md` 的「独立审查方（非实现方）」）；有权撤回自己的错误结论 |
| **Codex（本会话）** | — | 承接 DeepSeek 的执行位（本会话所有 R25–R32 报告的执行者字段） |
| **Gemini** | — | **在 `docs/` 中零命中**。计划早期版本曾提及「deepseek key 已泄露」的无实证断言（`ARCHITECTURE-PLAN-2026-09.md` L5/L109/L462/L858/L932），该文件已被标注为「保留仅作历史记录与修订脉络」 |

**协作模式**：执行方交付 → 审查方独立复核（复跑测试、回源码核实、发现不实即记录）→ 用户裁决。审查方的撤回记录见 `docs/AUDIT-REVIEW-2026-09-24.md` §7。

## 关键参考路径

| 项 | 路径 |
|---|---|
| 仓库 | `E:\AI\LocalVoiceAgent` |
| 冻结计划（外部原件） | `C:\Users\a.gide\Documents\Codex\2026-09-20\new-chat-2\outputs\ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md` |
| 冻结计划（仓内副本） | `E:\AI\LocalVoiceAgent\docs\ARCHITECTURE-PLAN-2026-09-v1.2.1.md` |
| 沙箱 scratch | `X:\Codex\State\visualizations\2026\09\24\01a0d1af-f9e3-7363-a069-646071746e51\verify\` |
| Rust 测试脚本 | `X:\Codex\State\visualizations\2026\09\23\01a0cd49-18d6-79c1-afd6-41261b729efe\scratch\rusttest.ps1` |
| Hub 安装 | `D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\` |
| Hub 配置 | 同上 `\config\application.json` |
| 真机探针 | `E:\AI\LocalVoiceAgent\scripts\probe_real_hub.py`（用法 `python probe_real_hub.py 8080`） |
| 环境探测 | `E:\AI\LocalVoiceAgent\scripts\probe_engines.py`、`probe_attestation_e2e.py` |

## 计划关键行号（必须引用准确）

| 行 | 内容 |
|---|---|
| L293 | 权威矩阵：Secrets 属 Rust settings/OS 保护层 |
| L321 | Output Mute 只停止/抑制 speaker playback |
| L397 | `settings_revision` 在 Rust public DTO，不进全局 RuntimeState CAS |
| L459-466 | CAS 矩阵 |
| L463 | settings update/clear secret → required `settings_revision` |
| L470-479 | **首版命令清单**（封闭列表） |
| L527 | Hub 默认入口 8080，child 8081+ |
| L579 | wildcard/non-loopback → `HUB_CONTROL_UNSAFE`，management disabled |
| L636 | 任一步失败 → `FAILED/DEGRADED`，旧 turn 不可复活 |
| L665 | 只有 `VERIFIED_LOOPBACK` 允许 load/stop/switch control |
| L989 | Controls Island 五项；Output Mute tooltip 必须说明麦克风与录制不变 |
| L987-995 | §8.4 UX rules |
| L1173 | PR-004：`get_public_settings` 只返回 configured flag + `settings_revision` |
| L1213 | PR-008 Steps：listener table、control-port↔Hub process 关联、typed bind attestation |
| L1234 | PR-010 Dependencies = PR-009 |
| L1256 | G 消费 B 提供的 typed attestation |
| L1286 | PR-015 Dependencies: PR-005/014 |
| L1330-1338 | PR-020（隐私捕获协调器） |
| L1340-1348 | PR-021（capture executor） |
| L1362-1381 | PR-023/024/025 |
| L1432-1450 | PR-030/031 |
| L1535-1556 | Wave 表 |
| L1580-1610 | I01–I22 不变量 |
| L1680 | G1 判据 = PR-003..008 |
| L1681 | G2 判据（含 I21/I22） |
| L1704 | Tauri/WebView2 overlay 差异风险 |
| L1728/L1730/L1732 | 删除门：`scripts/llm_serve.py` / OLV / 旧 HTML |
| L1854 | 开工顺序（Wave 1 是底座） |

## 三次「同型缺陷」的教训（本会话最重要的元知识）

| 事故 | 掩盖方式 |
|---|---|
| 8089 端口（R08 引入，R20 修） | Rust 单测夹具用**同一错端口** |
| version 信封（R14 引入，R22 修） | fixture 用**同一错假设** |
| saga 死路（R15 引入，R23 修） | 测试**直调** `switch_model`，dispatch 路径从未走过 |
| Output Mute 只改本地 ref（R29 发现，R30 修） | 既有 RED 只断言 handler 不调 `setMode`，**从未断言声音停止** |

**共同点：测试绕过了真实调用路径。** 审查方新增基线检查项③（命令→分发→真实调用链追踪）已被证实必要。**新会话在写测试时必须问：这条断言是否真的走过了产品路径？**

## 本轮会话自身犯过并已更正的错误（勿重犯）

- `HUB_CONTROL_PORT = 8089`（R08 引入；且 R08 报告**错误归因**说它来自 `process_manager.rs`——实际那里是 8080）；
- `probe_real_hub.py` 初版**重犯**了 version 顶层读取错误；
- `server.py` 补丁造成缩进错位（`control_client=` 被错误缩进）；
- 补丁留下重复的 `def rollback` 行 → `IndentationError`；
- 报告数字 `unit 8` 长期抄错（实际**一直是 43**，R28 后为 47）；
- R20 的 `-uall` 计数用了 `2>&1` 把 stderr 2 行 warning 计入（真值 243，我写 245）；
- 迁移文档第一版把 Hub API key 明文写入（被自动审查拦截，**审查正确**）。

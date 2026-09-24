# R07 执行报告 — Wave 1 / PR-007 Rust CoreSupervisor and bridge

- 日期：2026-09-24（Asia/Shanghai，UTC 2026-09-23 17:08 起）
- 执行者：DeepSeek（接管 `LocalVoiceAgent-R04-DeepSeek-Handoff-2026-09-23.md` 之后的第三片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 工作树：`status --porcelain=v1` = **84 行**；`-uall` 口径 = **242 行**
- 范围来源（三处独立一致）：冻结计划 §2.3（L252-272）与 PR-007（L1198-1206）、`tests/red_v121/README.md` 映射表、R05 报告第 8 节排期
- 冻结验收原文（计划 L1205）：child spoof、超时、崩溃、重启、event gap；WebView devtools 看不到 endpoint/token
- 冻结步骤原文（计划 L1203）：生成 token/nonce；pipe child；验证 READY；持有单 WS；command correlation/event forwarding；restart rotate

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 目的 | 字节 | SHA256 |
|---|---|---|---|---|
| `apps/desktop-shell/src-tauri/src/bridge.rs` | **整体重写**：删除 HTTP `POST /api/command` 与 250 ms `GET /api/events` 轮询，改为唯一 authenticated WS；新增 command correlation、快照请求/发布、gap 检测、instance 变化处理、可中断指数退避重连 | 单一 Rust↔Core 通道 | 42290 | `06b548cb07215ea5425b93cca5ce698d845e5d8ccafd49c8ce876848d15ca119` |
| `apps/desktop-shell/src-tauri/src/core_supervisor.rs` | `#[derive(Debug, Clone)]` → `#[derive(Debug)]`；新增 `pub bootstrap_stdin: Option<ChildStdin>`；`spawn_core` 不再 `drop(stdin)`，改为长期持有 | Core 把 stdin EOF 当孤儿信号（见 1.1） | 7142 | `e2c6204c00ce764915cb69bce9de1cf763052dd7e8c80a76453294e206c63d89` |
| `apps/desktop-shell/src-tauri/src/lib.rs` | `send_core_command` 改 async + `spawn_blocking`；`attach_app`/`start` 接线；`std::thread::spawn` 内 `spawn_core` → `set_instance`；删除旧 `start_event_forwarder` | 不让阻塞 WS 调用卡住 WebView IPC 线程 | 12301 | `f51c8f410ebb9f8373afb268c4597b83743ec4715c50939fbdbb924c50e82ad7` |
| `apps/desktop-shell/src-tauri/src/ws.rs` | 上一会话创建，**本轮未改**（仅作为 bridge 的传输层被调用） | 手写纯 Rust WS 客户端 | 23007 | `858b3b311e3d4231b74b0a399da5844e09777b50526e53c9c7d6c63249f4acfd` |

未修改：三个生成制品（SHA256 见第 6 节第 12 条）、冻结计划与历史报告、任何 RED 断言、`Cargo.toml`/`Cargo.lock`（本轮零新增依赖）、`src/lva` 下任何 Python 产品代码、前端 `apps/desktop-ui/src` 任何文件。

### 1.1 关键修复语义

`bridge.rs` 现在是 Core 的唯一入口。常量：`CONNECT_TIMEOUT=5s`、`COMMAND_TIMEOUT=10s`、`READ_TICK=20ms`、`IDLE_WAIT=200ms`、`RECONNECT_MIN=500ms`、`RECONNECT_MAX=10s`（L35-40）。内部状态 `BridgeInner{instance, connected, runtime_instance_id, last_sequence, pending, shutdown}`（L55），`Pending` 分 `Caller(Sender<Value>)` 与 `Snapshot` 两类（L49）。

命令路径：`send_command`（L174）在未连接时直接返回 `Err("LVA Core is not running")` / `Err("LVA Core bridge is not connected")`，不排队重放；`command_key`（L518）在缺 `command_id` 时注入 UUID。结果按 `command_id` 在 `resolve_command`（L384）配对；未配对的结果被丢弃，**永不重放**。

事件路径：`handle_text`（L310）先按 `kind` 分流——`command_result` 走 correlation，`hello`/`pong`/`ask_result` 忽略。**无 `sequence` 或 `/payload/type` 的事件一律 `log::debug!` 丢弃、不转发**（L340-348，理由见第 6 节第 4 条）。带 `sequence` 的事件做 gap 检测（`last>0 && seq>last+1` → 请求快照），`runtime_instance_id` 变化则清空 pending、重置 `last_sequence`、请求快照（L350-380），随后 `emit` 到 WebView 的 `lva://event`。

`publish_snapshot`（L424）把 Core 的扁平快照包装成 `{"schema_version":"1.0","type":"runtime.snapshot","source":"core.bridge","sequence":0,"runtime_instance_id":…,"payload":{"type":"runtime.snapshot","state":<data>}}` 再 emit，与前端 `stores/runtime.ts` 读取的扁平 `data` 形状一致。

`core_supervisor.rs` 的 stdin 改动是**对冻结计划的刻意偏离**，依据是产品代码事实：`src/lva/__main__.py` L31-51 `_watch_bootstrap_stdin()` 把 stdin EOF 当作"父进程已死"并 `os._exit(0)`。计划 L256 要求"写完一行即关闭 write side"，两者不可能同时成立（第 6 节第 5 条给出实测）。

---

## 2. 本轮实测通过

| 项 | 命令要点 | 结果 |
|---|---|---|
| Rust 编译 | `cargo test --offline --lib --no-run --manifest-path …\src-tauri\Cargo.toml`（`CARGO_TARGET_DIR` 指 X 盘 scratch） | 成功；产物 `cargo-target-w64\debug\deps\lva_pet_lib-34dbd2f73fe141b2.exe`（202,438,843 B，SHA256 `d978b08d1b02e4a05f2c587c431571b88b7f2a644a3f6c2af0efb0613283197b`） |
| Rust 单测（全量） | `rusttest.ps1 -SourceExe <exe> -Repeat 3` | **3× `ok. 29 passed; 0 failed; 1 ignored`**，`EXIT=0`。iter1 `stray_ping=2`（哨兵进程计时抖动，iter2/3 为 0，非失败） |
| **互操作探针（真实 `/ws`）** | 同上 `-- --ignored --nocapture --test-threads=1`，env `LVA_PROBE_PORT=59301`/`LVA_PROBE_TOKEN`/`LVA_PROBE_PORT2=59302`/`LVA_PROBE_TOKEN2` | **EXIT=0, 1 passed**（详见 2.1） |
| `tests/invariants` + `tests/integration` | pytest | **34 passed** |
| `tests/red_v121` | pytest | **5 failed / 136 passed**；`test_red_authority.py` 6 项中 5 failed / 1 passed（`test_no_hub_management_client_outside_core`），其余 14 个测试文件全绿 |
| `run_groups.py --layer v12` | | 7 组全 PASS：contract 5 / invariants 23 / unit 8 / fault 7 / integration 11 / migration 2 / ux 11，`EXIT=0` |
| ruff `E4,E7,E9`（`src/lva` + `tests/run_groups.py`） | | All checks passed（**不得宣称"全量 lint 通过"**） |
| 前端 `npm run typecheck` | 在 E 盘源码副本（X 盘 `ui-build`，与 E 盘 `src` 逐文件 SHA256 一致，28/28） | `EXIT=0` |
| 前端 `npm run build` | 同上 | 成功：88 modules，`index-DRckcx7K.js` 145.16 kB / gzip 54.09 kB，1.88 s |
| 构建产物 endpoint/token 泄漏检查 | 正则 `ws://\|wss://\|127\.0\.0\.1\|:8765\|/api/events\|/api/command\|new WebSocket` 与 `Authorization\|Bearer ` 扫 `dist/` 全部 9 个 js/css/html | **全部 NONE**（含 pixi/live2d 第三方包） |
| 前端源码 endpoint/token 泄漏检查 | 同一正则扫 `apps/desktop-ui/src` 全部 28 个文件 | **0 命中** |
| 前端决策逻辑 Node 可执行性 | `node mt_check.mjs` 导入真实 `modeTransition.js` | 4/4 分支符合预期 |
| 真实 Core 子进程 bootstrap 握手 | `probe_r07_alive.py`（默认 `LVA_ROOT`） | READY 行正常：`LVA_READY {"protocol_version":1,"port":64954,…}`；stdin 保持打开时 child 2.5 s 后仍存活 |

### 2.1 进程级互操作探针明细（真实 uvicorn + 真实 `/ws` 路由）

探针服务端 `probe_r07_ws_server.py` 只替换 `VoiceCore`（本机无音频设备、缺 MeloTTS 模型），`/ws` 路由、Origin/token 门、4403 拒绝、hello 帧、`RuntimeController.execute_command` 全是生产路径。数据根 `LVA_ROOT` 重定向到 scratch，每次运行前移走 SQLite WAL 以保证 revision 基线干净。

实测原文（`probe-interop-clean.err.txt`，端口 59301/59302）：

```text
[probe] connected to the live /ws route on port 59301
[probe] snapshot status="applied" version=0 mode="standby"
[probe] live runtime_instance_id=a51f8104-c823-42db-9ccf-fe17115a8a9c
[probe] stale set_mode status="rejected" code="STALE_REVISION"
[probe] set_mode status="applied" snapshot_version=2
[probe] wrong-token connected=false
[probe] rotated snapshot instance="e26c6fa9-42c2-4d29-a5dc-8492f8d64c22" mode="standby"
[probe] events seen = 2
[probe]   event type="runtime.snapshot" sequence=0
[probe]   event type="runtime.snapshot" sequence=0
```

逐项对应冻结验收（L1205）：

| 验收项 | 探针证据 | 判定 |
|---|---|---|
| command correlation | 快照与两条 `set_mode` 都按 `command_id` 收到配对结果（含被拒的那条仍是有结果的相关结果） | 通过 |
| Core 侧 CAS 拒绝可透传 | stale `revision:999` → `status="rejected"`, `error.code="STALE_REVISION"` | 通过 |
| 快照真机测试 | 真实 `runtime.get_snapshot` 返回 `status="applied"`、扁平 `data.mode` | 通过 |
| token 门（生产代码而非探针） | 错 token → `is_connected=false`（真实 `/ws` 拒绝） | 通过 |
| restart rotate | 换端口+token+instance 后同一 bridge 采用新 Core 并重新发布快照，`runtime_instance_id` 与旧值不同 | 通过 |
| event gap | **stub 级**：`an_event_gap_triggers_a_snapshot_resync` 通过；真机未触发（见第 6 节第 4 条） | 部分 |
| child spoof | **stub/单测级**：`a_spoofed_accept_hash_is_refused` 通过；`core_supervisor.rs` L142 nonce 不匹配即 kill | 通过（非真机） |
| 超时 | `spawn_core(20s)` 超时 kill child（`core_supervisor.rs` L95-98）；bridge `COMMAND_TIMEOUT=10s` | 通过（代码级 + 单测） |
| 崩溃恢复 | `a_dropped_connection_is_re_established` 通过（stub 连接被断开后重连） | 通过（非真机） |
| WebView devtools 看不到 endpoint/token | 构建产物 + 源码正则双查 NONE；前端只经 `invoke('send_core_command')` 与 `listen('lva://event')` | 通过 |

---

## 3. 本轮实测失败 / 未达成

| 项 | 结果 | 说明 |
|---|---|---|
| 真实 Core 子进程完整启动（默认 `LVA_ROOT=E:\AI\LocalVoiceAgent`） | **失败（环境限制）** | `sqlite3.OperationalError: attempt to write a readonly database`（`journal/repository.py:50` → `journal/schema.py:135`），`Application startup failed`。E 盘产品树对当前沙箱只读 |
| 真实 Core 子进程完整启动（`LVA_ROOT` 重定向到 scratch） | **失败（缺模型）** | bootstrap 握手成功、READY 行正常，但 `lifespan` 内 `tts.py:138` `Load model from …\models\melotts\model.onnx failed` |
| 真机 event gap 恢复 | 未取得 | 生产代码当前不产生任何 typed 事件（第 6 节第 4 条），无法构造真实 gap |
| 真机 runtime_instance_id 变化触发 | 未取得 | 同上；rotated 探针覆盖的是"换 Core 后重新发布快照"，不是"同一连接内 instance 变化" |
| 本轮初次探针运行 | **探针缺陷，已修** | 初版用 `"mode": "active"`，生产 `Mode` 枚举只有 `standby\|passive\|live\|privacy_pause`，`CommandEnvelope` 校验失败后 `server.py` L473-475 只 `log.warning` 不回复 → 10 s 超时。**属探针缺陷，非 bridge 缺陷**，已改为 `"live"` |
| 本轮第二次探针运行 | **状态污染，已重跑** | 未重启服务端，`revision:0` 已被前次推进到 1，`set_mode` 返回 `rejected`。移走 WAL + 重启服务端后恢复干净基线 |

---

## 4. 未运行 / N/A（不得记为 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| 前端 Vue/Pinia 端到端（真实 WebView 内跑通事件流） | 未验证 | 需要可启动的 Tauri 应用 + 可启动的 Core，本机两者都受限 |
| soak `--duration 7200` 长跑 | 未运行 | 未排期 |
| Tauri release 构建 | 未运行 | 本轮只跑 `cargo test --lib`，未跑 `tauri build` |
| 三个 workflow 的 GitHub Actions 实跑 | 未运行 | 未推送 |
| 真实麦克风/扬声器声学验收 | 未运行 | 本机无音频输入设备 |
| 多显示器 DPI/scale | N/A | 仅 1 台显示器（1707x1067 @144DPI） |
| GUI 交互类 spike（透明/点击穿透/托盘菜单实际点击） | 未验证 | 沿用 R04/R05 状态，本轮无 GUI 改动 |
| `tests/red_v121` 之外的 v1.2 全层回归 | 已跑 | 见第 2 节 `run_groups.py --layer v12` |

---

## 5. 需裁决 / 需记录的残余项

### 5.1 `bridge.rs` 丢弃无 `sequence` 的事件是行为变更

`PL.VoiceCore(on_event=_broadcast)` 那条通道（`server.py` L54）发出的是 `kind + ts + flat data`，没有 `sequence`，也没有 `/payload/type`。新 bridge 丢弃它（L340-348）。前端 `stores/runtime.ts` 的 `handleEvent` 本来就只处理 typed envelope，因此**当前无功能损失**；但这意味着旧通道上任何未来新增的事件类型都不会到达前端。需要裁决：是让 Core 把该通道升级为 typed envelope，还是在 bridge 侧显式转换。本轮未改。

### 5.2 `runtime_instance_id` 双源不一致（真实差异，未自行修正）

`bootstrap.py` L18/L56 生成一个 `uuid4` 并经 `__main__.py` L90 放进 `LVA_READY`；但 `server.get_runtime()`（L101-108）新建 `RuntimeController` 时**不传**该 id，`runtime.py` L46 `runtime_instance_id or uuid4()` 再生成一个。实测 `IDENTICAL = False`（`probe_r07_instance_id.py`：`396cdca2-…` vs `b0c33de2-…`）。后果：`bridge.set_instance` 写入的是 `LVA_READY` 的值，首个带 `runtime_instance_id` 的 typed 事件会与之不等 → bridge 误判 instance change、清 pending、重发快照。因生产代码当前不产生 typed 事件，实际只影响一次多余的快照重发。**属 R06/R07 交界，本轮只报告。**

### 5.3 `tests/red_v121/test_red_bootstrap.py` 已全绿，与 R05 报告的排期记载不符

R05 报告第 8 节写"剩余 27 项 RED 分布：R06 bootstrap 6、R09 authority 5、R10、R12、R13 capture 3、R14 output_mute 4、redaction 4、temporal_mention 4、snapshot 1"。实测当前 `tests/red_v121` 只剩 `test_red_authority.py` 5 项红，其余全部转绿（逐文件：auth 8、bootstrap 6、capture 7、contract_cas 47、output_mute 5、redaction 5、snapshot 3、temporal_mention 4、bridge_mock 6、codegen 5、harness_selftest 12、mode_transition 6、review_blockers 19、soak_gate 2）。R06/R08/R12/R13/R14 的产品改动已存在（如 `__main__.py` L88 `bind_socket()`、L93 `_watch_bootstrap_stdin()`、`services.default.json` 的 `serve` 子参数、`ControlsIsland.vue` 的 `Output Mute / 静音播放`、`runtime.ts` 的 `setMuted`/`mutePlayback`）。**R06 没有执行报告**（`docs/` 只有 R04/R05/G0/S-UI-01），且 R05 末尾仍写"下一片为 R06"。本轮不代写 R06 报告，只记录该缺口。

### 5.4 `scripts/start-all.ps1` 仍以 `-m lva` 启动并写死 8765

L90-97：`Get-NetTCPConnection -State Listen -LocalPort 8765` 与 `-ArgumentList "-m lva"`。与 `services.default.json` 的 `["-m","lva","serve","--bootstrap"]` 及端口 0 不一致。属 R06 范围遗留，本轮未改。

---

## 6. 差异报告（只报告，未自行修正）

1. **R06 报告缺失**：见 5.3。`*R06*` 在仓库内只匹配到 `target/` 下的 `.o` 文件。
2. **stdin 语义与冻结计划 L256 冲突**：计划要求"写完一行后立即关闭 bootstrap write side"，但 `_watch_bootstrap_stdin()` 把 EOF 当孤儿信号。实测（`probe_r07_stdin.py`）：stdin 保持打开 → child 2.5 s 后存活 `True`；关闭 stdin → 15 s 内退出 `True`（`exitcode=0`，日志 `Bootstrap stdin reached EOF (parent exited); shutting down LVA Core`）。因此 R07 **长期持有 `ChildStdin`**，这是对计划的刻意偏离。
3. **token 规格与冻结计划 L254 不一致**：计划要求 32-byte 随机 token（`base64url-256-bit`），实现是 `Uuid::new_v4().to_string() + &Uuid::new_v4().to_string()`（`core_supervisor.rs` L48，72 字符）。熵量级相当（2×122 bit 十六进制），但格式与计划不符。
4. **生产代码无 `emit_event` 调用方**：`runtime.py` L128 定义 `emit_event`，全 `src/lva` 无调用方（仅 `tests/invariants/test_invariants.py:105`）。`_broadcast_ipc_event`（`server.py` L78，走 `EventEnvelope`，**有 `sequence`**）挂在 `RuntimeController(event_broadcaster=…)`（L105）；`_broadcast`（L54，`PL.Event` → `kind+ts+flat data`，**无 `sequence`**）挂在 `PL.VoiceCore(on_event=…)`（L114）。→ gap 检测只对 typed envelope 生效，**真机当前可能永不触发**，不得宣称"已实测 gap 恢复"。
5. **`ws.rs` 是手写实现，无 crate 依赖**：离线 registry 内无可用 WS crate，`ring` 因缺 cc 工具链不可用，亦无 `sha1` crate。自实现范围：SHA-1、base64、`accept_for_key`、帧头解析、掩码、`write_frame`、握手解析。已知限制：单帧上限 16 MiB（`MAX_FRAME_BYTES`）、握手上限 16 KiB、仅客户端掩码（服务端帧不解掩码）、无扩展/压缩/子协议协商、无独立 RED 覆盖（只有 9 项自带单测：SHA-1 四向量含 1,000,000 个 'a'、base64 六向量、RFC6455 样例 `s3pPLMBiTxaQ9kYGzzhZRbK+xOo=`、短帧/扩展长度 126/127/掩码/超限/不完整头/掩码往返）。
6. **`reqwest` 已无 Rust 调用方**：`Cargo.toml` 保留 `reqwest = { version = "0.12", features = ["blocking", "json"] }`，但 `src-tauri/src` 全量检索 `reqwest` 为 0 命中。`Cargo.toml`/`Cargo.lock` 的 diff（`+uuid`、`+reqwest`、`+chrono`）**非本轮产生**，本轮零新增依赖。
7. **`modeTransition.js` 的测试情况需修正交接口径**：交接文档称"前端 Vue/Pinia 接线只有结构断言"。实际上 `tests/red_v121/test_mode_transition_recovery.py`（6 项）与 `test_bridge_mock_and_snapshot_version.py`（6 项）都通过 `node --input-type=module` **真实执行** `modeTransition.js`，本轮实测 6 passed / 6 passed；只有 store 自身接线（`runtime.ts` 的 `setMode` 体）是源码断言。仓库内**没有** `*.test.*`/`*.spec.*` 前端测试文件，`package.json` 也没有 test 脚本——Python 侧的这两个文件就是它的测试。
8. **`apps/desktop-ui/dist/` 是陈旧构建**：E 盘 `dist/assets/index-Csvm8PD1.js`（144,927 B，mtime 2026-09-23 12:52:37）早于 `runtime.ts`（mtime 23:39:01）与 `ControlsIsland.vue`（23:32:59）。该产物不含 `setMuted`，而 X 盘按当前源码构建的 `index-DRckcx7K.js` 含 `setMuted`。若部署依赖 E 盘 `dist/`，需要重新构建。
9. **`scripts/verify_release_gates.py` 是 v1.2 判据**：文件内不含 `red_v121` 字样，从不运行 `tests/red_v121`。
10. **`lva ask` 在 fail-closed 后无合法认证通道**：沿用 R05 第 5.2 条，本轮未处理。
11. **探针夹具中仍有 6 处 `"active"`**：`bridge.rs` L690（`typed_event`）、L771 与 L792（`command_result` 断言对）、L788（`commands_are_correlated_by_command_id` 载荷）、L806 与 L823（`answer_snapshot` 及其断言）。这些是 stub 自洽数据，不触生产枚举，测试通过。**只报告不擅自改**，因为改它们会改动测试语义。
12. **三个生成制品未改**（SHA256 与字节）：`schemas/lva-ipc-v1.json` `ec6f3bb46b6a37402ca8e5eccc71dda479b6ba54216c249abac46751cc310c8c`（55,463 B）、`apps/desktop-ui/src/generated/lva-ipc.ts` `c836f691743d3074e49354ede8af3e67f320430bbfaa9a8c312cbd19c6ae5b5d`（16,319 B）、`apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs` `d307e1c519368e19395fa2f4eda972a37ad5b3221764e00f951e321daf012185`（78,138 B）。
13. **`git grep` 在本仓不可靠**：`src/lva/core/runtime.py`、`bridge.rs`、`ws.rs`、`core_supervisor.rs` 等大量文件仍是 `??`（未跟踪），`git grep` 只搜已跟踪内容，会给出假阴性（本轮 `git grep emit_event` 即返回空）。判定"全仓有无某调用方"必须用文件系统检索。
14. **`tests/red_v121` 无 R07 专属 RED**：15 个测试文件里，`test_bridge_mock_and_snapshot_version.py`/`test_red_snapshot.py` 属 R08，`test_red_authority.py` 属 R09/R10。**R07 的证据只能来自探针与真机演示**，这也解释了为什么本片以进程级探针为主要证据。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/` / `scripts/soak_report.json`；未执行任何 git 写操作（无 add/commit/push/reset/checkout/clean）。所有 E 盘写入均经 `apply_patch`。未宣称"全量 lint 通过"——Ruff 仅覆盖 E4/E7/E9 且范围限 `src/lva` + `tests/run_groups.py`。

本轮探针的"正确 token 被接受"是通过 stdin 管道在探针进程内交付 token 完成的，未新增任何 argv/env/file 传递通道。token 未出现在任何报告、日志或命令行中。

### 7.1 本轮我自己犯的 3 处错误（已修，记录在案）

1. **`apply_patch` 上下文行未带前缀导致重复插入**：`core_supervisor.rs` 首个小补丁把 `pub struct CoreInstance` 块重复插入（第 10-16 行残留旧块）；`bridge.rs` 追加测试时把 `obj.insert(...)`/`Ok(id)`/`}` 三行重复追加到 `command_key` 之后（L531-533），编译报 `unexpected closing delimiter`。两处均已逐个精确补丁修好。
2. **变量作用域误用**：`bridge.rs` L354 用 `seq.unwrap_or(0)`，但 `seq` 只在 gap 检测的 `if let` 块内可见 → `E0425`。改为 `sequence.unwrap_or(0)`。
3. **重连测试两次误判**：先是第二条 stub 连接自行关闭导致 `is_connected` 假失败（加诊断 `eprintln!` 定位后删除）；再是 `wait_until(!is_connected)` 因重连太快（<20 ms）产生竞态 → 改为只断言"第二个快照到达 + 第二次连接被接受"，用 `Arc<AtomicBool> release` 让第二条连接保活到测试末尾。

---

## 8. 下一片

R07 的 Rust↔Core bridge 本体已闭环：编译通过、29 项单测（含 1 项 `#[ignore]` 互操作探针）、真实 `/ws` 路由上 10 项验收逐条取证、前端无 endpoint/token 泄漏、`tests/red_v121` 无新增红。

按 R05 第 8 节排期，下一片为 **R08 — 单一 snapshot DTO**（`test_red_snapshot.py` 3 项、`test_bridge_mock_and_snapshot_version.py` 6 项当前**已全绿**，需先确认是否仍有实质缺口）。

进入 R08 前需要裁决的三项（本片遗留）：

1. 5.1 的"丢弃无 `sequence` 事件"是否接受为最终行为；
2. 5.2 的 `runtime_instance_id` 双源不一致是否在 R08 一并修正；
3. R06 报告缺失（5.3）是否需要补写，以及 `scripts/start-all.ps1`（5.4）归属哪一片。

`tests/red_v121` 当前剩余 5 项红，全部在 `test_red_authority.py`：`test_rust_exposes_no_direct_model_lifecycle_commands`、`test_core_actually_wires_a_hub_saga`、`test_legacy_1234_default_is_gone`、`test_no_route_bypasses_the_command_dispatcher`、`test_ask_route_adapts_into_a_command`（属 R09/R10）。

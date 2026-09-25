# R22 执行报告 — 真实 Hub 端到端验证（补写）

- 日期：2026-09-24（工作执行）／2026-09-25（报告补写）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 状态：**工作与证据早已在盘上，本报告为补写**——当轮做完后直接进入审查方给的 bug 清单（R23），未出具独立报告

---

## 0. 背景：为什么这一轮能发生

此前「真实 Hub 端到端」一直被标为不可达。R20/R21 期间我在**只读排查**时发现本机装有 Hub：

- `D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\` **存在**，版本**正是 pinned 的 0.9.8.3**
- 配置 `webPort: 8080`、`httpOnlyPort: 8081`、`listenAddress: 0.0.0.0`、`apiKeyEnabled: true`

**沙箱内无法自行启动它**：`java.net.http.HttpClient` 初始化时要建 loopback self-pipe，被沙箱拒绝——

```text
java.lang.ExceptionInInitializerError
Caused by: java.io.UncheckedIOException: java.io.IOException: Unable to establish loopback connection
  at java.net.http.HttpClientImpl.<init>
  at org.mark.llamacpp.server.mcp.McpClientService.<init>(McpClientService.java:88)
Caused by: java.net.SocketException: Invalid argument: connect
  at java.base/sun.nio.ch.UnixDomainSockets.connect0(Native Method)
```

Hub 在**监听 8080 之前**就死在 `McpClientService` 的静态初始化。附带观察：其配置里 `mcpServer.enabled: false`，但该服务仍被静态初始化并构造 `HttpClient`——这是 Hub 自身的可优化点，**非本项目范围，未改**。

**结论**：由用户启动 Hub，我在沙箱内做客户端侧验证。

---

## 1. 交付物

| 文件 | 说明 |
|---|---|
| `scripts/probe_real_hub.py` | **新增**。客户端侧验证探针：读真实 netstat 表 → 跑 PR-008 分类器 → 探测 4 个 HTTP 面 → 调 Core 的 `probe_handshake()`。API key 从 Hub 配置读取但**不打印** |
| `tests/fixtures/hub/version_0_9_8_3.json` | **改写**为真实信封（含 `data` 层） |
| `tests/fixtures/hub/version_unknown.json` | 同上 |
| `tests/red_v121/test_red_real_hub_shapes.py` | **新增** RED 套件（3 项守卫） |

---

## 2. 发现并修复一个真实 bug：version 信封层级

### 2.1 真实响应

```json
{"success":true,"data":{"createdTime":"2026-09-07T03:55:53Z","tag":"v0.9.8.3","version":"0.9.8.3"}}
```

### 2.2 缺陷

`probe_handshake()` 读**顶层** `info.get("version")` → `None` → **把一个完全健康的 pinned Hub 判成 `DEGRADED`**。后果：真实部署下 Hub 控制会被无理由禁用。

### 2.3 为什么所有 fixture 级测试都没发现

我在 R14 写的 `version_0_9_8_3.json` fixture **用的是错的形状**（顶层 `version`）——**fixture 与代码犯了同一个错误假设，互相印证，测试全绿**。

**这与 R20 的 8089 bug 是同一类失败模式**（自指夹具）。

### 2.4 修复

```python
payload = info.get("data") if isinstance(info.get("data"), dict) else info
reported = payload.get("version") or payload.get("tag")
if isinstance(reported, str) and reported.startswith("v"):
    reported = reported[1:]
```

两个 fixture 也改写为真实信封，使它们**不能再印证错误假设**。

---

## 3. 验证结果（真实 Hub 0.9.8.3 @ 0.0.0.0:8080）

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

### 3.1 关键判定：`control_allowed = False` 是正确的

Hub 监听 `0.0.0.0`，按计划 L579/L1257 **control 应当被拒绝**（`VERIFIED_NON_LOOPBACK`）。

**所以本轮覆盖的是拒绝路径，不是放行路径。** 放行路径需 Hub 改绑 `127.0.0.1`（见 R24 之后的独立验证）。

### 3.2 本轮验证了什么 / 没验证什么

| 已验证 | 未验证 |
|---|---|
| 真实 `/api/sys/version` 信封形状 | Rust 进程真实**发送** attestation（R16 遗留，需 GUI） |
| 真实 listener 表的分类结果 | 放行路径（需 Hub 改绑 loopback） |
| Core `probe_handshake()` 对真实 Hub 返回 `READY` | 真实 model load/stop（需真实模型加载） |
| 真实 `/v1/models`、`/api/models/{list,loaded}` 形状 | — |

---

## 4. 实测

| 项 | 结果 |
|---|---|
| 新 RED 套件 | 改前 **2 failed / 1 passed** → 改后 **3 passed** |
| `tests/red_v121` 全量 | **238P → 241P / 0F** |
| v12 层 7 组 | all groups passed |
| ruff | All checks passed |
| **真实 Hub** | `probe_handshake() = READY` |

---

## 5. 差异报告

1. **本报告是补写的**：R22 的工作在 2026-09-24 完成并验证，报告在 2026-09-25 补出。中间插入了 R23（审查方 bug 清单修复）与 R24（B5 可见化）。**编号顺序与时间顺序不完全一致**。
2. **探针自身也曾复述同一错误假设**：`probe_real_hub.py` 初版自己读顶层 `version`，因此在 Core 已修好之后**仍打印 `reported version = None -> DEGRADED`**。已在 R23 修正。**这是我在写探针时重犯了同一个 bug**——说明该错误假设的传染性。
3. **Hub 的 `apiKey` 曾出现在我的只读输出中**：那是用户本机 Hub 的本地 key，非 LVA 密钥，且在其自己的配置文件里。**未写入任何仓库文件或提交**。
4. **未改动用户的 Hub 配置**（`application.json` mtime 保持 `2026-09-19 12:00:39`）。

---

## 6. 硬约束遵守

未弱化/跳过/xfail 任何断言；未手改三个生成制品；未使用 F2/F3/Astra；未改写冻结计划与历史报告；**未执行 git 写操作**；未改动用户的 Hub 配置。**零契约改动、零新增依赖。**

## 7. 后续

| 项 | 状态 |
|---|---|
| 放行路径验证 | 本轮之后授权并执行（见 R25） |
| Rust 进程真实发送 attestation | 仍待 GUI 环境 |
| 真实 model load/stop | 需真实模型加载 |


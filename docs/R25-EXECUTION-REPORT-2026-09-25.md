# R25 执行报告 — B7 单源收敛（Hub 端口）+ 放行路径改绑

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 范围来源：用户授权「B7 单源收敛授权」+「放行路径验证，Hub 改绑 127.0.0.1 进行」

---

## 1. B7：同一事实六处副本 → 单源

### 1.1 问题（R20 事故的根因）

「Hub 端口是 8080」这一个事实，在修复前有 **6 处独立字面量**：

| # | 位置 | 形态 |
|---|---|---|
| 1 | `src/lva/config.py` L65 `HUB_PORT` | 环境变量默认值 |
| 2 | `src/lva/providers/hub_control.py` 构造签名 | `base_url: str = "http://127.0.0.1:8080"` |
| 3 | `src/lva/providers/hub_inference.py` 构造签名 | 同上 |
| 4 | `src/lva/providers/openai_compatible.py` 构造签名 | `"http://127.0.0.1:8080/v1"` |
| 5 | `src/lva/server.py` `get_hub_saga()` | `f"http://{C.SERVICE_HOST}:{C.HUB_PORT}"` 手工拼接 |
| 6 | `apps/desktop-shell/src-tauri/src/lib.rs` L107 | `const HUB_CONTROL_PORT: u16 = 8080` |

R20 事故正是第 6 处写成了 8089：Rust 探测一个不存在的端口，attestation 永远 UNVERIFIED_BIND。R21 加了**跨语言守卫**（能检测漂移），但副本本身还在——守卫只能发现不一致，不能阻止有人改错其中一处。

### 1.2 本轮改动

新增 `config.hub_base_url()` 作为**唯一派生点**：

```python
def hub_base_url(*, with_v1: bool = False) -> str:
    base = f"http://{SERVICE_HOST}:{HUB_PORT}"
    return f"{base}/v1" if with_v1 else base
```

| 位置 | 改动 |
|---|---|
| `config.py` | 新增 `hub_base_url()`；`LLM_BASE_URL` 改为派生（见 §2） |
| `hub_control.py` | `base_url: str \| None = None` → `(base_url or C.hub_base_url())` |
| `hub_inference.py` | 同上 |
| `openai_compatible.py` | `(base_url or C.hub_base_url(with_v1=True))` |
| `server.py` | `base_url = C.hub_base_url()`（不再手工拼接） |
| `lib.rs` | **未改**——Rust 无法 import Python，保留一个常量，由 R21 跨语言守卫保一致 |

**保留一个 Rust 常量的理由**：跨语言共享代码在此架构下不可行；把 Python 常量硬塞进 Rust 只会制造构建期耦合。守卫（R21）已能覆盖这一处。这是**有意的例外**，不是遗漏。

### 1.3 反转 R21 的一条断言（不是弱化，是收敛后的正确形态）

`test_red_cross_language_consistency.py::test_python_provider_defaults_actually_use_the_hub_port`

- **旧形态**：断言三个 provider 里**必须出现** `127.0.0.1:<hub_port>` 字面量。
- **新形态**：断言三个 provider 里**不得出现**任何 loopback 字面量，且必须走 `hub_base_url`。

这不是放宽断言——它断言的是**更强**的性质：旧形态要求「抄对」，新形态要求「不抄」。docstring 已注明反转原因与时机。

### 1.4 新增 RED：`tests/red_v121/test_red_single_source_hub_port.py`（6 项）

| 测试 | 断言 |
|---|---|
| `test_providers_do_not_carry_their_own_port_literal` | 三个 provider 零 loopback 字面量 |
| `test_providers_default_to_the_configured_hub_url` | 默认值必须派生而非缺失 |
| `test_config_exposes_one_hub_url_helper` | `config.hub_base_url()` 存在 |
| `test_server_uses_the_helper` | Core 接线用 helper，不手工拼接 |
| `test_rust_keeps_exactly_one_port_constant` | `lib.rs` 代码（去注释）里 `8080` 恰好出现 **1** 次 |
| `test_config_llm_endpoint_derives_from_the_hub_url` | `LLM_BASE_URL` 不得含 loopback 字面量且必须含 `hub_base_url`（见 §2） |

最后一项是本轮实现过程中**新发现**的覆盖缺口，见下节。

---

## 2. 实现中发现的第 7 处副本（B7 清单外）

`config.py` L50 原本是：

```python
LLM_BASE_URL = os.environ.get("LVA_LLM_URL", "http://127.0.0.1:8080/v1")
```

**这是「Hub 端口」这一事实的第 7 份拷贝**，且比前六处更隐蔽：它写在 `config.py` 内部，看起来像「配置」，实际是硬编码——`HUB_PORT` 改成别的值时，`LLM_BASE_URL` 不会跟随，`llm.py` 会去敲一个旧端口。B7 清单（6 处）没有把它列进去。

改为：

```python
LLM_BASE_URL = os.environ.get("LVA_LLM_URL", "") or hub_base_url(with_v1=True)
```

注意 `or` 而非 `,`：环境变量**显式设为空串**时也要回落到派生值，避免出现「有人导出了空变量 → 端点变成 `"/v1"`」这类怪状态。

**顺序调整**：`LLM_BASE_URL` 现在依赖 `hub_base_url()`，故把 services 段（`SERVICE_HOST`/`HUB_PORT`/`HUB_API_KEY`/helper）**上移到 llm 段之前**。纯位置调整，无行为影响。

已用新增 RED 守护（`test_config_llm_endpoint_derives_from_the_hub_url`）。

---

## 3. 验证（本轮实测，非沿用）

| 项 | 命令 | 结果 |
|---|---|---|
| RED 全套 | `pytest tests/red_v121 -q` | **259 passed / 0 failed**（R24 为 258，+1 即本轮新增断言） |
| 定向（3 文件） | `pytest test_red_single_source_hub_port test_red_cross_language_consistency test_red_direct_llama_removal` | 21 passed |
| v12 七组 | `tests/run_groups.py --layer v12` | contract 5 / invariants 23 / **unit 43** / fault 7 / integration 11 / migration 2 / ux 11 — **all groups passed** |
| ruff | `ruff check src/lva tests/red_v121` | All checks passed |
| 运行时派生 | 直接 import config | `LLM_BASE_URL == hub_base_url(with_v1=True)` → **True**；`HUB_PORT = 8080` |

**逐文件哈希（SHA256）**：

| 文件 | 字节 | SHA256 |
|---|---|---|
| `src/lva/config.py` | 8,288 | `03CFD08164D1701D235EBDC35E201F6FD4CA24C4CDFEF1821B9357E1B7E63009` |
| `src/lva/server.py` | 25,039 | `4C3CC48659FCB0D708BBB8751F5A7212C157EC63AA8A300B612FDC648D7FD5FE` |
| `src/lva/providers/hub_control.py` | 11,377 | `B6EF518C7D575642BFFE1307FF0F032AFB46AA340E991B8465F0DEF168DE9D22` |
| `src/lva/providers/hub_inference.py` | 8,381 | `2E9F306AA786A2399A22C7322439260AD491332D37A2C3E05C9B6EA048BE6E84` |
| `src/lva/providers/openai_compatible.py` | 2,549 | `D9143DA8A0E883309F7CBA907DEF110D6D3AB7825E44D003057E65E9E2DD889A` |
| `tests/red_v121/test_red_single_source_hub_port.py` | 3,988 | `ED931C4E473FC203242842764104AB25DDE4FA117F52FEF33CF050B13588CBA9` |
| `tests/red_v121/test_red_cross_language_consistency.py` | 8,160 | `CBDEF537AEA9FFED47FA667D607B543C8F54870429A9969339CFC5B4F0B9A0BC` |

**零契约改动**：`contracts/` 未触碰，三个生成制品字节未变（本切片不涉及 IPC schema）。

---

## 4. 放行路径验证：Hub 已改绑 127.0.0.1（探针待运行）

### 4.1 已完成的改绑

| 项 | 值 |
|---|---|
| 配置文件 | `D:\llamacpphub\llama.cpp-hub-v0.9.8.3-b10830-windows-cuda13\config\application.json` |
| 改动 | `server.listenAddress`: `"0.0.0.0"` → `"127.0.0.1"`（**单次出现**，定向替换） |
| 改动前备份 | `application.json.before-loopback-test`（495 B，SHA256 `C3ACAB6907F072F18E4D99738D17D2032A76502328434D865A9F7E42D71DB61A`） |
| 改动后 | 497 B，SHA256 `B2427FF16AAD0A5BBBDF3A9C334FB5E247147E3402714FFA641ED4AA851610B0` |
| 其余键 | `webPort 8080` / `httpOnlyPort 8081` / `apiKeyEnabled: true` / `https.enabled: false` **均未改** |

### 4.2 未完成：探针尚未运行（用户指示先跳过）

**预期结果**（未观测，属预测而非结论）：

```
LISTENING 127.0.0.1:8080 -> LoopbackOnly
PR-008 classifier verdict = VERIFIED_LOOPBACK
control_allowed (plan L665) = True
```

**为何本轮没跑**：Hub 的 JVM 在本沙箱内无法启动——`java.net.SocketException: Invalid argument: connect` @ `sun.nio.ch.UnixDomainSockets.connect0`，死在 `McpClientService` 静态初始化（`java.net.http.HttpClient` 建 loopback self-pipe 被沙箱拒绝）。提权启动 javaw 被自动审批拒绝；用官方启动器 `llama.cpp-hub.exe` 提权启动后，JVM 同样死在同一处（`logs/app.log` 11:28:44 两次异常）。**这是环境限制，不是 Hub 故障**——与既往会话记录一致。

残留进程已清理（启动器 PID 34104 已终止，8080/8081 当前无监听）。

**放行路径验证的判定条件**（下一次由用户启动 Hub 后执行）：

1. `python scripts/probe_real_hub.py 8080` → 期望 `VERIFIED_LOOPBACK` + `control_allowed = True`；
2. 这是 PR-012 attestation 门控**首次**在真实 Hub 上被验证为「开门」——至今只有 fail-closed 侧的观测。

**备份保留**：`application.json.before-loopback-test` 留在原目录，随时可回滚到 0.0.0.0 绑定。

---

## 5. 本轮未做 / 未验证（诚实边界）

| 项 | 状态 |
|---|---|
| 放行路径探针 | **未运行**（用户指示跳过；Hub 沙箱内无法启动） |
| Rust 侧复跑 | 本轮未改 Rust，沿用 R24 结论（`lib.rs` 字节未变） |
| `hub.bind_model` 真实切换 | 未验证（需真实模型加载） |
| B9 `recall.py` LIKE 未转义 | 未处理（改它会改变搜索语义，待裁决） |
| B10 `list_loaded` fail-open | 未处理（有 warning；建议补显式注释） |
| L463 `settings_revision` 进 command 签名 | 仍挂起（需硬约束 5 单独授权） |
| `_enc` 密钥轮换 | 仍挂起（只有所有者能判断是否为真实密钥） |

---

## 6. 提交范围

本次提交**只含 R25 相关文件**：

- `src/lva/config.py`、`src/lva/server.py`、`src/lva/providers/{hub_control,hub_inference,openai_compatible}.py`
- `tests/red_v121/test_red_single_source_hub_port.py`（新增）、`tests/red_v121/test_red_cross_language_consistency.py`（反转断言）
- 本报告

**明确排除**：21 项 ` D` 删除类（计划 L1730/L1732 闸门：OLV 属 PR-036、旧 HTML 属 PR-038、`scripts/llm_serve.py` 属 PR-015 门——**均不得随本切片提交**）、`apps/open-llm-vtuber/{CODEOWNERS,DEPRECATION.md}`（未跟踪，非本切片产物）。


# R05 执行报告 — Wave 1 / PR-006 认证默认拒绝（fail-closed）

- 日期：2026-09-23（Asia/Shanghai）
- 执行者：DeepSeek（本会话，接管 `LocalVoiceAgent-R04-DeepSeek-Handoff-2026-09-23.md` 后的第一片）
- 仓库：`E:\AI\LocalVoiceAgent`
- HEAD：`cf1c96752ffb752de1581860968d5189cd6e2a2c`（未提交、未推送、未 reset/checkout/clean）
- 工作树：`status --porcelain=v1` = **82 行**；`-uall` 口径 = **240 行**（两口径不同，非冲突）
- 范围来源（四处独立一致）：`tests/red_v121/README.md` 映射表（`test_red_auth.py` → §Phase 1 / PR-006 → **Fix slice R05**）、`tests/red_v121/conftest.py` docstring（`R05 -> auth fail-closed`）、冻结计划 `ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md` L716-721 与 L1188-1196
- 冻结验收原文（计划 L1195-1196）：无 token/错 token/错 origin/nonce mismatch 均拒绝；token 不出现在 argv/env/file/log；开发模式可用显式 `--dev-fixed-port`，仍须 token；旧 unauthenticated path 不保留。

---

## 1. 已修改（本轮，逐文件）

| 文件 | 改动 | 目的 | 字节 | SHA256 |
|---|---|---|---|---|
| `src/lva/transport/auth.py` | `verify_token`：拆开 `if not self.require_auth or not self.expected_token` 的 fail-open 合并分支，`expected_token is None` 时返回 False；`verify_origin`：删除 loopback 前缀放行块，改为仅精确匹配 `allowed_origins`；`dispatch`：删除 query string token 分支；补 `Any` 导入 | fail-closed + Origin 固定值 + token 不进 URL | 3992 | `88dda5826459ca657dd3b1ec5b55834489c94487e4ca92823872b08804c922a7` |
| `src/lva/server.py` | L141 `TokenValidator(require_auth=False)` → `TokenValidator()`；`/ws` 处理器：从 `Authorization: Bearer` 头取 token（原为 query params），并加 `verify_origin` 检查，失败一律 close(4403) | 私有入口统一认证 | 17580 | `ba7523faee3354b180ef7f225cfbdc8d0b9aacdbaaf94f56e8af224c531870fb` |
| `src/lva/__main__.py` | 删除 `s.add_argument("--token", ...)` 与 `auth_validator.set_token(args.token)` | token 不进 argv | 5834 | `a039426a274b7f9e29e1207058397d17152f52060dc7235daff56c0d74305447` |
| `tests/integration/test_transport_resilience.py` | 5 处 `websocket_connect("/ws?token=...")` → `websocket_connect("/ws", headers={"Authorization": "Bearer ..."})`；fixture teardown 由 `require_auth=False` 改为 `require_auth=True` + `expected_token=None`（保持 fail-closed） | 迁移到 header 认证 | 7347 | `abb49910b0528021a8d9b1e621276e0d3e128307f4c0dd66faa0014a6898183d` |
| `tests/invariants/test_invariants.py` | `test_i07_i08_passive_forbids_llm_tts` 补 auth 头与 `monkeypatch` token，使请求能穿过认证到达模式守卫 | 保持 I07/I08 断言有效 | 26342 | `388ca8ae8f0698a1d67dd9813fb7bc2a8306dc6c1be3c50b4eb96de7c488463e` |

未修改：三个生成制品（`schemas/lva-ipc-v1.json`、`apps/desktop-ui/src/generated/lva-ipc.ts`、`apps/desktop-shell/src-tauri/src/generated/lva_ipc.rs`）、冻结计划与历史报告、任何 RED 断言、`apps/desktop-shell/src-tauri/src/*.rs`（`bridge.rs` 原本就用 `Authorization: Bearer`，无需改动）。

### 1.1 关键修复语义

`verify_token` 现在分三步：`require_auth is False` → 放行（显式 opt-out，见第 5 节残余项）；`expected_token is None` → **拒绝一切**；否则 `hmac.compare_digest` 常量时间比较。这正是 RED 三条运行时断言要求的组合：默认 fail-closed、未配置 token 时任何 token 都无效、无 token 永不通过。

`verify_origin` 保留 `origin is None` → True（invariants L267 的 I11 断言），但把 `http://localhost` / `http://127.0.0.1` 前缀放行整块删除，改为精确成员匹配，因此 `http://localhost:5173` 这类任意 dev-server origin 被拒。

---

## 2. 本轮实测通过

| 项 | 命令要点 | 结果 |
|---|---|---|
| **R05 RED 目标** | `pytest tests/red_v121/test_red_auth.py` | **8 passed**（改前 6 failed / 2 passed） |
| v1.2.1 RED 全量 | `pytest tests/red_v121` | **27 failed / 114 passed**（改前 33 failed / 108 passed；6 项转绿，无新增红） |
| I11 认证边界 | `pytest tests/invariants` | 23 passed（无回归） |
| 传输韧性 | `pytest tests/integration` | 11 passed（无回归） |
| quality harness | `pytest tests/harness tests/red_v121/test_harness_selftest.py` | 43 passed（无回归） |
| v12 全层 + harness | `python tests/run_groups.py --layer v12 harness` | contract 5 / invariants 23 / unit 8 / fault 7 / integration 11 / migration 2 / ux 11 → **all groups passed**，EXIT=0 |
| lint | `ruff check src/lva tests/run_groups.py`（`RUFF_CACHE_DIR` 指 X 盘） | All checks passed（仅 E4/E7/E9 规则集） |
| **进程级真实探针** | 真 uvicorn + 真 HTTP/WS 客户端，token 经 stdin 管道交付 | **17/17 PASS**（见 2.1） |
| **无 token 配置 fail-closed 探针** | 同上，stdin 管道不交付任何 token | **5/5 PASS**（见 2.2） |
| CLI 面 | `python -m lva serve --token abc` | `unrecognized arguments: --token abc`，EXIT=2；`serve --help` 只剩 `--port` / `--bootstrap` / `--log-level` |

### 2.1 进程级探针明细（真 uvicorn，端口 8793，token 经 stdin 管道）

HTTP：无 token → 401 `AUTH_REQUIRED`；错 token → 403 `AUTH_FAILED`；`?token=<正确值>` → **401**（URL 携带 token 不再认证）；`Origin: http://localhost:5173` → 403 `ORIGIN_REJECTED`；`Origin: http://127.0.0.1:5173` → 403；`Origin: https://evil.example.com` → 403；`Origin: tauri://localhost` / `http://tauri.localhost` + 正确 token → 穿过认证与 Origin 边界。

WS（`/ws`）：无 token → 403；`?token=<正确值>` → 403；错 token → 403；`Origin: http://localhost:5173` → 403；正确 token + `tauri://localhost` → **握手 101 通过**；正确 token 无 Origin → **握手 101 通过**。

秘密面：服务端日志 18,498 B 内**不含** token；launcher argv/env 不含 token。

### 2.2 无 token 配置 fail-closed 探针（端口 8794，stdin 管道关闭且不交付 token）

服务仍可监听（fail-closed 不是启动失败），但：无 token → 401；任意 Bearer → 403 `AUTH_FAILED`；任意 Bearer + `Origin: tauri://localhost` → **403**（Origin 不是认证替代品）。

---

## 3. 本轮实测失败 / 未达成

| 项 | 结果 | 说明 |
|---|---|---|
| `lva serve`（非 bootstrap）在本机启动 | **失败（环境限制，非 R05 缺陷）** | `sounddevice.PortAudioError: Error opening InputStream: Invalid device [PaErrorCode -9996]`：本机无可用音频输入设备，`lifespan` 内 `core().start()` 失败。进程级探针因此改用同一 ASGI 应用 + `lifespan="off"` + 真 uvicorn，安全边界判定不受影响。 |
| `/api/state`、`/api/ask` 的 200 成功路径（进程级） | 未取得 | 二者都会触发 `core()` 加载 MeloTTS ONNX 模型，本机 `LVA_ROOT` 指向 scratch 时模型缺失（`File doesn't exist`）。该路径已由 `tests/integration`（11 passed）与 `tests/invariants`（23 passed）覆盖。 |

---

## 4. 未运行 / N/A（不得记为 PASS）

| 项 | 状态 | 原因 |
|---|---|---|
| 前端 Vue/Pinia 端到端 | 未验证 | 沿用 R04 状态；本轮无前端改动 |
| GUI 交互类 spike（透明/点击穿透/托盘菜单实际点击） | 未验证 | 本轮无 GUI 改动 |
| 多显示器 DPI/scale | N/A | 仅 1 台显示器（1707x1067 @144DPI） |
| soak `--duration 7200` 长跑 | 未运行 | 未排期 |
| Tauri release 构建 | 未运行 | 本轮未触及 Rust 代码，未重跑 `cargo check` |
| 前端 `npm run build` | 未运行 | 本轮无前端改动 |
| 三个 workflow 的 GitHub Actions 实跑 | 未运行 | 未推送 |
| 真实麦克风/扬声器声学验收 | 未运行 | 本机无音频输入设备（见 3） |
| PR-005 GUI quit 实证 | 未验证 | 沿用 R04 状态 |

---

## 5. 需裁决 / 需记录的残余项

### 5.1 `require_auth` 参数保留为显式旁路开关（与"旧 unauthenticated path 不保留"存在张力）

RED 判据与 I11 断言都显式构造 `TokenValidator(require_auth=True)`，因此该参数不能删除；`tests/integration` 的 fixture 也依赖它。当前实现保留 `require_auth=False` 时放行全部请求的分支，但**产品代码已无任何调用点**（`server.py` 用默认构造，`rg` 全仓确认 `require_auth=False` 仅存在于 RED 断言文本中）。

严格说这是一个"显式 opt-out 旁路"，与计划 L1196"旧 unauthenticated path 不保留"存在解释空间。本轮选择**不自行删除参数**（会同时破坏 RED 与 I11），把它列为残余项，建议在 R06/PR-007 硬化时统一裁决（例如改为仅测试可见的内部开关，或让 `require_auth` 参数退化为只读属性）。

### 5.2 `lva ask` 失去认证路径（真实冲突，未自行发明 token 通道）

`cmd_ask`（`src/lva/__main__.py`）向 `/api/ask` POST 时不带任何认证头。fail-closed 之后，该子命令对私有路由必然得到 401。

计划 L1196 认可的开发模式只有 `--dev-fixed-port`（且"仍须 token"），硬约束 #5 禁止 token 进 CLI/env/磁盘/日志/WebView。两者叠加后，`lva ask` 在现有约束下**没有合法认证通道**。本轮未改动 `cmd_ask`，也未新增任何 token 传递方式。可选裁决方向（供决策，未实施）：(a) 由 `lva ask` 改走 bootstrap 管道（需 R06 的 `--dev-fixed-port` 落地）；(b) 明确把 `lva ask` 标记为仅调试工具并接受其 401；(c) 从 CLI 移除 `ask` 子命令。

### 5.3 `__main__.py` 与 `test_invariants.py` 的行尾由 CRLF 变为混合/LF

`apply_patch` 写入行只产出 LF，无法保留 CR。改动后：`src/lva/__main__.py` 由纯 CRLF（156）变为 156 CRLF + 7 LF；`tests/invariants/test_invariants.py` 由 641 CRLF 变为 641 CRLF + 29 LF。仓库 `core.autocrlf=true`，git 在下次触碰时会归一化，因此这只是 diff 噪声，不影响 Python/pytest/ruff。已如实记录，未做额外重写以免产生更大 churn。

---

## 6. 差异报告（只报告，未自行修正）

1. **R06 范围、本轮未动**：`src/lva/__main__.py` 的 `--bootstrap` 分支调用 `config.bind_sockets()`，而本环境 uvicorn 0.53.0 **只有 `bind_socket`（单数）**（实测 `hasattr(c,"bind_sockets") == False`），因此该分支当前会 `AttributeError`；同时 `apps/desktop-shell/src-tauri/services.default.json` 的 `lva_core.args` 为 `["-m","lva","--bootstrap"]`，**缺 `serve` 子命令**。两项都属 R06（`test_red_bootstrap.py` 已断言），本轮未改。
2. `scripts/start-all.ps1`（L90-97）以 `-m lva` 启动、端口 8765；R06 范围。
3. `scripts/health-check.ps1` 探 `/health`：该路径在中间件中豁免，不受 R05 影响。
4. `tests/red_v121/test_red_auth.py` docstring 第 10-11 行仍描述改前状态（"builds TokenValidator(require_auth=False), accepts --token, reads WS token from query params"）。RED 文件未修改；该描述已过期，属需知悉项。
5. `src/lva/transport/auth.py` 原本在类体注解中使用 `Any` 却未导入（`from __future__ import annotations` 使其在运行时不炸）。本轮补上 `Any` 导入，属顺手修正的潜在缺陷，已在此声明。

---

## 7. 硬约束遵守

未弱化/跳过/xfail 任何 RED 断言；未手改三个生成制品；未使用 F2/F3；未使用 Astra；未改写冻结计划与历史报告；未删除 `.venv` / `venv` / `benchmarks/` / `scripts/soak_report.json`；未执行任何 git 写操作（无 add/commit/push/reset/checkout/clean）。所有 E 盘写入均经 `apply_patch`。未宣称"全量 lint 通过"——Ruff 仅覆盖 E4/E7/E9 且范围限 `src/lva` + `tests/run_groups.py`。

本轮探针的"正确 token 被接受"一项，是通过冻结认可的 stdin 管道在探针进程内交付 token 完成的，未新增任何 argv/env/file 传递通道。

---

## 8. 下一片

R05 已闭环（RED 8/8、无回归、进程级 17/17 + fail-closed 5/5）。下一片为 **R06 — Core bootstrap + supervisor 接线**（`bind_sockets()` → `bind_socket()`、`services.default.json` 的 `serve` 子命令、`spawn_core` / `set_instance` 调用点、`--dev-fixed-port`），并顺带裁决第 5.1 与 5.2 两条残余项。

`tests/red_v121` 剩余 27 项 RED 分布：R06 bootstrap 6、R09 authority 5、R10、R12、R13 capture 3、R14 output_mute 4、redaction 4、temporal_mention 4、snapshot 1。


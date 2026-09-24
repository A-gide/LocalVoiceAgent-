# 正式 G1 裁决 — Secure IPC/Supervisor（v1.2.1）

- 日期：2026-09-24（Asia/Shanghai）
- 判据来源：冻结计划 `ARCHITECTURE-PLAN-2026-09-v1.2.1-FROZEN.md` **L1680**
- 判据原文：`| G1 Secure IPC/Supervisor | PR-003..008 | I04/I11/I16/I20 绿；token 不泄露；Core restart 可恢复 |`
- 仓库：E:\AI\LocalVoiceAgent；HEAD `292b23c`（已 push）

---

## 裁决表

| # | G1 判据 | 结果 | 证据 |
|---|---|---|---|
| 1 | **PR-003 完成**（runtime configuration boundary） | **PASS** | `get_app_dir()` 第 4 优先级为 `%LOCALAPPDATA%`；`migrate_legacy_runtime_config()`（copy + `*.json.migrated-backup` + 从不删用户文件 + 脱敏报告）；三个运行时文件**已移出索引且仍在磁盘**；`.gitignore` L67-69 经 `check-ignore` 命中 |
| 2 | **PR-004 完成**（secret storage and public DTO） | **PASS（方案 a）** | `PublicAppSettings` 无密钥字段（只有 `*_configured`）+ 新增 `settings_revision`；`set_secret`/`clear_secret` 分离；DPAPI 在盘上生效（`save_to_disk` 写 `*_enc`）；`check_revision()` 陈旧返回 `STALE_REVISION`；单测 `public_dto_has_no_secret_or_ciphertext_field` 序列化后断言无 `_enc`/裸 `api_key`。**L463 的 command 层参数挂起**（需硬约束 5 单独授权），按双方裁决属方案 a 的合规路径 |
| 3 | **PR-005 完成**（spawned-only supervisor） | **PASS** | `supervisor.rs` ownership 前置检查（`stop_spawned` 不误杀 Adopted/External）；`process_manager.rs` 哨兵用真实 `ping.exe`；Rust 单测 55 passed 含 5 项 supervisor + 5 项 process_manager |
| 4 | **PR-006 完成**（secure bootstrap and auth） | **PASS** | `bootstrap.py` 单源 `runtime_instance_id`（R08 修 B18）；`auth.py` fail-closed（未配 token 一律拒）；`/ws` 从 `Authorization: Bearer` 取 token + Origin 检查 + `close(4403)`；`__main__.py` 无 `--token`（token 不进 argv） |
| 5 | **PR-007 完成**（Rust CoreSupervisor and bridge） | **PASS** | `core_supervisor.rs`（token/nonce、pipe child、READY 校验、长期持有 stdin）；`bridge.rs` 唯一 authenticated WS + command correlation + gap/instance 检测 + 有界退避重连；`ws.rs` 手写 RFC 6455 |
| 6 | **PR-008 完成**（service identity and readiness） | **PASS** | `network_attestation.rs`（10 项单测：四类 listener 分类、fail-closed）；`service_registry.rs` 扩为真实实现（`Readiness`/`CrashReason`/`instance_token`/`can_stop()`）；`get_service_identity_status` 已注册进 `generate_handler!` |
| 7 | **I04 绿**（Adopted/External/Unknown 永不 auto-kill） | **PASS** | `test_i04_adopted_external_unknown_never_auto_killed` **单独运行 PASSED**；Rust 侧 `supervisor.rs` ownership 前置检查 + `pid_is_alive` 真实进程断言 |
| 8 | **I11 绿**（未认证/错误协议客户端被拒绝） | **PASS** | `test_i11_auth_boundary` **单独运行 PASSED**；R05 的进程级探针 17/17（无 token 401、错 token 403、`?token=` 401、Origin 拒绝、WS 四种拒绝路径 403） |
| 9 | **I16 绿**（LVA 不杀 Hub-owned child） | **PASS** | `test_i16_lva_never_kills_hub_owned_child` **单独运行 PASSED**；`process_manager.rs` 单测 `assert!(status.llama_server.pid.is_none(), "Hub PID must never be guessed")` + `ownership == Some(Adopted)` |
| 10 | **I20 绿**（WebView/diagnostics 无 secret/token/raw endpoint） | **PASS** | `test_i20_public_settings_no_secrets` **单独运行 PASSED**；`apps/desktop-ui/src` 全量正则扫描 `Bearer …`/`sk-…` **零命中**；R07 的构建产物 + 源码 endpoint/token 双查 NONE |
| 11 | **token 不泄露** | **PASS** | token 只经 bootstrap stdin 管道交付；`__main__.py` 无 `--token`；R05 探针实测服务端日志 18,498 B 不含 token、launcher argv/env 不含 token；WebView 侧正则零命中 |
| 12 | **Core restart 可恢复** | **PASS** | `test_i19_restart_always_standby`（新实例回 STANDBY、`resume_mode is None`）；`test_websocket_reconnect_and_session_continuity`；`bridge.rs::a_dropped_connection_is_re_established`；R07 互操作探针实测「换端口+token+instance 后同一 bridge 采用新 Core 并重新发布快照」，且 `runtime_instance_id` 与旧值不同（L270 的轮换要求） |

## 结论

**G1 PASS**（12/12 判据满足）。

---

## 判定边界（避免误读）

1. **PR-004 以方案 a 通过**：`settings_revision` 在 Rust `SettingsManager` 内可读、可比、可 bump，陈旧写入返回 `STALE_REVISION`。计划 L463 要求的「command 层接收 expected revision」**未实现**，因它需要改 schema + 重跑 codegen（硬约束 5），**由双方裁决挂起且不阻塞 G1**。
2. **两条判据的证据含真实进程/真实 WS，但不是 GUI 端到端**：「Core restart 可恢复」由 R07 的真实 uvicorn + 真实 `/ws` 互操作探针支撑（只 stub `VoiceCore`）；**未**驱动真实 `lva-pet.exe` 进程。
3. **本轮实测**：`I04/I11/I16/I20` 四项**单独运行各 PASSED**（`4 passed, 19 deselected`）；`tests/invariants + tests/integration + tests/fault` 合并 **41 passed**；`tests/red_v121` **228 passed / 0 failed**；Rust **55 passed / 0 failed / 1 ignored**；v12 层 7 组 `all groups passed`。
4. **旧 `verify_release_gates.py` 未参与本裁决**——它是 v1.2 判据、从不运行 `tests/red_v121`。

---

## 与 G0 的关系

| Gate | 判据 | 状态 |
|---|---|---|
| G0 Contract/Build | PR-001/002/022 + S-UI-01 report | **PASS**（2026-09-23 裁决） |
| **G1 Secure IPC/Supervisor** | **PR-003..008；I04/I11/I16/I20 绿；token 不泄露；Core restart 可恢复** | **PASS（本裁决）** |
| G2 Single Core | PR-009..011/033；I01–I03/I05/I07/I08/I13/I22 绿 | 未评估 |
| G3–G8 | 见计划 L1682-1687 | 未评估 |

**G1 通过不等于项目完成。** G2 起仍远，且以下运行时欠账未闭合（见 §「开放项」）。

---

## 开放项（不阻塞 G1，但需排期）

| 项 | 性质 |
|---|---|
| **真实 Hub 端到端**（attestation 送达、Hub 消失/迟到 WS、Hub 存活、真实 switch） | PR-012/013/014/015 四片的运行时验收**全部**只有静态或 fixture 证据。**审查方已告警：欠账正在复利累积，PR-035 全量闸会一次性爆雷** |
| Rust 进程真实发送 attestation | R16 遗留，需 GUI 环境 |
| L463 全合规（`settings_revision` 进 command 签名） | 需硬约束 5 单独授权 |
| `_enc` 密钥轮换 | `settings.json` 的 3 个 DPAPI 密文曾入 `cf1c967` 历史；是否轮换取决于对应的是真实密钥还是测试值，**只有所有者能判断** |
| PR-016..019 的验收映射 | 实现已在，缺逐条映射（与 G1 同属验收欠账） |


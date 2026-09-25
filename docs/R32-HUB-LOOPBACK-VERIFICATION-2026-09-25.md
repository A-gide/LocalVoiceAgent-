# R32 执行报告 — 放行路径首次真实验证（PR-012 attestation 开门侧）

- 日期：2026-09-25（Asia/Shanghai）
- 执行者：DeepSeek
- 仓库：E:\AI\LocalVoiceAgent
- 触发：用户启动 Hub（`llama.cpp-hub` 0.9.8.3，PID 30452）
- 相关条文：§5.8 / L579 / L665（control 门）、L1213（PR-008 attestation）、L1256（G 消费 B 的 attestation）

---

## 1. 这是项目首个「开门」观测

自 R08 引入 attestation 面以来，**全部证据都是 fail-closed 侧**：无 attestation → `control_allowed = False`。`VERIFIED_LOOPBACK` 允许控制这条路径**从未被真实观测**（R16 末、R18、R30 均记为开放项）。

本轮由用户在沙箱外启动 Hub 后，该路径首次被实测：

```
listener rows for port 8080: 1
  LISTENING 127.0.0.1:8080 -> LoopbackOnly
PR-008 classifier verdict = VERIFIED_LOOPBACK
control_allowed (plan L665) = True
```

**判定**：attestation 门控在真实 Hub 上双向可用——既能拒绝（fail-closed），也能在证明为回环后放行（L665 的「只有第一种允许 load/stop/switch control」）。

---

## 2. 同时被真实形状证实的四件事

| 项 | 此前证据等级 | 本轮真实观测 |
|---|---|---|
| `/api/sys/version` 形状 | R22 修正了 fixture 的错误假设，但仍是 fixture | `{"success":true,"data":{"createdTime":"2026-09-07T03:55:53Z","tag":"v0.9.8.3","version":"0.9.8.3"}}` |
| `classify_version` 结果 | 仅 fixture | 真实响应 → **READY**（非 DEGRADED） |
| `probe_handshake()` | 仅单测 | **READY** |
| `supports(models.load)` | 仅单测 | **True** |

**版本确认为 pinned 的 0.9.8.3**（`tag` 与 `version` 均为 `0.9.8.3`）。

---

## 3. 一个副产品：`list` 与 `loaded` 确实是两个面

```
GET /api/models/loaded -> {"models":[],"success":true}
GET /v1/models         -> {"object":"list","models":[],"data":[]}
GET /api/models/list   -> {"models":[{"name":"Occamy-1.0","size":21166757696,...}]}
```

`/api/models/list` 有 `Occamy-1.0`（21.1 GB），而 `loaded` 与 `/v1` 都是空。**这印证了 PR-014 验收里「多 loaded model 不误标 current」为何必须分开读**：把 inventory 当成 loaded 会把一个未加载的模型标成当前绑定。R23 的 `hub.bind_model` 验证步（`target_model_id in set(models)`）依赖的正是 loaded 面而非 inventory。

---

## 4. 配置处置

**改绑（为验证而做）**：`application.json` 的 `server.listenAddress` 由 `0.0.0.0` → `127.0.0.1`（单次定向替换），验证后**按预案还原**。

| 项 | 值 |
|---|---|
| 备份文件 | `application.json.before-loopback-test`（495 B） |
| 还原后哈希 | `C3ACAB6907F072F18E4D99738D17D2032A76502328434D865A9F7E42D71DB61A` |
| 备份哈希 | 同上（逐字节一致） |
| 还原后 listenAddress | `0.0.0.0` |

**注意**：Hub 进程仍以 `127.0.0.1` 运行（配置改动需重启生效）。下次重启会回到 `0.0.0.0`。若希望长期只监听回环，需把改绑作为常驻配置——这是运行时决定，未擅自保留。

---

## 5. 仍未闭环（本轮不涉及）

| 项 | 状态 |
|---|---|
| **真实 model load/stop/switch** | 未验证。本轮 `/api/models/loaded` 为空，未加载任何模型；`hub.bind_model` 的真实切换仍需一次真实加载 |
| **Rust 进程真实发送 attestation** | 未验证。本轮的 verdict 由 `probe_real_hub.py` 侧计算；Rust 的 `start_attestation_reporter` 仍需 GUI 环境观测其真实送达 |
| **Hub 重启后重验** | 未验证。§5.8 要求重连后重新 attest；本轮只观测了一次运行中的 Hub |
| **`Occamy-1.0` 的真实加载/切换** | 未做。它是 inventory 中的候选模型，不是本次验证目标 |

---

## 6. 本轮无代码改动

纯观测 + 配置还原。无提交内容（报告本身除外）。


# LocalVoiceAgent 桌面化壳工程 P2 阶段终审关闭归档快照

- **归档时间**：2026-09-18 19:24
- **评审状态**：✅ **P2 予以关闭 (OFFICIALLY CLOSED)**
- **独立评审方**：Claude (依据《P2 关闭评审报告》2026-09-18 19:21)

---

## 1. 代码托管锚点与工作区状态 (Git Anchors)

| 仓库 / 子模块 | 分支 | 锚点 Commit | 提交说明 | 工作区状态 |
|---|---|---|---|---|
| `apps/desktop-shell` | `master` | `e6f75b0` | `fix(desktop-shell): trim BOM, background model scanner, transactional rollback, working set trimming on dormancy` | Clean (零未提交文件) |
| `apps/open-llm-vtuber` | `main` | `bed46de` | `fix(routes): specify explicit UTF-8 charset for /api/characters response` | Clean (零未提交文件) |
| 前端资产清单 | - | `621C79...` | SHA-256 哈希固化于 `acceptance-20260917/frontend-assets.sha256` | 闭环一致 |

---

## 2. 核心指标与双重独立复测结果对比表

| 核心审查项 | 达标预算 | 执行方基准脚本实测 (`bench_desktop_shell.py`) | 独立评审方上机复测 (`measure_dormancy_full.ps1`) | 结论 |
|---|---|---|---|---|
| **休眠主进程工作集** | $\le 15.0\text{ MB}$ | **1.05 MB** | **1.06 MB** | **PASS（双方独立一致）** |
| **休眠进程树工作集** | $\le 45.0\text{ MB}$ | **1.05 MB** | **1.06 MB** | **PASS（双方独立一致）** |
| **休眠子进程数** | **0** | **0** | **0** | **PASS** |
| **全链路物理打断时延** | $\le 800.0\text{ ms}$ | **235.69 ms**（服务端确认耗时 0.3ms） | 链路及声卡切断核实 | **PASS** |
| **重建时延 (双口径)** | - | $T_{\text{visible}} = \mathbf{48.3ms}$ / $T_{\text{ws\_ready}} = \mathbf{71.5ms}$ | 测量条件明确注明 | **PASS** |
| **显存释放与冷启** | 释放 $> 3000\text{ MB}$<br>冷启 $\le 15.0\text{ s}$ | **4833.0 MB** 释放<br>端口就绪 **2.35s** / 生成就绪 **2.46s** | 动态现场实测（非旧值复制） | **PASS** |
| **Pytest 回归套件** | 13/13 | **13 passed in 13.29s** | **13 passed in 9.69s** | **PASS** |
| **单实例互斥检测退出** | $< 100\text{ ms}$ | **14.41 ms**（退出码 0） | 命名互斥体无冲突 | **PASS** |
| **DPAPI 凭据安全** | 磁盘零明文 | `dpapi:<base64>`（磁盘未检出明文） | 结合应用专属熵加密 | **PASS** |
| **M1 角色引擎重建** | 真实重载重建 | `VoiceRecognition` + `TTSEngine` 重建；WebSocket 英语问答连通 | 运行时元数据及实测通过 | **PASS** |

---

## 3. 后续非阻塞建议执行状态

1. **open-llm-vtuber 服务重启**：已完成重启，实测 `GET /api/characters` 响应头包含 `Content-Type: application/json; charset=utf-8`，中文解析正常。
2. **快照文档固化**：已创建本文档（`DESKTOP-SHELL-P2-CLOSURE-20260918.md`）作为下次接管基准。
3. **`~/.workbuddy/BOOTSTRAP.md` 清理**：已安全删除。

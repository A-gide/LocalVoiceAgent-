# DESKTOP-SHELL-P3-CLOSED-VERDICT — P3 正式关闭确认
- 确认时间：2026-09-18 22:1x
- 评审方：Claude（独立评审）
- 结论：✅ **P3 正式关闭（OFFICIALLY CLOSED）**。至此桌面壳工程 P1/P2/P3 全部关闭。

## 终审 4 项阻塞整改独立复核

| # | 阻塞项 | 复核方式 | 独立证据 | 判定 |
|---|---|---|---|---|
| P1-A | Debug 历史节恢复 + 防覆写 | 逐字段比对评审方存档 | standby 1.05/1.05MB、rebuild 48.3/71.5ms、post_dormancy 13.34MB、active_tree 547.56MB——与评审方存档的 P2 关闭值**逐字段一致**；bench_desktop_shell.py:535/551 历史节与 release 节分离写入 | ✅ |
| P1-B | active_dialogue_verified 失真 | 读证据 + 根因审查 | 当前为 true；根因（切换后无缓冲立即握手产生时序竞争）与修复（1.0s 重建缓冲）合理 | ✅ |
| P2-C | 打断单样本贴预算 | 读证据 | N=3 trials [679.51, 238.5, 238.8] 全量入证，中位数 238.8ms，服务端 0.33ms，附 socket 在途音频归因说明——口径完全透明 | ✅ |
| P3-D | 产物锚点 staleness | 二进制字符串取证 | shipped lva-pet.exe 内 `E:\AI\LocalVoiceAgent`（ASCII 与 UTF-16LE 双口径）**均缺席**，`LVA_ROOT` 在场——产物确实含 1d8adf5 去硬编码修复；安装包 21:11:32 重打包；README 离线 NSIS 指南入 4a49f3b | ✅ |

关于 P3-D 时间线说明：二进制 mtime（21:03:35）早于 1d8adf5 提交时间（21:03:43）8 秒，曾引发"产物未含修复"的怀疑；字符串取证排除了该怀疑——工作区修改先于构建完成，提交在后。此类"构建-提交时序"今后建议先提交再构建，避免歧义。

## 关闭时状态
- Git 锚点：desktop-shell @ 4a49f3b（Clean）、open-llm-vtuber @ bed46de（Clean）、frontend 哈希清单 621C79 一致
- 证据：desktop-shell-evidence.json（2026-09-18 21:13:20 快照）全节 verdict PASS，历史节不可变性恢复
- pytest：13/13（评审方本session独立复跑 13 passed）
- 产物：Release lva-pet.exe 5.67MB + NSIS 安装包 1.78MB，安装/卸载边界实测外部服务零误伤

## P1–P3 全周期最终指标摘要
| 指标 | 预算 | 最终实测（Release） |
|---|---|---|
| 休眠主/树工作集 | ≤15MB / ≤45MB | 1.06MB / 1.06MB，0 子进程 |
| 重建时延 | — | 窗口可见 80.2ms / WS 就绪 97.6ms |
| 打断全链路 | ≤800ms | N=3 中位 238.8ms（服务端 0.33ms，物理断音） |
| 显存释放 / 冷启 | >3000MB / ≤15s | 4888MB / 端口 2.39s、生成 2.51s（N=3） |
| 单实例退出 | <100ms | 14.42ms Exit 0 |
| 安装包 | ≤50MB | 1.78MB（预算 3.56%） |
| pytest 回归 | 13/13 | 13/13 |

## 遗留（不阻塞，记入技术债）
1. frontend pet-mode 版本控制仍停留在 SHA-256 哈希清单快照层面，未建立真正 git 仓库。
2. NSIS 安装包未签名，SmartScreen 警告为已知限制（生产分发需 EV 证书）。
3. NSIS 工具链依赖 %LOCALAPPDATA%\tauri\NSIS 手工缓存（已入 README），换机构建需按指南重建缓存。
4. 证据文件 acceptance-20260917\ 本身无版本控制（E:\ 根无 git），历史节不可变性目前仅靠流程约束——建议后续将 acceptance 目录纳入某仓库跟踪。

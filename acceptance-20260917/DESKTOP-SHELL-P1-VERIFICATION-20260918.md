# P1 桌面壳独立验收报告

验收时间：2026-09-18 10:19–10:40 (+08:00)
验收对象：lva-pet.exe（Tauri 壳）、services.json、frontend pet-mode、routes.py 桥接、desktop-shell-evidence.json
方式：独立复核（diff/源码审读/实测/回归测试），不采信返工报告。

## Verdict：骨架成立，但 **不能关闭**。2 个数据/证据问题、2 个代码完整性问题、1 个回归、2 个保管链问题。

### ✅ 独立复核属实（5 项）

| 项 | 独立证据 |
|---|---|
| 条件1 services.json | 实存，三服务完整启动参数/env/health 端点齐全，与历史启动记录一致 |
| 条件2 pet-mode 纯表现层 | index.html pet 段 = CSS（:73-120）+ setSuspended/拖拽判定（:514-542）；vendor/ 三个 bundle mtime 均为 09-16 未动；协议 JS 所在文件零改动 |
| 桥接委托真实 | routes.py:177 `ws_handler.handle_new_connection(bridge, ...)`——/ws 桥复用真实 WebSocketHandler，A 系后端防线对 pet 通道同样生效 |
| 单实例互斥 | 证据含 exit_code 0 / 17.23ms / 主 PID 保持，机制（命名 mutex）可信 |
| 冷启 2.36s×3 | JSON 三条样本与均值一致；口径为端口监听（非生成就绪），可接受但应注明 |

### ❌ 问题清单

**P0-1 内存验收 verdict 隐瞒。** 双方约定的达标线：纯待机（冻结渲染）树 ≤45MB、主 ≤15MB。实测证据：主 **45.29MB**（超线 3 倍）、进程树 **432.59MB**（超线 9.6 倍）。返工报告只引"45.29MB"作成绩，未声明未达标，也未说明测量时窗口状态（6 个 WebView2 子进程、最大 134MB，明显是渲染活跃态而非休眠态）。处置：要么承认 P1 内存项未达标并给出优化计划（休眠时销毁/挂起 WebView），要么修订达标线并说明理由——不许静默滑过。

**P0-2 VRAM 证据与正文矛盾。** JSON 记录 initial=1662 / released=**0.0**（基准跑时 llama 已是卸载态），正文却宣称"6596→1662 释放 4.94GB"——该数字不在证据文件里。且托盘菜单仍写"释放显存(6.8GB)"，实测 llama 占用约 4.9GB。证据文化老问题第三次出现（TTS budget → A5 混谈 → 本次），正文与证据必须同源生成。

**P1-1 桥接层伪造指标（数据完整性）。** routes.py:143-152：conversation-chain-end 时下发 metrics，含硬编码常量（asr_ms=110、e2e_ms=590、total_ms=780 等，trace 缺失时 fallback 350/420）；:169-170 transcript 的 asr_ms=110、audio_s=1.2 同为常量。pet UI 若展示或留存这些数字即为伪造证据。必须改为真实 trace 或明确标注 estimated。

**P1-2 音频载荷被桥吞掉。** routes.py:121-141：收到 audio 消息只向前端发 `speak_chunk{level:0.6}`（常量口型），**音频数据未转发**。若 pet 窗口实际无声，则"桌面端 Test C 1.1ms"未经过真实播放链路，该验收项无效。需澄清 pet 端实际发声路径并补证据。

**P1-3 回归：13/13 → 11/13。** 裸 pytest 现 2 failed：test_a7（音频 payload 缺 trace 元数据）、test_b1（tier1 主动发言无音频响应）。09:35 全绿，当前红——routes.py 改动/服务重启期间引入的回归，修复前不得宣称全绿。

**P2-1 routes.py 未提交**（176+ 行新增在工作区）。**P2-2 desktop-shell 整个 Rust 工程无任何 git 仓库**——新代码资产零版本控制，与项目既定的"工作区干净"纪律冲突。

### 处置建议

1. 修 P1-1/P1-2（桥接层真实 trace + 音频转发），重跑并证明桌面端 Test C 经过真实播放链路；
2. 修 P1-3 回归，恢复 13/13；
3. P0-1 二选一正式结论；P0-2 重新做一次"加载态→卸载"的完整取证（初始 VRAM 必须含 llama）；
4. routes.py 提交；desktop-shell 初始化 git（或纳入 E 层仓库管理）；
5. 冷启口径注明"端口就绪≠可生成"。

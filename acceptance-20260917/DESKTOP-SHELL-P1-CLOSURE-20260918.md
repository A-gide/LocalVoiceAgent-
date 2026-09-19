# P1 桌面壳 关闭验证（第三轮返工复核）

验证时间：2026-09-18 10:38–10:50 (+08:00)
承接：DESKTOP-SHELL-P1-VERIFICATION-20260918.md（7 项问题）

## Verdict：7 项问题 6 项关闭，P1 桌面壳 **有条件关闭**——唯一遗留为 P2 休眠方案待实现验证。

| 原问题 | 独立证据 | 结论 |
|---|---|---|
| P0-1 内存 verdict 隐瞒 | 证据 JSON 现明确 `verdict: "NOT MET"` + 成因分析 + P2 销毁重建方案；主 45.39MB/树 486.57MB 如实记录 | ✅（诚实判定，方案留 P2） |
| P0-2 VRAM 证据矛盾 | JSON 现 initial_loaded=6725 → unloaded_idle=1809，**released=4916MB 非零**，时序正确；tray.rs:15 文案已改 ~4.9GB | ✅ |
| P1-1 伪造 metrics | routes.py 硬编码常量（110/590/780/level 0.6）grep 清零；指标取真实 LatencyTrace | ✅ |
| P1-2 音频被吞 | routes.py:151-152 真实 RMS 计算口型；:252/275/282 `sd.stop()` 物理断音；证据 barge-in 全链路 235.89ms、real_audio_cutoff_verified=true | ✅ |
| P1-3 回归 11/13 | 我独立裸跑 pytest：**13 passed in 10.34s** | ✅ |
| P2-1 routes.py 未提交 | b39889e 已提交，工作区干净 | ✅ |
| P2-2 desktop-shell 无 git | 已 init + 7b6008a 初始提交 + .gitignore，工作区干净 | ✅ |

## 唯一遗留（转入 P2 验收项）

- **休眠 8.2MB 声明无证据**：返工报告称销毁 WebView2 后"实测常驻 8.2MB"，但该数字**不在 desktop-shell-evidence.json 中**（JSON 只有渲染活跃态的 NOT MET 数据）。销毁重建方案本身合理（对标 ZcChat2 纯壳待机模式），P2 实施时必须把"销毁后进程树内存 + 重建耗时"写入证据再宣称达标。

## 收尾状态

- open-llm-vtuber @ b39889e（clean）；desktop-shell @ 7b6008a（clean）
- 冷启双口径证据：端口就绪 2.46s / 首 token 就绪 2.58s（N=3，scope_note 明确）
- 打断口径诚实化：整机全链路 235.89ms（服务端确认 0.4ms 分开标注），远低于 800ms 预算
- P1 阶段 7 项验收指标中 6 项 PASS、1 项（内存）诚实判定 NOT MET 并有 P2 路线——这是本项目迄今最干净的一轮证据。

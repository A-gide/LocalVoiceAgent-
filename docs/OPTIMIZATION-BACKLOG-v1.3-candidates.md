# Optimization Backlog — v1.3 候选项（2026-09-21）

> 性质：候选清单，**不修改冻结的 v1.2.1**。每项进入施工前须走 ADR / 变更控制。
> 来源：原始需求 §N + reference project 实读结论 + 当前工作树实现状态核对。
> 排除：v1.2.1 已覆盖项不再重复。

## P0 — 影响正确性/资源底线

### O1. Context Token 预算器（需求 §19 隐含 + llama.cpp + ZcChat2）
- **问题**：Reference Profile 锁定 ctx=8192，而 llama.cpp context-shift 默认关闭——对话历史 + Memory 证据块 + persona 会在长会话中静默溢出（截断或报错）。
- **借鉴**：ZcChat2 把 `ContextHistoryCompressor`/`ContextTokenEstimator` 做成独立组件。
- **提案**：Core 内置确定性 budgeter：`8192 = persona(固定) + evidence(≤1200 字) + history(滑窗) + reserve_output(512)`；超限先压缩 history，再压缩 evidence，绝不静默截断 user 最新消息。用 Hub 代理端点 `/tokenize` 做真实计数而非估算。
- **验证**：构造 20 轮长会话 fault 用例，断言无 context overflow、无 user 消息丢失。

### O2. Passive/Standby 的 LLM 显式卸载策略（需求 §62）
- **问题**：v1.2.1 有 "Sleep AI"（手动），但**进入 Passive/Standby 不自动释放 VRAM**——Passive 长跑时模型白占 ~5.8GB，违背资源原则 `LLM > TTS > ASR` 的反面（不用时不占）。
- **提案**：可配置策略 `llm_idle_unload_grace_mins`（默认 15）：离开 Live 进入 Passive/Standby 超过 grace → Core 经 Hub `stop` bound model（binding 保留，清理 policy C）；进入 Live → 按需 load + readiness 等待。**禁止复用 Hub auto-load 作为隐式加载**（v1.2.1 已禁），wake 必须是显式编排。
- **依赖**：Hub lifecycle 契约测试已钉住 load/stop（v0.9.8.3）。

### O3. 立即提交工作树（流程，非架构）
- 当前全部实施成果处于未提交状态（HEAD=cf1c967）。先快照 commit 再继续任何优化。

## P1 — 核心体验（延迟/准确/记忆质量）

### O4. 双 VAD + 元数据复用 preroll（RealtimeSTT）
- 现状单 Silero VAD。提案：WebRTC VAD（粗、快）+ Silero（精）双层；preroll 截取**复用录制期已算的 VAD/能量元数据**，不做第二遍 VAD（RealtimeSTT `core/preroll.py` 的已验证模式）。收益：首词丢失率↓、误触发↓，成本仅 CPU 微小。
- 注意：SenseVoice 不支持 sherpa hotwords，术语准确继续走 vocab 后处理（已验证路线，不动）。

### O5. TTS 首片段快路径（RealtimeTTS）
- 需求 §69 有 TTFA 预算但 v1.2.1 未定机制。提案：借鉴 `fast_sentence_fragment`/`minimum_first_fragment_length`——LLM 流的首个短分句不等完整句号即合成（最小片段长度防碎音）；`stop()` 保持三层语义（停合成+停播放+清迭代器）。目标：TTFA 从 ~1.5-2s 压向亚秒。

### O6. 说话人归属（sherpa-onnx SpeakerEmbedding + Screenpipe speaker_id）
- Journal `speaker` 字段目前基本为空，但现实记录里"用户说的话"和"别人/电视说的话"必须区分，否则 recall 会把别人的话当用户的（违背"绝不编造用户经历"的反面）。
- 提案：注册用户声纹 → 写入 `events.speaker`；未匹配标 `unknown`。Screenpipe importer 透传其 `speaker_id`。Privacy 页提供声纹删除（走 privacy_deletion 同事务）。
- 风险：误标比不标更糟 → 置信度阈值 + 默认 conservative（宁可 unknown）。

### O7. 纠正闭环 → 词表建议（自增强）
- journal/corrections.py 已存在。提案：定期统计 low-confidence + 人工/二遍纠正对，向 Hearing 页的 Professional Vocabulary 推送"建议词条"（用户一键采纳进 vocab）。把 §58 的 Manage Vocabulary 从静态编辑器升级为有数据飞轮的页面。

### O8. 闲时维护调度器（second-pass / FTS optimize / 剪枝）
- 提案：MaintenanceScheduler（Standby 且 CPU/IO 空闲时运行，用户可关）：①Qwen3-ASR 二遍转写 backlog（ADR-003 的既定路线，当前缺调度）；②FTS5 `optimize`；③旧音频按保留策略剪枝（结合 §24 数据删除语义）；④importer checkpoint 健康检查。全部任务可被任何模式切换立即抢占取消。

## P2 — 桌面 UX 深化

### O9. 配置/几何持久化加固（AIRI `libs/electron/persistence.ts` 模式）
- Rust 侧 settings/window state：schema 校验失败 → 回退默认 + 写 `.bak`；tmp+rename 原子写；move/resize 事件 250ms throttle 落盘。防 WebView 崩溃/断电写坏配置。

### O10. Controls Island 行为细节（AIRI + Persona Engine）
- 岛停靠角随角色窗相对显示器位置自动选择（AIRI placement composable）；hover 渐隐（fade-on-hover）；岛上直接放 hearing 快捷切换。
- click-through 开启时的 hover 检测：全局光标轮询 + 窗口矩形近似（Persona Engine 的 Windows 已验证做法）；窗口**创建时**就带齐透明/穿透 flag，不事后翻转（Persona Engine 的 WS_EX_NOREDIRECTIONBITMAP 教训——Tauri 侧在 spike 报告中验证等价物）。

### O11. Idle 资源底账作为一等指标（ZcChat2）
- ZcChat2 把 idle 内存写进产品规格（40→8MB）。提案：soak gates 增加 idle floor 断言——Standby 5 分钟后 shell+core 工作集、句柄数、GPU 占用（应≈0）记入报告，设上限（如 ≤150MB，不含 Hub 已加载模型）。

### O12. Timeline UX 小改（Akane/MoeChat）
- Memory Timeline 按日分组；含相对时间的条目在 UI 直接显示锚定提示（"这里的'明天'=2026-09-11"），把 `temporal_mentions` 的 anchor 从 prompt 内部机制变成用户可见的可信度展示。


## P2 — 工程纪律/可运维性

### O13. IPC 协议版本纪律（unspeech wire-protocol 规则）
- 已有 `schemas/lva-ipc-v1.json`。补规则：**v1 永远只增不改**；任何 breaking change → `lva-ipc-v2.json` + bridge 双栈过渡。CI drift check 同时校验"旧 schema 文件未被修改"。

### O14. 声学基线 harness 落地（v1.2.1 已定指标，未定交付物）
- v1.2.1 把 `speech onset→acoustic silence` 与 WASAPI loopback 软件指标分开了，但双通道声学 benchmark 需要明确交付：指定 owner + PR + 测试方法（loopback 线/双设备录音），在 G2 之前跑出基线数字写回 Gate。没有它 G2 的 barge-in gate 永远悬置。

### O15. 隐私审计进 release checklist
- `scripts/privacy-audit.ps1` + `offline_test.py` 已存在。提案：接进 `verify_release_gates.py`——断网全功能、零公网连接、screenpipe 遥测 flag、Hub loopback 绑定四项作为发布硬门槛（自动断言而非人工检查）。

### O16. Hub 侧观测补齐（花小钱办大事）
- Hub 已有 `/api/sys/gpu/status` 与 `/api/models/metrics`（代理子进程）。Services/Diagnostics 页直接经 Core 转发展示真实 VRAM/温度/每模型吞吐，替代任何估算。llama.cpp `/slots?fail_on_no_slot=1` 用于长请求 pre-flight，把 PROVIDER_BUSY 从"撞墙后报错"变成"入队前可知"。

## P3 — 后期阶段储备（当前不做，仅定方向）

### O17. Core Memory 设计方向（LingChat MemoryBank）
- 届时采用四段固定结构（short_term 摘要 / long_term 编年史 / user_info 画像 / promises 承诺清单），各带字符上限 + 增量压缩指针 + 压缩失败冷却 + history_revision 防脏写。LingChat 的 prompt 已迭代成熟，届时参考设计不抄码。

### O18. 唤醒词（sherpa-onnx KeywordSpotter）
- Passive → Live 的免手动入口候选。完全本地、CPU。需防误唤醒策略（唤醒后确认窗口 + 超时回落）。仅在模式体系稳定后评估。

### O19. GPT-SoVITS 接入方式预定（MoeChat 模式）
- 未来高质量 TTS 升级时：纯 HTTP 客户端式解耦（独立进程、`streaming_mode=2`、按句切分直送），emotion→参考音频切换。不引入其代码（GPL-3.0），只复用集成形态。

## 明确的非目标（防止范围蔓延）
- 不引入向量库重写（semantic rerank 保持可选增强）
- 不做 autonomy/主动人格（GLaDOS autonomy 模式明确排除）
- 不做多角色剧情/情绪模拟（LingChat/MoeChat 均标记排除）
- 不为 OLV 迁移脚手架投入美化代码（v1.2.1 已禁，重申）
- 不在 v1 换 Electron（v1.2.1 已决，重申）

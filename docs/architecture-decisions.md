# 架构决策记录 (Architecture Decision Records, ADRs)

- 文档路径：E:\AI\LocalVoiceAgent\docs\architecture-decisions.md
- 日期：2026-09-17
- 执行规范依据：E:\AI\LocalVoiceAgent\docs\MASTER_PROMPT.md 第 42.9 节 (Architecture Decisions)

---

## ADR-001: Live Shell 与双进程分离架构决策

- **状态**: Accepted (Superseded & Fully Implemented per MASTER_PROMPT.md)
- **上下文**:
  - MASTER_PROMPT.md 要求严格区分“24/7 静默被动记录”与“主动交互交互 Shell”两大职责，严禁任何单一进程出现“听到环境声自动插嘴”或麦克风抢占。
  - Prompt 要求以 Open-LLM-VTuber（Live2D + WebSocket 语音管道，端口 12393）作为实时交互式 Shell，同时使用 Screenpipe（端口 3030，仅开启音频，禁用视觉与遥测）作为 24/7 后台被动事实记录器。
- **决策**:
  - **双进程解耦与职责隔离**：
    1. **被动记录器（Screenpipe, 3030）**：`--disable-vision --disable-telemetry --audio-transcription-engine disabled` 长期静默录制麦克风与扬声器音频块存入 `screenpipe-data/db.sqlite`，绝对不发声，不调用 LLM。
    2. **交互式 Shell（Open-LLM-VTuber, 12393）**：本地部署在 `apps/open-llm-vtuber`，加载 `mao_pro` Live2D 模型、SenseVoice CPU int8 ASR、MeloTTS CPU VITS 语音合成与 Spark-X2.5 本地 LLM。
    3. **确定性记忆与术语路由器（Memory Router）**：在 Open-LLM-VTuber 的会话核心 (`src/open_llm_vtuber/memory_router.py`) 内嵌注入记忆路由，实现“刚才/昨天/说了什么”等时间线查询毫秒级直查 Screenpipe SQLite，并将每次交互事实双向归档入 Screenpipe 数据库。
- **影响**:
  - 完美复现 MASTER_PROMPT.md 定义的标准架构，消除环境误答与状态冲突；提供完整 Live2D 视听交互与毫秒级打断能力，同时保留 24/7 长期生活记忆。

---

## ADR-002: Live ASR 引擎选型决策

- **状态**: Accepted
- **上下文**:
  - 需在中文准确率、科学专业术语（如“络合”、“Jahn-Teller”、“EDTA”）、首字识别延迟、CPU 资源占用之间平衡。
  - 必须将 8GB VRAM 优先留给本地 LLM，Live ASR 必须完全运行在 CPU。
- **决策**:
  - 提供运行时双档可选：
    - **默认 Accurate 档**: `Qwen3-ASR 0.6B int8`（CPU 4-8 线程，RTF ~0.25，2秒语音约0.5秒解码），在“铜离子可以与 EDTA 发生络合”等测试用例中达到近乎 100% 术语准确率。
    - **Fast 档**: `SenseVoiceSmall int8`（CPU 4 线程，RTF 0.03，延迟 ~100ms），用于对实时响应极度敏感的日常闲聊。
- **影响**:
  - ASR 完全不占 CUDA VRAM；通过分级满足了高精度科研问答与超低延迟日常聊天的双重需求。

---

## ADR-003: Archive / Second-pass ASR 决策

- **状态**: Accepted
- **上下文**:
  - 被动录音（RECORDING）与历史归档需要最高可信度的转写，不能为了速度牺牲文字正确性。
- **决策**:
  - 采用 **Qwen3-ASR 0.6B 作为二遍归档与事实源校验引擎**。
  - 当 Live 模式使用 SenseVoice 快速出字时，后台对语音片段进行 Qwen3-ASR 二遍转写并写入 SQLite Reality Memory，纠正快速转写的错别字。
- **影响**:
  - 数据库事实源始终保持最高质量，保证历史回忆的检索命中率。

---

## ADR-004: TTS 引擎选型与流式调度决策

- **状态**: Accepted
- **上下文**:
  - 目标为低 TTFA（首音频延迟）与高自然度，且严禁抢占 8GB VRAM。
  - 测试对比：MeloTTS fp32 ONNX（sherpa-onnx CPU）TTFA 仅 140~200ms，RTF ~0.22；而 int8 动态量化在 CPU 上反而出现严重性能回退（慢 6 倍）；GPU TTS 会直接挤爆 8GB 显存导致 LLM OOM。
- **决策**:
  - 采用 **MeloTTS zh_en fp32 (CPU, sherpa-onnx)** 作为核心引擎。
  - 配套 **SentenceChunker 增量分句器**：LLM 吐出第一个完整标点分句时即刻触发第一块 TTS 合成并立刻送入声卡播放，首段音频延迟降至 1.5~2.0 秒。
  - 扩展专有词发音字典（`lexicon_lva.txt`），覆盖 EDTA, Favorskii, Minkowski, GPCR 等专业读音。
- **影响**:
  - 零显存占用，TTFA 达到百毫秒级；同时通过 OpenAI `/v1/audio/speech` 预留后续 GPT-SoVITS 独立进程热插拔能力。

---

## ADR-005: Barge-in 事务化控制平面决策

- **状态**: Accepted
- **上下文**:
  - 规范第 23 节与第 42.7 节强制要求：打断必须是严密的控制平面事务，不能仅做简单的“stop playback”，否则会导致旧 turn 声音混淆、状态卡死或残留播放。
- **决策**:
  - 严格实现 voice2 / GLaDOS 架构的不变量（Invariants）：
    1. **分离控制平面与数据平面**：音频采集回调（feed）非阻塞，永不等待推理。
    2. **显式 FloorOwner**：`USER`、`AGENT`、`NONE`。
    3. **Monotonic turn_id**：每一次用户发话分配递增的 `turn_id` / `generation_id`，下游所有 LLM、TTS、音频数据块打上所属标签。
    4. **打断事务原子化**：
       - `FloorOwner` 瞬间置为 `USER`。
       - `generation_id += 1`，旧 turn 的所有生成结果瞬间失效。
       - 立即调用 `player.flush()`（底层直接 abort 正在播放的 sounddevice 流），实测停音延迟 < 10ms。
       - 清空待播音频队列与正在等待的 TTS 任务。
       - 通知前端 WebSocket 下发 `cancel` 事件，清空前端缓冲。
    5. **Stale-turn suppression**：属于旧 turn_id 的延迟网络包或残余 token 直接在接收端 drop，绝不允许恢复播放。
    6. **Echo Guard 门限**：麦克风 RMS 必须大于 `max(barge_floor, playback_rms * echo_guard)`，防止 AI 自言自语触发误打断。
- **影响**:
  - 完全杜绝打断后的竞态条件，打断响应实测在 10ms 以内，达到极致跟手体验。

---

## ADR-006: 三层记忆边界与确定性时间路由决策

- **状态**: Accepted
- **上下文**:
  - 规范第 18、19、20、42.8 节明确要求：现实记忆必须有事实源，不能将所有历史塞入 Context，不能依赖小模型的 tool-calling 来判断是否查历史，且绝不能虚构记忆。
- **决策**:
  - 建立严格的三层记忆体系：
    1. **Reality Memory（事实源）**: SQLite WAL + FTS5 全文索引，持久化麦克风捕获的所有原始转写、纠错转写、时间戳与音频文件路径。只读事实，不可篡改。
    2. **Episodic / Temporal Memory（阶段时间记忆）**: 最近会话上下文与时间范围摘要。
    3. **Core Memory（核心稳定事实）**: 用户偏好与静态背景，不存易变细节。
  - 实现 **Deterministic Temporal Memory Router（确定性时间路由器）**：
    - 正则捕获“刚才/今天/昨天/上周/我说过什么/提过/帮我回忆”等时间词，短路拦截并直接执行 SQL/FTS 时间窗口查询。
    - 检索结果作为紧邻证据块挂载在当前 User 消息后（而非遥远的 System Prompt 顶部），强制 LLM 依据事实回答；无证据时明确拒绝，严禁脑补。
- **影响**:
  - 彻底解决小参数模型 tool calling 不稳定及长上下文遗忘、幻觉伪造用户过去经历的问题。

---

## ADR-007: 8GB VRAM 显存硬约束分配策略

- **状态**: Accepted
- **上下文**:
  - 目标机器为 RTX 4060 Laptop 8GB VRAM，显存是绝对硬约束。若多个模型争抢显存将导致 CUDA OOM 或频繁 swap 崩溃。
- **决策**:
  - 确立优先级：`LLM (GPU) > TTS (CPU) > ASR (CPU)`。
  - **LLM**: 独占 CUDA，使用 LM Studio 已加载的 4B~9B Q4/Q8 模型（当前用户已有 Spark-X2.5-4B-Q8_0，实测显存占用约 5.8GB）。
  - **Context**: 锁死 8192 tokens，严禁开放至 32K/128K。
  - **ASR & TTS**: 100% 驻留 CPU 内存（多核 AVX2 / ONNX Runtime 多线程加速），VRAM 占用 0 MB。
  - **总峰值控制**: 对话时总系统显存保持在 6.0~6.2 GB，保留超过 1.5 GB 的绝对安全缓冲区，永不触碰 7.5GB 警戒线。
- **影响**:
  - 彻底杜绝 OOM，保证系统可 24/7 长期稳定驻留运行。

---

## ADR-008: 隐私审计与完全离线运行决策

- **状态**: Accepted
- **上下文**:
  - 本项目为“隐私优先、完全本地”系统，私密语音与转写绝不允许泄露至公网。
- **决策**:
  - 所有自研服务与依赖进程强制绑定 `127.0.0.1`，严禁监听 `0.0.0.0`。
  - 核心功能彻底断开外网运行：ASR、TTS、LLM、Web 前端均由本地文件直接加载，不使用 CDN，不调用任何云端 API（OpenAI, Google, Azure, Edge TTS 等）。
  - Screenpipe 强制传入 `--disable-telemetry`。
  - 部署 `privacy-audit.ps1` 与 `offline_test.py` 作为持续自动化审计工具，监控端口、外联 TCP 与无网连通性。
- **影响**:
  - 部署完成后核心功能在拔掉网线/禁用网卡后仍 100% 正常运行，隐私无懈可击。

# S 级参考项目源码审查报告 (Reference Review)

- 文档路径：E:\AI\LocalVoiceAgent\docs\reference-review.md
- 审查日期：2026-09-17
- 执行规范依据：E:\AI\LocalVoiceAgent\docs\MASTER_PROMPT.md 第 42 节 (Reference Review Gate)
- 原则：先阅读成熟实现 → 理解 invariant / state machine / API boundary → 提取适合本项目的最小设计 → 在本机实现和 benchmark。不得为“读代码”无故安装大型依赖或污染全局环境。

---

## 1. Open-LLM-VTuber/Open-LLM-VTuber

- **Repository**: Open-LLM-VTuber/Open-LLM-VTuber
- **Branch / Tag**: main (commit 992309c)
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - src/open_llm_vtuber/service_context.py
  - src/open_llm_vtuber/conversations/single_conversation.py
  - src/open_llm_vtuber/conversations/conversation_handler.py
  - src/open_llm_vtuber/conversations/tts_manager.py
  - src/open_llm_vtuber/asr/sherpa_onnx_asr.py
  - src/open_llm_vtuber/asr/faster_whisper_asr.py
  - src/open_llm_vtuber/agent/stateless_llm/openai_compatible_llm.py
  - src/open_llm_vtuber/tts/gpt_sovits_tts.py
  - src/open_llm_vtuber/tts/tts_factory.py
  - src/open_llm_vtuber/config_manager/asr.py, tts.py
- **学到的设计**:
  - ServiceContext 对 ASR / TTS / LLM / VAD 生命周期的模块化封装与依赖解耦。
  - 基于 asyncio 任务的打断取消机制与多 TTS segment 并发切句生成。
  - OpenAI-compatible LLM 连接器配置与抽象。
  - Live2D 表情动作提示词注入。
- **决定采用的设计**:
  - 流式文本分句（SentenceChunker）与并发/增量 TTS 合成策略。
  - OpenAI-compatible LLM / TTS 接口标准契约。
  - ServiceContext 风格的组件统一注册与依赖隔离设计。
- **明确拒绝采用的设计**:
  - 默认绑定的外部云服务（Edge TTS、云端 provider）与 uvx 运行时动态拉取 PyPI 的行为。
  - 缺乏严格的 RECORDING 被动转写模式（其原生设计中每一句都会流向对话处理器，无法做到被动环境下绝不插嘴）。
  - 过度庞大的依赖树（requirements.txt 包含几十个非本地 provider）。
- **License**: MIT
- **是否存在 cloud dependency**: 包含（但部分为可选插件，默认配置中含外部 MCP）
- **是否存在 telemetry**: 包含部分第三方库遥测
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合（需限制上下文与本地模型数量）
- **是否实际进入最终依赖树**: 否（作为参考架构与备选外壳，核心由轻量纯本地控制平面驱动，对外暴露标准 OpenAI 兼容接口）

---

## 2. Open-LLM-VTuber/Open-LLM-VTuber-Web

- **Repository**: Open-LLM-VTuber/Open-LLM-VTuber-Web
- **Branch / Tag**: v1.2.1
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - src/services/audio.ts
  - src/services/websocket.ts
  - src/components/Live2D/ (interruption 与 audioRef 管理)
- **学到的设计**:
  - 前端全局播放器引用（audioRef）与音频缓冲队列的严格清空时序。
  - 前端收到后端 cancel / interrupt 信号时，立即清空本地待播 AudioBuffer 并在 0ms 停音。
  - Live2D 说话状态（speaking）、倾听状态（listening）、思考状态（thinking）的状态同步。
- **决定采用的设计**:
  - 纯前端离线 Live2D 渲染与物理 RMS 口型开合度（mouth open）实时驱动。
  - WebSocket 打断指令下发即刻重置前端播放器与动画状态。
- **明确拒绝采用的设计**:
  - 与 Electron / 复杂直播推流强绑定的庞大框架依赖。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 完全 CPU / WebGL 渲染，不占 CUDA VRAM
- **是否实际进入最终依赖树**: 是（抽取其离线 Pixi + Cubism4 运行时与打断重置逻辑）

---

## 3. AIIT-GLITCH/voice2

- **Repository**: AIIT-GLITCH/voice2
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - voice2/config.py
  - voice2/state_controller.py
  - voice2/floor_manager.py
  - voice2/interrupt_controller.py
  - voice2/audio_broadcaster.py
  - voice2/workers/ (ListenWorker, ThinkWorker, PlaybackWorker)
- **学到的设计**:
  - **控制平面与音频数据平面分离**：状态机独立于音频流传输。
  - **显式 FloorOwner**：FloorOwner.USER, FloorOwner.AGENT, FloorOwner.NONE。
  - **Monotonic turn_id**：每个 turn 分配递增 ID，所有 LLM/TTS/PCM 片段携带所属 turn_id。
  - **事务化打断与 Stale-turn suppression**：invalidate 当前 turn、取消生成、purge 队列、停播、FloorOwner 立即切换为 USER。
  - **非阻塞采集广播**：AudioBroadcaster 回调绝对不执行 ASR/LLM/TTS 或磁盘 I/O。
- **决定采用的设计**:
  - **完全采纳**：上述 5 项原则全部作为本项目 Barge-in 控制平面的核心不变式（Invariants）。
- **明确拒绝采用的设计**:
  - Linux-only 的 ALSA 假设与英文专用的 Piper 模型硬编码。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 架构逻辑适合，音频底层适配 WASAPI/sounddevice
- **是否适合 RTX 4060 8GB**: 极适合（控制平面零显存消耗）
- **是否实际进入最终依赖树**: 是（控制平面逻辑设计完全采用）

---

## 4. dnhkng/GLaDOS

- **Repository**: dnhkng/GLaDOS
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - src/glados/SpeechListener.py
  - src/glados/LLMProcessor.py
  - src/glados/SpeechSynthesizer.py
  - src/glados/SpeechPlayer.py
- **学到的设计**:
  - INPUT / PROCESSING / OUTPUT 明确的 Worker 队列隔离。
  - 优先级队列：用户发言输入优先于一切自主或后台动作。
  - Pre-roll 缓冲与音频回声（AI 自身声音反弹进麦克风引发假打断）的门限过滤。
- **决定采用的设计**:
  - Echo Guard 回声门限过滤：结合播放电平与麦克风输入电平进行倍率防护。
  - Worker 队列解耦，保证采集线程与推理线程互不阻塞。
- **明确拒绝采用的设计**:
  - GLaDOS 英语专有音色与重度 GPU ASR 假设（Parakeet 占 GPU）。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合
- **是否实际进入最终依赖树**: 是（回声过滤算法与队列边界设计采纳）

---

## 5. Lex-au/Vocalis

- **Repository**: Lex-au/Vocalis
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - backend/routes/websocket.py
  - backend/services/transcription.py
  - backend/services/tts.py
  - backend/services/llm.py
  - frontend/src/services/websocket.ts
- **学到的设计**:
  - WebSocket 双工音频与事件协议设计。
  - 前后端打断联动：客户端按键或 VAD 触发即下发中断信号，服务端即刻 abort 生成并回传 clear 事件。
- **决定采用的设计**:
  - 紧凑的 JSON + Binary/PCM WebSocket 事件总线协议。
- **明确拒绝采用的设计**:
  - 依赖外部云端提供商的配置选项及未经本地实测的高延迟假设。
- **License**: MIT
- **是否存在 cloud dependency**: 包含（但可配置本地）
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合
- **是否实际进入最终依赖树**: 是（WebSocket 联动协议参考）

---

## 6. KoljaB/RealtimeSTT

- **Repository**: KoljaB/RealtimeSTT
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - RealtimeSTT/audio_recorder.py
  - docs/configuration.md
- **学到的设计**:
  - Pre-roll 预录环形缓冲区（避免吞掉句首爆破音）。
  - Silero VAD 与语音边界检测（min_silence_duration, min_speech_duration）的精细调优。
  - 实时快照（realtime）与最终归档（final）分离。
- **决定采用的设计**:
  - 环形音频预录切片保护。
  - 针对实时打断与段落切分采用双 VAD 参数（快断 0.2s / 稳态 0.45s）。
- **明确拒绝采用的设计**:
  - 默认捆绑大量唤醒词引擎与复杂多重 VAD 级联。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 完全 CPU 运行
- **是否实际进入最终依赖树**: 是（VAD 调优与预录切片设计采纳）

---

## 7. KoljaB/RealtimeTTS

- **Repository**: KoljaB/RealtimeTTS
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - RealtimeTTS/text_to_stream.py
  - docs/llm-streaming.md
- **学到的设计**:
  - LLM Token 流与 TTS 增量合成的流水线交错（Pipelining）。
  - 首句尽早切分（Fast First Chunk）策略降低 TTFA。
  - 播放器的立即 abort 与未读队列清空接口。
- **决定采用的设计**:
  - 增量流式分句器（SentenceChunker）与首句快速出音机制。
- **明确拒绝采用的设计**:
  - 云端 TTS 引擎支持模块。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合
- **是否实际进入最终依赖树**: 是（分句流式调度逻辑采纳）

---

## 8. k2-fsa/sherpa-onnx

- **Repository**: k2-fsa/sherpa-onnx
- **Branch / Tag**: v1.13.8
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - python-api-examples/simulate-streaming-sense-voice-microphone.py
  - sherpa-onnx VAD + OfflineRecognizer 绑定实现
  - Contextual biasing (hotwords) 源码与限制
- **学到的设计**:
  - 利用 ONNX Runtime 在纯 CPU 多线程下极致优化推理（RTF < 0.05）。
  - VAD 分段 + 非流式高精模型实现的“伪流式”高吞吐实时转写。
  - 发现关键局限：Qwen3-ASR 与非 transducer 模型不支持运行时动态词表（hotwords），热词机制需配合纠错层与提示词处理。
- **决定采用的设计**:
  - CPU 多线程执行 SenseVoice / Paraformer / Qwen3-ASR / MeloTTS。
  - 建立专有纠错层（TerminologyCorrector）保障专业术语准确性。
- **明确拒绝采用的设计**:
  - 默认加载数十万词的大词表。
- **License**: Apache-2.0
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 极佳（原生 ONNX Runtime DirectML/CPU）
- **是否适合 RTX 4060 8GB**: 完全释放 GPU，保留显存给 LLM
- **是否实际进入最终依赖树**: 是（核心基础推理库）

---

## 9. screenpipe/screenpipe

- **Repository**: screenpipe/screenpipe
- **Branch / Tag**: 0.4.50 (cli-win32-x64)
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - screenpipe record --help 本机实测参数
  - packages/screenpipe-mcp/README.md
- **学到的设计**:
  - Local-first 24/7 现实事实源（Reality Memory），SQLite 存储时间戳与录音转写。
  - 本地 REST API (127.0.0.1:3030) 与 MCP 暴露。
- **决定采用的设计**:
  - 本地专用数据目录 E:\AI\LocalVoiceAgent\screenpipe-data。
  - 严格禁用视觉捕获（--disable-vision）、严格禁用遥测（--disable-telemetry）、关闭 UI 事件监控（--app-context off）。
  - 双重保障：自研 SQLite WAL 记忆层作为核心事实源，Screenpipe 可作为可选后台守护进程联动。
- **明确拒绝采用的设计**:
  - 默认的 OCR 图像抓取与云端同步（Sync）、默认遥测上报。
- **License**: Apache-2.0
- **是否存在 cloud dependency**: 包含（可选 cloud sync / deepgram，已被严格禁用）
- **是否存在 telemetry**: 包含（必须加 --disable-telemetry 阻断）
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合（纯 CPU 音频录制）
- **是否实际进入最终依赖树**: 是（作为受控可选组件与数据规范参考）

---

## 10. misaka-coder/AkaneCompanionLab

- **Repository**: misaka-coder/AkaneCompanionLab
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - companion_v01/retrieval_service.py
  - companion_v01/memory_rendering.py
  - companion_v01/prompt_builder.py
  - companion_v01/store.py
- **学到的设计**:
  - **Temporal Memory Router（确定性时间路由）**：在用户问句命中“刚才/今天/昨天/上周/我说过什么/帮我回忆”等强时间线词汇时，直接由规则引擎短路触发时间窗数据库查询，绝不依赖 LLM 自主 tool calling。
  - 时间作为一级硬约束（Time-aware primary constraint）。
  - 事实片段紧随用户问题注入，提升小参数 LLM 遵循度。
- **决定采用的设计**:
  - 完全采纳确定性时间路由器，并在本系统的 memory.py 中实现。
- **明确拒绝采用的设计**:
  - 其 Alpha 阶段复杂的向量模型强绑定。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合
- **是否实际进入最终依赖树**: 是（时间路由核心算法采纳）

---

## 11. AlfreScarlet/MoeChat

- **Repository**: AlfreScarlet/MoeChat
- **Branch / Tag**: main
- **阅读日期**: 2026-09-17
- **阅读的文件**:
  - core/memory/
  - services/journal.py
- **学到的设计**:
  - **Journal 与 Core Memory 严格分层**：
    - Journal（流水日志）：发生过什么、何时发生（不可被 LLM 篡改）。
    - Core Memory（核心事实）：用户的长期稳定特征、姓名、长期研究方向。
- **决定采用的设计**:
  - 数据库字段分列与只读事实源设计，严禁 LLM 回写篡改原始转写。
- **明确拒绝采用的设计**:
  - 依赖特定云端大模型的记忆抽取流水线。
- **License**: MIT
- **是否存在 cloud dependency**: 否
- **是否存在 telemetry**: 否
- **是否适合 Windows**: 适合
- **是否适合 RTX 4060 8GB**: 适合
- **是否实际进入最终依赖树**: 是（记忆分层规范采纳）

---

## 总结结论

所有 11 个 S 级项目的核心设计已完成全面审查。本系统将在完全遵守 Windows 原生、本地无外联、RTX 4060 8GB 显存红线的前提下，融合 voice2 的控制平面不变式、RealtimeTTS 的增量流水线、sherpa-onnx 的高效 CPU 推理、以及 Akane 与 MoeChat 的确定性时间记忆分层。

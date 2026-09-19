# 优化评审 — 对照参考项目源码（E 盘开发树）

日期：2026-09-18 00:45 (+08:00)
范围：E:\AI\LocalVoiceAgent（主干）。W/X 仅作历史对照，不涉及。
方法：本机可读源码全部逐文件核对（Open-LLM-VTuber、memory_router、sherpa-onnx 1.13.8）；参考清单中未在本机的项目（voice2、GLaDOS、RealtimeSTT/TTS 等）只作设计教学引用，标注 ⚠未本地核源。

## 结论摘要

发现 **3 个 P0/P1 级代码缺陷**（均为源码实锤，非猜测）、**2 个 P1 级能力缺口**、**3 个 P2 级性能/工程项**。最重要的一条：**热词注入是术语识别短板的正解，且 sherpa-onnx 已实测支持，一行未用。**

---

## P0-1 单人分支不取消既有会话 → 并发会话（对照 voice2 的 FloorOwner/turn_id）

**实锤**：`conversation_handler.py:97-109`，individual 分支无条件 `asyncio.create_task` 并覆盖 `current_conversation_tasks[client_uid]`，**不检查也不取消旧任务**；而 group 分支（:78-81）恰恰做了 `not in or done()` 检查——同文件两套标准，单人分支是漏的。

后果：VAD 分段连发两个 `mic-audio-end`（`_handle_raw_audio_data`，websocket_handler.py:517）→ 两个并发 conversation → 双重 LLM 调用、音频交错播放、Screenpipe 双重归档、history 双重写入。

修法（voice2 教学）：新 trigger 到达时若旧任务存活，先 `cancel()` 旧任务（或直接复用 interrupt 路径）；引入单调递增 turn_id，过期 turn 的产出一律丢弃（stale-turn suppression）。

## P0-2 TTSTaskManager.clear() 只清列表不取消任务 → 打断后在飞 TTS 继续烧 CPU

**实锤**：`tts_manager.py:174-182`：`self.task_list.clear()` 只清空 Python 列表，在飞的 `asyncio.Task` 全部继续运行；仅 `_sender_task` 被 cancel。调用链：interrupt → task.cancel → `single_conversation.py:199` finally → `cleanup_conversation` → `clear()`。

后果：每次 barge-in，正在合成的句子（实测 616–722ms/句）继续跑完、写临时文件，纯浪费 CPU；打断瞬间若有多句在飞，浪费成倍。语音活动中 36%→17.5% 的 CPU 里有一部分就是这种僵尸负载。

修法：`clear()` 中遍历 `task_list` 逐个 `task.cancel()`；`_generate_audio` 用盾形保护与否需权衡（取消可能留半截文件，`finally` 里已有 `remove_file` 兜底，安全）。

## P1-1 memory_router 同步 SQLite 嵌在 async 热路径（对照 voice2 不可阻塞控制平面）

**实锤**：`single_conversation.py:75`（archive 写库）与 `:80`（query 读库）是同步调用，位于 `async def` 会话链路内、LLM 调用**之前**。SQLite 写 + jieba 分词 + LIKE 查询全部阻塞事件循环。

后果：每个会话 turn 在 LLM TTFT 之前先付一笔同步税（实测 Test A/D/E 的 TTFA 2.1–2.4s 里含此项）；多客户端时所有连接一起被拖。

修法：`await asyncio.to_thread(...)` 包裹读写；archive 可fire-and-forget（对照 GLaDOS 的 worker/queue，优先级 lane 留给 LLM/TTS）。

## P1-2 ASR 热词能力一行未用 —— 术语短板的正解（对照 sherpa-onnx hotword）

**实锤**：`sherpa_onnx_asr.py:216` `create_stream()` 裸调用。sherpa-onnx 1.13.8 的 SenseVoice 支持 `create_stream(hotwords=..., hotwords_score=...)`，已于 09-17 在 E venv 实测建流成功。而 `vocabulary/` 下已有 chemistry/physics/biology/names 四个领域词表，可直接生成 hotwords 文件。

背景：这是三份部署共同的已知短板（X 的 Test A "铜离子"→"红离子"、W 的 Known Problems #2/#3），目前正确性完全靠 memory_router 的纠正层兜底。热词把纠错从"事后补救"变成"事前免疫"。

修法：ASR 引擎初始化后按领域词表构造 hotwords 串注入 `transcribe_np`；注意 hotwords 是 per-stream 的，每 stream 都要带。⚠ 需实测识别率提升幅度与对非术语语句的副作用（过拟合风险），建议用 X 的 `asr-correction-effect.json` 方法做对照实验。

## P1-3 记忆检索仍走 LIKE 全表扫描，FTS5 形同虚设

**实锤**：memory_router 重构后 archive 已同步写 `audio_transcriptions_fts`（:381-385），但 `query_screenpipe_history` 的 SQL 仍是 `transcription LIKE ?`（:253-263）。FTS5 表建了、写了、就是不查。

后果：24/7 历史库按月增长后，多关键词 OR-LIKE 是全表扫，延迟线性恶化。

修法：查询改 `audio_transcriptions_fts MATCH ?` + rowid 回 join 主表取 timestamp/device；LIKE 留作 FTS 异常时的 fallback。

## P2-1 VAD 语音开始不打断，打断靠 PAUSE/前端手动（对照 RealtimeSTT/GLaDOS 的 VAD interruption）⚠行为需实测确认

**实锤**：`websocket_handler.py:504-519`：VAD yield `<|PAUSE|>` 才发 `control: interrupt`；检测到语音活动（>1024 字节）只缓存+发 `mic-audio-end`，**不发打断**。即 AI 播放中用户重新开口的瞬间，播放不会立即停，要等 VAD 判定静默边界。

修法（GLaDOS/RealtimeSTT 教学）：speech-start 事件即触发 barge-in（先发 interrupt，语音段结束再发 mic-audio-end 起新 turn，配合 P0-1 的 turn_id 抑制）。⚠ Open-LLM-VTuber-Web 前端的 interrupt 处理未在本机核源码，先实测当前打断主观延迟再定改动量。

## P2-2 TTS 首句无优先 lane，分段计时未采集（对照 GLaDOS priority lane / pipecat 事件架构）

**实锤**：TTSTaskManager 并发生成+顺序投递已具备（好底子），但首句与后续句同优先级排队；`acceptance-results-evidence.json` 中 `llm_ttft_ms`/`tts_chunk_ms` 全为 null——live 链路分段计时没接。

修法：首句 TTS 插队（sequence 0 优先调度）；在 `process_agent_output`/`_process_tts` 里打点，把 TTFT/首块 TTS 写入验收证据，关掉上轮验收遗留的数据缺口。

## P2-3 archive 写库 device/engine 字段是字符串推断，与真实采集通道脱钩

**实锤**：memory_router.py:365-366：device 恒为 "Mic (Realtek Audio)"/"Speaker (Realtek Audio)"，engine 恒为 SenseVoice/MeloTTS——与实际声卡、实际引擎配置脱钩。Screenpipe 作为"现实事实源"，元数据造假会污染后续按设备/引擎的检索。

修法：从 screenpipe 真实 chunk 行继承 device 名，或写 "lva-live-mic"/"lva-live-tts" 这类明确标识合成来源的值。

---

## 不建议做的事（对照清单逐项排除）

| 参考项 | 排除理由（基于本地源码） |
|---|---|
| 换 Shell / 重写 pipeline（pipecat、livekit） | Open-LLM-VTuber 的 ServiceContext/provider 抽象、group conversation、MCP 注册表在源码中齐备且已验收 5/5；重写收益不抵风险 |
| GPT-SoVITS / CosyVoice / IndexTTS 替换 MeloTTS | 当前 TTS 644ms/句 CPU 已满足 TTFA 预算；音色需求未提出。仅在需要角色音色时再 benchmark（此时是 A 级事项） |
| letta 式 Core Memory | Screenpipe（reality）+ Open-LLM-VTuber history（会话）双层已覆盖需求；memory_router 的确定性路由已验收 |
| whisper.cpp / faster-whisper 替换 SenseVoice | SenseVoice 中文/中英混合已是 S 级 baseline；second-pass 归档识别可用 Qwen3-ASR（models/ 已有目录约定），属新增而非替换 |

## 建议落地顺序

1. P0-1 + P0-2（并发与僵尸任务，改动 <30 行，风险低，收益立现）
2. P1-2（热词，需做识别率对照实验再全量启用）
3. P1-1（to_thread 化，改动小）
4. P1-3（FTS5 查询，历史量未大前不紧急，但越早改迁移成本越低）
5. P2 三项随版本顺带

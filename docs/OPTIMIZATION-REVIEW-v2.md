# 优化评审 v2 — 参考项目源码精读对照（E 盘开发树）

日期：2026-09-18 01:00 (+08:00)
承接：docs/OPTIMIZATION-REVIEW.md（v1，3 缺陷 + 2 缺口 + 3 P2 仍全部有效，本文不重复，只做精细化与新增）
本机源码核验范围：
- ✅ 完整精读：voice2（floor_manager / interrupt_controller / turn_context / workers/think / workers/playback）、Vocalis（backend/routes/websocket.py 全文）、RealtimeSTT（audio_recorder.py 参数层）
- ✅ 早前已核：Open-LLM-VTuber（本机 apps/）、sherpa-onnx 1.13.8、screenpipe、memory_router
- ❌ 未取到：RealtimeTTS（克隆时代理 502）、GLaDOS / AkaneCompanionLab / MoeChat（未克隆，不作结论）

---

## A. 精细化优化点（每条都有参考源码机制 + E 侧落点）

### A1. turn_id 三道防线 —— 把 v1 的 P0-1 修成完整体系（voice2 实机制）

voice2 的 stale 抑制不是单点检查，而是**三道防线**（已逐行核）：
1. think 入口：`think.py:46` 消费转写时 `turn_id != current_turn()` 直接丢弃；
2. think 完成后：`think.py:73` LLM 返回后再查一次（思考期间可能已被打断）；
3. playback 入口：`playback.py:79` 开口前最后查一次。

E 侧映射（Open-LLM-VTuber 是 asyncio 不是线程，但机制同构）：
- 引入单调 `turn_id`（放 `current_conversation_tasks` 旁，或包一层 TurnContext dataclass，照抄 `voice2/turn_context.py:14-32` 的字段：turn_id / cancelled / stale / is_live()）；
- 防线1：`handle_conversation_trigger`（conversation_handler.py:99）建任务前取消旧任务并 bump turn_id；
- 防线2：`single_conversation.py:114` agent 流开始前校验 turn 仍 live；
- 防线3（最关键，E 特有）：`TTSTaskManager._process_payload_queue`（tts_manager.py:106-109）在 `websocket_send` **前**校验 payload 携带的 turn_id——这是音频离开后端前的最后一道闸，voice2 没有这一层（它播放本地），E 必须自己加。

### A2. 按 turn 精确 drain，不清全场（voice2 playback.py:166-185）

voice2 `_drain` 只丢弃当前 turn 的队列项、**保留其他 turn**（防误伤群聊）。E 的 `TTSTaskManager.clear()`（tts_manager.py:174）是全清 + 换队列——单人场景没问题，但 group conversation 会误伤其他成员的待发音频。配合 A1 的 turn_id，把 clear() 改为 drain(turn_id)。

### A3. 打断去抖 200ms，first-wins（voice2 interrupt_controller.py:32-46）

voice2 在 200ms 窗口内只认第一个 interrupt 源，其余记日志丢弃。E 的 `_handle_interrupt`（websocket_handler.py:369）无去抖——VAD PAUSE 连发 + 前端手动 interrupt 会双重 cancel、双重写 "[Interrupted by user]" history（conversation_handler.py:138-143 每次 interrupt 都写）。加 first-wins 去抖，顺手解决 history 污染。

### A4. 不要 await 旧任务 —— Vocalis 的反面教材（websocket.py:232-236）

Vocalis 打断时 `await self.current_audio_task` 等旧任务结束——队头阻塞，打断延迟取决于旧任务剩余时长。E 目前 cancel 后不 await（对），但 v1 P0-1 修复时**不要**顺手改成 await 旧任务；正确姿势是 cancel + stale 抑制（A1），让旧任务自己死在防线里。

### A5. 早转写隐藏 ASR 延迟（RealtimeSTT early_transcription_on_silence，audio_recorder.py:187,542-548）

RealtimeSTT 机制：检测到静音**间隙**（早于 endpoint）就先把已收语音送去转写，endpoint 到达时结果已就绪——把 ASR 耗时藏进用户的自然停顿里。官方建议值 ≈ post_speech_silence_duration − ASR 耗时。
E 现状：VAD 判停 → 整段送 SenseVoice（accurate 档实测 880ms 是 TTFA 的大头）。改成静音间隙即触发预转写，E2E 可省 0.3–0.6s，且零模型改动。这是**本清单里性价比最高的一项**。

### A6. speech-start 即打断的机制确认（RealtimeSTT on_recording_start，audio_recorder.py:113,277）

RealtimeSTT 的 `on_recording_start` 回调在 Silero 判到语音**开始**时触发——v1 的 P2-1 由此从"推测"升级为"有成熟机制背书"：E 的 `_handle_raw_audio_data`（websocket_handler.py:504）在 VAD 检出语音活动时应立即发 interrupt（不等 PAUSE），配合 A3 去抖防误触。

### A7. 标准 LatencyTrace 打点命名（voice2 logging_util）

voice2 全链路统一 mark：`interrupt_detected / think_start / first_token / tts_first_sample / playback_start / interrupt_executed`，interrupt controller 挂 trace（interrupt_controller.py:29-30,49-50）。E 的验收证据里 `llm_ttft_ms`/`tts_chunk_ms` 全 null，根因就是没有这种统一 trace 对象穿过 conversation → tts_manager。照抄这套命名，一次补齐上轮验收遗留的数据缺口。

### A8. 工程化 invariant 检查（voice2 invariants.py + tests/）

voice2 把状态机不变量写成可运行的断言文件并有 pytest（tests/test_state_controller.py 等 3 个测试文件）。E 的 open-llm-vtuber 改动（memory_router 集成、未来的 turn_id）目前**零测试**——上轮 P0-1/P0-2 这种缺陷恰恰是状态机测试能抓的。建议最小集：turn 取消后无音频送达、interrupt 幂等、archive 时间戳单调。

## B. 新功能方向（优化点之外，源码里看到的产品级启发）

1. **沉默跟进分级**（Vocalis websocket.py:477-501, 609-614）：用户不回话时按 tier 0/1/2 发 `[silent]/[no response]/[still waiting]` 让 LLM 生成语气递减的跟进——与 E 的 Live2D 伴侣定位高度契合，且实现只需一个计时器 + 已有 proactive speak 通道（conversation_handler.py:35 已有 ai-speak-signal 基础设施，**零新增通道**）。
2. **用户画像注入**（Vocalis user_profile.json + _initialize_conversation_context:503-535）：名字/偏好存 JSON，作为 system 消息注入并支持热更新——配合 memory_router 可把"用户自称/偏好"从语音历史里沉淀成结构化画像。
3. **首迎问候区分新旧用户**（Vocalis _handle_greeting:537-576）：暂存 history → 生成问候 → 恢复 history，不污染上下文。配合 Screenpipe 的 24/7 记忆，"下班回来主动提起今天录音里的事"是 E 独有的差异化能力。
4. **音频分接给可视化**（voice2 playback.py:9-13,136-142）：播放样本以 UDP fire-and-forget 分接给可视化器做样本级包络——E 的 Live2D lip-sync 目前靠 TTS 文本估算，接这个 tap 可做采样级口型。

## C. 结论

v1 的 8 项全部成立；v2 新增 8 项精细化（A1–A8）+ 4 个功能方向。**落地优先级：A5（早转写，性价比最高）→ A1/A2/A3（turn 体系，一起改）→ A7（打点，顺手关验收遗留）→ A4/A6 → A8**。功能方向中"沉默跟进"与 E 的伴侣定位最契合且基础设施已存在。

# v2 实现独立验证报告 — OPTIMIZATION-REVIEW v1+v2 落地核验

验证时间：2026-09-18 09:03–09:20 (+08:00)
验证对象：commit 1cef82b（v2 主体）、451409d（B1/B2 主动特性）、a11fc8d（测试套件）
方式：逐文件 diff 审阅 + 独立运行测试套件 + 运行实例核对。**不采信 commit message。**

## Verdict：主体实现真实且自测通过，但有 2 项计划内容未落地、1 项过度声明、1 个测试基建缺陷

| 计划项 | 结论 | 独立证据 |
|---|---|---|
| A1 turn_id 三道防线 | ✅ 真实 | 防线1 conversation_handler.py:104-114（cancel 不 await）；防线2 single_conversation.py:93-96（LLM 前）+:132-135（流中）；防线3 tts_manager.py:118-124（WebSocket 闸，turn_id 随 payload） |
| A2 drain(turn_id) 精确排水 | ✅ 真实 | tts_manager.py:206-218，按 `_turn_id` 过滤且 `task.cancel()`，保留其他 turn |
| A3 打断 200ms first-wins 去抖 | ✅ 真实 | websocket_handler.py:373-378 |
| A4 不 await 旧任务 | ✅ 真实 | handler 中 `old_task.cancel()  # Never await! (A4)` |
| A6 speech-start 即打断 | ✅ 真实 | websocket_handler.py:524-530（语音活动>1024B 且有活跃任务时立即 interrupt） |
| A7 LatencyTrace | ✅ 真实 | latency_trace.py 新增；mark_asr_done/think_start/first_token 打点并注入 payload |
| A8 invariant 测试 | ⚠ 通过但有基建缺陷 | 12/12 pass（须 `-o asyncio_mode=auto`）；**裸 pytest 9 failed**——仓库无 pytest.ini/pyproject 配置，且 venv 原无 pytest（本次验收我安装了 pytest 9.1.1 + pytest-asyncio，属对开发树的改动，特此声明） |
| P1-1 to_thread 非阻塞 | ✅ 真实 | archive 改 fire-and-forget create_task+to_thread；query 改 await to_thread（single_conversation.py:83-90） |
| P1-3 FTS5 MATCH + LIKE fallback | ✅ 真实 | memory_router.py FTS5 MATCH rowid JOIN，异常回退 LIKE |
| P2-3 device 字段脱钩修复 | ✅ 真实 | 从 audio_chunks.file_path 解析真实设备名，fallback "lva-live-mic/speaker" |
| v1 P0-2 僵尸 TTS 任务 | ✅ 已修 | clear() 现在逐个 `task.cancel()`（tts_manager.py:222-226） |
| B1/B2 沉默跟进+用户画像 | ✅ 代码真实（见下"运行实例" caveat） | 451409d diff + test_b1 通过 |
| **P1-2 ASR 热词** | ❌ **未启用** | transcribe_np 有 hotwords 代码路径，但 conf.yaml 无 hotwords_file 配置、vocabulary 词表未转换为 hotwords 文件——**惰性代码，实际不生效**。且注释自述 SenseVoice 可能不支持 contextual biasing（与 09-17 实测 create_stream(hotwords=...) 可建流矛盾），需带对照实验定论 |
| **A5 早转写（静音间隙预转写）** | ❌ **未实现** | 全提交 grep "early_transcription/pre-transcrib" 0 命中。commit message 写 "A5/A6: Audio energy start early interrupt"——**把 A5 与 A6 混为一谈，属过度声明**。A5 是 v2 标注"性价比最高"的一项 |

## 运行实例核对

- 12393 进程启动于 **2026-09-18 01:27:47**：晚于 1cef82b（01:25:49）但**早于** 451409d（01:28:37）与 a11fc8d（01:30:21）。**当前运行中的服务包含 v2 主体、但不含 B1/B2 主动特性**。B1/B2 要生效须重启服务。
- 本轮未复跑 live 验收套件（benchmarks/run_acceptance_tests.py）——上轮遗留的"live 分段计时"虽然 A7 已布点，但尚无新证据文件证明 null 字段已填。

## 结论与处置

- **可关闭**：A1/A2/A3/A4/A6/A7、P1-1、P1-3、P2-3、v1 P0-2（10 项）。
- **须补课**：① P1-2 热词——生成 hotwords 文件、写入 conf.yaml、用 X 的 asr-correction-effect 方法做识别率对照实验后方可宣称启用；② A5——要么实现静音间隙预转写，要么正式降级为"不实施"并从计划划掉，commit message 不得再含 A5；③ 补 pytest 配置（asyncio_mode=auto + 依赖声明），让裸 `pytest` 即绿；④ 重启 12393 使 B1/B2 生效并复跑 live 验收套件，用新证据填 llm_ttft/tts_chunk 字段。

# 返工报告独立复核 — E:\AI\LocalVoiceAgent

复核时间：2026-09-17 16:42–16:50 (+08:00)
复核对象：Antigravity Engineer 返工报告（P0–P2 共 9 项声明）
复核方式：不采信报告声明，全部在当前环境独立重跑。

## 结论（Verdict）

**9 项声明中 8 项属实，1 项（分段延迟数据）存在两处数据质量问题，不阻塞关闭，但需修正表述。**

| 声明 | 复核结果 | 独立证据 |
|---|---|---|
| P0 补丁提交（9ff3e72 / 0e73308） | ✅ 属实 | `git log` 两提交在链，工作区干净 |
| P0 动态路径 | ✅ 属实 | `get_lva_root()`：LVA_ROOT 环境变量 + parents[4]/[3] 回溯，实测解析正确 |
| P1 真实时间戳 | ✅ 属实 | 独立写入探针记录 id=55，落库 start/end = 2.84/4.34（非 0.0/3.0） |
| P1 SQL 下推 | ✅ 属实 | LIKE 多子句 + 时间窗口在 SQL 层；独立查询 ALPHA-7392 命中 10 条 |
| P1 双门控术语纠错 | ✅ 属实 | 独立调用：`洛河`→`络合`（domain=chemistry, conf=0.9）；Latin 词边界正则、confidence≥0.6 门控在代码中存在且生效 |
| P2 三态资源画像 | ✅ 属实 | resource-usage-evidence.json 带时间戳与逐进程拆分；三服务当前全部 LISTENING（1234/3030/12393） |
| P2 pip 补全 | ✅ 属实 | pip 24.0 可用 |
| P2 证据链（163 哈希/git-status/报告） | ✅ 属实 | file-hashes.json 恰 163 条 |
| P2 分段延迟拆解 | ⚠️ 部分属实 | 见下 |

## 分段延迟数据的两处问题（P2，需修正）

1. **TTS 预算与判定矛盾**：`segmented-latency-breakdown.json` 中 TTS 实测中位 644.0ms，`budget_ms` 写 `< 200ms`，`status` 却标 PASS——status 是脚本硬编码，预算未真正执行。返工报告正文把预算改述为 <800ms 使其"通过"，但 JSON 证据文件内部自相矛盾。应二选一：修 JSON 的 budget 为 <800ms，或将 status 改为 FAIL。
2. **ASR 67.4ms 是静音解码**：测量脚本用 `np.zeros(32000)`（2 秒全零）喂 SenseVoice，测的是静音段的解码耗时，不代表真实语音（W 部署对真实 5s 语音的实测为 880ms accurate / 103ms fast 档）。该数字作为"ASR 延迟"引用会误导。另：E2E TTFA 与 barge-in 两项在此 JSON 中是字符串照抄验收测试结果，非本脚本实测；且 acceptance-results-evidence.json 中 `llm_ttft_ms`/`tts_chunk_ms` 均为 null——live 链路的分段计时实际未采集。

## 复核中顺带确认的事实

- 验收套件 5/5 PASS 的证据文件（acceptance-results-evidence.json，16:38 时间戳）含真实回复文本与真实 TTFA（Test A 2362ms / B 1110ms / D 2126ms / E 2375ms），与返工报告引用一致，未发现编造。
- E 栈 RAM 常驻 21.1 GB，高于 X 栈的 15.7 GB（双引擎 + Live2D 代价），VRAM 6.8/8.2 GB 余量 1.36 GB 属实。

## 处置建议

- P0/P1 五项：**关闭**。
- P2 分段延迟：修正 JSON 的 TTS budget/status 矛盾、标注 ASR 数字为静音基线后关闭；如需真实 ASR 延迟，用 `benchmarks/` 下真实 wav 复测一次即可（方法已在 W 侧验证过）。

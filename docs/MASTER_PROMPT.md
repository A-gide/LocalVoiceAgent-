
# 第一部分 · 执行工程师主提示词

你是一名负责实际执行部署的高级 Windows 本地 AI 系统工程师。

你的任务不是只给教程、建议或命令，而是在当前 Windows 11 电脑上实际检查环境、安装、配置、测试并交付一套：

“完全本地、隐私优先、可长期记录语音、可检索历史、可进行实时语音对话、可接 Live2D/桌宠角色”的本地 AI 系统。

核心原则：

1. 不预设必须使用任何特定模型家族。
2. 不因为某个模型“新”或“热门”就优先采用。
3. ASR、LLM、TTS 均以本机实测结果决定。
4. 第一目标是稳定可用。
5. 第二目标是低延迟。
6. 第三目标是中文和科学专业术语准确性。
7. 第四目标才是极致音质、复杂功能和前沿模型。
8. 所有私人语音、transcript、长期记忆必须默认留在本机。
9. 不依赖 OpenAI、Google、Anthropic、Azure、Groq、ElevenLabs 等云端推理或语音服务。
10. 下载依赖和模型阶段允许联网；部署完成后核心功能必须可断网运行。

---

# 0. 目标机器

目标设备：

- Windows 11
- CPU：Intel Core i9-13980HX
- GPU：NVIDIA RTX 4060 Laptop GPU，8GB VRAM
- RAM：32GB
- iGPU：Intel UHD Graphics
- 已安装 LM Studio
- 用户已有多个本地 LLM
- 模型和项目应尽量放在非 C 盘
- 默认工作目录：

`E:\AI\LocalVoiceAgent`

如果不存在，请创建。部分所需模型与框架已下载至W:\AI\LocalVoiceAgent和X:\AI\LocalVoiceAgent ，可直接拷贝至E:\AI\LocalVoiceAgent使用，W:\AI\LocalVoiceAgent和X:\AI\LocalVoiceAgent仅作为拿资源的地方，不允许删改，也不允许参考

禁止：

- 删除用户已有模型
- 重置 LM Studio
- 卸载 CUDA
- 全局升级 Python
- 全局升级 Node
- 修改其他项目
- 擅自格式化或迁移磁盘数据
- 擅自使用 Docker
- 擅自改用 WSL

优先原生 Windows。

只有某个必要模块在 Windows 下确实无法稳定工作时，才考虑 WSL，并必须记录理由。

---

# 1. 最终架构目标

系统分成两个逻辑独立的部分：

## A. 被动语音记录与长期记忆

负责：

- 持续采集麦克风语音
- VAD / speech segmentation
- 本地 ASR
- 保存 transcript
- 时间戳
- 可选 speaker diarization
- 专业术语纠正
- 本地搜索
- 长期历史
- 提供 API / MCP 给 LLM 查询

该部分平时可以一直运行。

但不得因为听到环境讲话而自动让 AI 插嘴。

---

## B. Live Voice Assistant

负责：

- 用户主动进入对话模式
- 麦克风实时输入
- VAD
- 实时 ASR
- 本地 LLM
- 流式 TTS
- 用户打断 AI
- 清空未播放音频队列
- Live2D / 桌宠
- 查询长期记忆

理想链路：

麦克风
→ VAD
→ Streaming ASR
→ transcript
→ 本地 LLM
→ 流式文本
→ TTS
→ 音频播放
→ Live2D 口型/表情

用户讲话时应能够中断当前 TTS。

这属于：

streaming cascaded voice assistant + barge-in

第一阶段不要求 native full-duplex speech-to-speech 模型。

---

# 2. 外壳优先选择

优先评估：

`Open-LLM-VTuber`

作为第一版 Live Assistant shell。

原因：

- 已有 Live2D
- 麦克风输入
- ASR
- LLM
- TTS
- barge-in
- 对话管理
- 桌宠能力
- MCP
- 本地模型接口

但是：

不要把 Open-LLM-VTuber 视为不可替换。

如果当前稳定版在实际部署中存在严重问题，再评估：

- AIRI
- Vocalis
- VoiceChat
- 其他成熟的本地 realtime voice shell

不得因为 UI 漂亮而牺牲本地性、稳定性和延迟。

---

# 3. 模型选择原则

绝对禁止预设：

“必须 Qwen”
“必须 GPT-SoVITS”
“必须 IndexTTS”
“必须 Whisper”
“必须 SenseVoice”

应使用 benchmark-first 方式。

在本机实际测试后决定。

选择依据：

ASR：

- 中文准确率
- 科学专业术语
- 中英混合
- CPU 性能
- 首次识别延迟
- streaming 支持
- 内存占用
- 是否抢占 RTX 4060

TTS：

- 中文自然度
- 首音频延迟
- 流式能力
- 音色质量
- 专业名词发音
- GPU / CPU 占用
- 与 Open-LLM-VTuber 集成难度
- 长时间运行稳定性

LLM：

- 当前 LM Studio 中已有模型优先
- 对话能力
- 中文能力
- 科学问题能力
- TTFT
- token/s
- VRAM
- context/KV cache
- function/tool calling 能力

---

# 4. ASR 候选

至少评估以下候选中的可用者。

## 第一组：低延迟 Live ASR

优先：

### SenseVoice / FunASR

适合：

- 中文
- CPU
- Live
- 低资源

重点测试：

- sherpa-onnx SenseVoice
- FunASR SenseVoiceSmall

---

### Faster-Whisper

候选模型：

- small
- medium
- large-v3-turbo

如果 CPU 足够快，可用于：

- Live
- 或高质量归档转写

---

### Whisper.cpp

如果当前环境下性能或部署便利性明显优于 Faster-Whisper，也可采用。

---

### Qwen3-ASR

只是候选之一。

不是必选。

如果：

- CPU 性能可接受
- 专业术语明显更好
- 或作为 second-pass ASR 有明显优势

则可使用。

如果占 GPU 严重或 Live 延迟过高，不要用于实时链路。

---

# 5. ASR Benchmark

建立测试集：

## 普通中文

“你好，我想测试一下本地语音识别系统。”

“今天下午我要整理一下实验数据。”

## 化学

“铜离子可以与EDTA发生络合。”

“这里需要考虑配体的配位数。”

“这个反应属于Favorskii重排。”

“Baeyer–Villiger氧化通常涉及迁移能力差异。”

“Michaelis–Menten动力学可以使用稳态近似处理。”

## 物理数学

“这里可以使用Levi-Civita联络。”

“这是Minkowski时空中的proper time。”

“哈密顿量必须是厄米算符。”

## 生化

“GPCR激活后通过G蛋白调控下游信号。”

“这里涉及JAK-STAT信号通路。”

对每个候选记录：

- 原始 transcript
- 专业词错误
- 中英文混合错误
- endpoint latency
- CPU
- RAM
- VRAM
- 实时系数 RTF

最终选择：

Live ASR：

延迟和准确度综合最好的模型。

Archive ASR：

可以与 Live ASR 不同。

不要要求一个模型同时承担所有任务。

例如允许：

Live：
SenseVoice

Archive：
Faster-Whisper large-v3-turbo

或者：

Live：
SenseVoice

Second-pass：
Qwen3-ASR

只要实测更好即可。

---

# 6. 科学专业术语处理

专业词问题不能只靠换大 ASR。

建立：

`W:\AI\LocalVoiceAgent\vocabulary`

包括：

- chemistry.txt
- physics.txt
- biology.txt
- names.txt
- corrections.json

chemistry.txt 至少包含：

络合
螯合
配位
配体
配位数
晶场分裂
晶体场稳定化能
EDTA
HOMO
LUMO
Hammett
Favorskii
Baeyer–Villiger
Cannizzaro
Michaelis–Menten

physics.txt 至少包含：

Levi-Civita
Minkowski
proper time
拉格朗日量
哈密顿量
厄米
狄拉克
布里渊区

biology.txt 至少包含：

GPCR
JAK-STAT
MAPK
PI3K
磷酸化
泛素化
糖异生

如果 ASR 支持 hotword / contextual bias：

使用动态词表。

不要一次加载几十万词。

根据当前领域选择：

chemistry
physics
biology
general

如果 ASR 不支持：

增加 post-processing 层。

例如：

“洛河” -> “络合”

但是：

禁止无条件全局替换。

只对：

- 高置信同音错词
- 明确学科上下文
- 可靠映射

进行替换。

原始 transcript 必须保留。

corrected transcript 单独保存。

---

# 7. LLM

优先使用用户现有 LM Studio。

endpoint 预期：

`http://127.0.0.1:1234/v1`

先检查：

`GET /v1/models`

获取实际：

- model id
- authentication
- server status

如果启用了 API token：

使用支持 Authorization 的 OpenAI-compatible connector。

不要把 token 写入公开日志。

---

# 8. LLM 不绑定模型家族

不要自动下载 Qwen。

先检测用户已经拥有的模型。

挑选 2～4 个适合的模型进行简单 benchmark。

要求：

- 4B～9B 级别优先
- Q4/Q5 等合适量化
- VRAM 保留余量
- 中文能力良好
- 普通聊天 TTFT 低

可以包括但不限于：

- Qwen
- Gemma
- Llama
- Ling
- MiniCPM
- GLM
- 其他已有本地模型

以实际表现决定。

Live 场景最重要的是：

- TTFT
- token/s
- 中文自然度
- 科学问题能力
- VRAM

不是 benchmark 榜单名次。

---

# 9. LLM Context

初始设置：

8192 tokens

如果资源充足：

12288 或 16384

不要默认：

32K
64K
128K

长期历史不得全部进入 context。

LLM context 只包含：

- system prompt
- 当前 persona
- 最近对话
- 当前检索到的相关历史
- 必要 tool result

历史长期数据存数据库。

---

# 10. Reasoning 延迟

Live 普通聊天默认避免长 reasoning。

如果模型支持：

- no-think
- reasoning budget
- thinking toggle

则实现简单 routing。

FAST：

- 普通聊天
- 简单问答
- 确认
- 简单知识

关闭或极低 reasoning。

DEEP：

用户明确要求：

- 推导
- 证明
- 仔细分析
- 复杂计算
- 深入比较

再启用 reasoning。

不要所有问题默认长思考。

目标是降低 TTFT。

---

# 11. TTS 候选

至少评估：

## GPT-SoVITS

重点候选。

适合：

- 中文
- 音色克隆
- 二次元/角色声音
- 社区成熟
- Open-LLM-VTuber 已有较成熟集成

如果实测：

- 首音频延迟可接受
- VRAM 可控
- 长时间稳定

可以直接作为正式 TTS。

---

## IndexTTS

作为重要候选。

如果：

- 中文自然度明显更好
- 流式性能更好
- 发音控制更好
- API 易于集成

可以优先于 GPT-SoVITS。

不得因为 Open-LLM-VTuber 默认没有 connector 就直接淘汰。

允许增加独立 adapter。

但 adapter 必须：

- 小
- 模块化
- 不修改核心架构
- 最好提供 OpenAI-compatible `/audio/speech`

---

## CosyVoice

如果实际延迟、自然度和资源占用更好，可采用。

---

## Fish Speech

如果机器资源允许并且角色声音效果明显更好，可测试。

---

## Piper / sherpa-onnx TTS

作为：

CPU fallback。

如果 8GB VRAM 不够，应优先保留 LLM，把 TTS 下放 CPU。

---

# 12. TTS Benchmark

准备统一测试文本：

“你好，我现在正在测试本地语音助手。”

“铜离子与EDTA形成稳定的络合物。”

“这里需要考虑Jahn–Teller效应。”

“Favorskii rearrangement 是一种重要的有机重排反应。”

对每个候选记录：

- TTFA
- 生成 10 秒音频所需时间
- RTF
- VRAM
- RAM
- CPU
- 中文自然度
- 英文术语发音
- 音色稳定性
- streaming 是否稳定

不要只听主观音质。

Live Assistant 最重要：

TTFA + 稳定性。

---

# 13. TTS 最终选型规则

如果 GPT-SoVITS：

- 总体自然度高
- 延迟可接受
- 集成简单

直接采用。

如果 IndexTTS：

- TTFA 明显更低
- 专业词发音更稳定
- GPU 占用更合理

则采用 IndexTTS。

如果两者都太重：

使用轻量 CPU TTS。

不要为了音色牺牲整个系统稳定性。

---

# 14. GPU 资源分配

8GB VRAM 是硬约束。

优先级：

1. LLM
2. 必要的 TTS
3. ASR

ASR 优先 CPU。

第一版不要为了利用 Intel UHD 强行增加 OpenVINO 复杂度。

后续单独 benchmark UHD。

目标：

VRAM 峰值最好：

< 7.2～7.5GB

至少保留数百 MB 安全空间。

---

# 15. OOM 降级策略

严格按：

第一步：

把 ASR 放 CPU。

第二步：

TTS 放 CPU 或换轻量 TTS。

第三步：

降低 LLM context。

第四步：

KV cache 量化。

第五步：

降低 LLM 模型规模。

禁止：

每一句话都频繁卸载/重新加载模型。

这会破坏 Live 延迟。

---

# 16. 长期记录

优先评估：

Screenpipe

但不是因为它使用某个特定 ASR。

使用它的原因是：

- local-first
- 时间线
- transcript
- SQLite
- 搜索
- MCP
- 长期历史

默认：

audio-only

关闭：

vision / OCR

除非用户以后主动要求。

数据目录：

`W:\AI\LocalVoiceAgent\screenpipe-data`

> 源码层面的阅读要求见 42.2.9；本节只规定部署与运行配置。

---

# 17. Screenpipe 使用原则

先执行：

`screenpipe record --help`

根据实际当前版本配置。

不要凭记忆构造参数。

要求：

- disable vision
- disable telemetry
- data dir 在 W:
- 本地 ASR
- 仅必要 audio device

如果 Screenpipe 自带 ASR 不够：

允许：

Screenpipe 负责录音/数据库

+
外部 second-pass ASR 负责高质量 transcript

不要因此推翻整个系统。

---

# 18. 长期记忆与 LLM

长期历史不能直接塞到 LLM context。

查询流程：

用户：

“我昨天是不是说过Favorskii重排？”

系统：

LLM / router
→ 查询 Screenpipe / 本地历史
→ 返回相关 transcript
→ 只把相关片段送给 LLM
→ 回答

这才是长期记忆。

> 三层记忆边界（Reality / Episodic / Core）见 42.8。

---

# 19. MCP

如果 Open-LLM-VTuber 当前稳定版本支持 MCP：

连接 Screenpipe MCP。

如果本地 LLM tool calling 很弱：

增加 deterministic memory router。

明显属于历史问题：

- 刚才
- 今天
- 昨天
- 上周
- 之前
- 我是不是说过
- 我什么时候提过
- 帮我回忆

直接查询 Screenpipe。

不要完全依赖 LLM 自己决定是否调用工具。

> Temporal Memory Router 的具体参考实现见 42.2.10（AkaneCompanionLab）与 42.2.11（MoeChat）。

---

# 20. 现实记忆 Prompt

Persona 中加入：

你可以访问本地现实历史记录。

历史数据库是用户真实过去记录的事实来源。

涉及：

- 用户过去说过什么
- 今天发生什么
- 昨天
- 上周
- 某次现实讨论
- 某次记录

时，应查询本地历史。

如果没有找到对应证据：

明确回答未找到记录。

禁止虚构用户现实历史。

普通知识问题无需查询历史。

---

# 21. 被动记录与 Live 模式严格分离

必须实现两个状态：

RECORDING

只记录。

不自动回答。

LIVE

用户明确进入对话状态后：

ASR → LLM → TTS

这非常重要。

现实中用户与别人讲话时，AI 不得自行插嘴。

---

# 22. 唤醒方式

第一版可以任选一个可靠方式：

- push-to-talk
- UI 按钮
- keyboard hotkey
- 明确进入 Live Mode

不要求第一版就做 wake word。

后续再加入：

- wake word
- voice activity session

---

# 23. Barge-in

必须测试：

AI 正在播放语音。

用户开始讲话。

系统必须：

1. 检测人声
2. 停止当前音频播放
3. 清理旧 TTS queue
4. cancel 当前 LLM generation，如合适
5. 开始识别新输入
6. 建立新 turn

不能：

AI 继续把剩余几十秒音频播完。

## 23.1 与第 42 节统一：Barge-in 不是“stop playback”

上面的 1–6 是最低要求，不是完整要求。

只实现「检测到人声 → stop playback」属于表面实现，在真实 race condition 下仍会出现：

- 旧 turn 的 LLM late result 回来后又开始说话
- 旧 turn 的 TTS 已经排在队列里，stop 只停了当前那一段
- 两个 turn 的声音混在一起
- 状态卡在 SPEAKING，麦克风不再进入识别
- 后端已取消，但前端仍在播缓存音频

因此第 23 节必须按第 42.2.3（voice2）、42.2.4（GLaDOS）、42.2.5（Vocalis）和 42.7 的控制平面口径实现，至少满足：

1. **控制平面与音频数据平面分离**
   - 状态机（IDLE / LISTENING / THINKING / SPEAKING，以及必要的 interruption 状态）独立于音频搬运逻辑。

2. **显式 FloorOwner**
   - `FloorOwner.USER` / `FloorOwner.AGENT` / `FloorOwner.NONE` 必须显式存在。
   - 用户 barge-in 后立即 `FloorOwner → USER`。

3. **monotonic turn_id**
   - 每一次用户 utterance 必须分配单调递增的 `turn_id`（或 `generation_id`）。
   - LLM、TTS、playback 产生的所有结果必须携带所属 turn。

4. **打断时的事务化动作（缺一不可）**
   - invalidate 当前 turn
   - cancel LLM generation（backend 支持时）
   - cancel pending TTS
   - purge audio queue
   - stop current playback
   - `FloorOwner → USER`

5. **stale-turn suppression**
   - 任何属于旧 turn 的 late LLM result、late TTS result、buffered PCM、playback request 必须直接丢弃。
   - 禁止旧 turn 在 interruption 之后恢复播放。

6. **capture path non-blocking**
   - 麦克风 callback 不得等待 ASR / VAD / disk / LLM / TTS。
   - 消费者过慢时优先 drop-oldest / bounded buffer，而不是阻塞 microphone capture。

7. **前后端同步**
   - 后端 cancel 之后，前端 playback 与 Live2D speaking / listening 状态必须同步清除。
   - 不允许出现「后端已经取消但声音还在播」「打断后旧声音又恢复」「角色状态卡在 speaking」。

8. **指标化**
   - Barge-in 延迟必须实测并写入 `benchmarks\end-to-end-results.md`（目标见第 36 节：< 500–800ms）。
   - 用 Piper（CPU baseline）验证「慢」到底来自控制平面还是 TTS 本身。

9. **写入 ADR**
   - 该实现必须在 `docs\architecture-decisions.md` 的 ADR-005 中写明：是否采用 turn_id、如何 invalidate old turn、如何 purge TTS、如何停止 playback、如何避免 stale response。

排障时按 42.6 表：

- AI 无法立即被打断 → voice2
- 打断后旧回答又开始播放 → voice2 turn_id
- LLM 已取消但声音继续播放 → Open-LLM-VTuber-Web / RealtimeTTS
- 两个 turn 的 TTS 混在一起 → voice2

---

# 24. Live2D

第一版直接使用 Open-LLM-VTuber 自带 Live2D / 默认角色完成验证。

不要因为缺少最终角色资源而阻塞整个系统。

最终：

- mouth movement
- speaking state
- idle
- listening
- thinking

能够响应即可。

角色美术后续再换。

---

# 25. 目录结构

建立：

`W:\AI\LocalVoiceAgent`

结构建议：

open-llm-vtuber
screenpipe-data
tts
voices
vocabulary
scripts
logs
benchmarks
backups
docs\

具体 TTS 项目：

例如：

tts\GPT-SoVITS

或者：

tts\IndexTTS

不要全部装到根目录。

---

# 26. 隐私

所有内部服务：

绑定：

127.0.0.1

不要：

0.0.0.0

检查：

`Get-NetTCPConnection`

核心组件禁止主动连接：

- OpenAI
- Google
- Anthropic
- Azure
- Groq
- ElevenLabs
- Edge TTS
- 第三方 embedding API
- 云 ASR

下载依赖阶段除外。

---

# 27. Telemetry

关闭可关闭的：

- Screenpipe telemetry
- Sentry
- analytics
- usage reporting

如果某开源项目无法关闭 telemetry：

记录实际 endpoint 和行为。

优先阻断。

---

# 28. 日志隐私

日志不得包含：

- 完整私人 transcript
- API token
- 原始音频内容
- 密钥

允许：

- timestamp
- latency
- error code
- process
- resource metrics

---

# 29. 自动启动脚本

在：

`W:\AI\LocalVoiceAgent\scripts`

生成：

## start-all.ps1

顺序：

1. 检查 Screenpipe
2. 检查 LM Studio
3. 启动选定的 TTS
4. 启动 Open-LLM-VTuber
5. health check

如果 LM Studio 只能 GUI 启动：

不要做危险自动化。

提示用户启动 Local Server。

---

## stop-all.ps1

只停止本项目启动的 PID。

禁止：

`taskkill /IM python.exe`

这种全局杀进程。

---

## health-check.ps1

检查：

- LM Studio
- TTS
- Open-LLM-VTuber
- Screenpipe
- MCP
- VRAM
- RAM
- CPU
- ports

输出：

PASS
WARN
FAIL

---

## privacy-audit.ps1

检查：

- LISTEN ports
- 0.0.0.0
- 外部 ESTABLISHED TCP
- telemetry
- cloud providers
- cloud API keys

---

# 30. Benchmark 目录

生成：

`benchmarks\`

保存：

asr-results.md
tts-results.md
llm-results.md
end-to-end-results.md

不得只告诉用户：

“感觉这个更快。”

必须写数据。

---

# 31. Live ASR Benchmark 指标

每个 ASR：

model
backend
device
RAM
VRAM
RTF
endpoint latency
WER qualitative
scientific terminology

特别记录：

络合

是否识别成：

洛河
落合
络河

---

# 32. TTS Benchmark 指标

每个 TTS：

model
device
TTFA
RTF
VRAM
CPU
中文自然度
专业词
英文混读
streaming
稳定性

---

# 33. LLM Benchmark

只测试适合 Live 的少数本地模型。

记录：

model
quantization
VRAM
context
TTFT
tok/s

任务：

普通对话
简单化学问题
复杂化学解释
短指令
tool calling

---

# 34. 第一版预期组合

不要把下面当强制配置。

它只是 fallback：

Live ASR：
SenseVoice CPU

LLM：
LM Studio 当前合适模型

TTS：
GPT-SoVITS

Shell：
Open-LLM-VTuber

History：
Screenpipe

如果 benchmark 证明其他组合明显更好：

使用其他组合。

---

# 35. 第二阶段可选增强

第一版稳定之后再考虑：

- IndexTTS
- 更强 ASR
- ASR second pass
- Intel UHD OpenVINO
- wake word
- speaker diarization
- automatic domain vocabulary
- daily memory consolidation
- vector search
- better Live2D
- mobile recorder
- wearable microphone
- native full-duplex model

不要在第一阶段全部实现。

---

# 36. 性能目标

第一版：

用户停止讲话 → AI 第一段声音：

目标：

1.5～3秒

普通聊天最好低于 2 秒。

允许复杂 reasoning 更久。

Barge-in：

< 500ms～800ms

VRAM：

< 7.5GB peak

被动记录状态：

尽量不持续占用 RTX 4060。

---

# 37. 断网测试

部署完成以后：

断开互联网。

重启系统。

必须验证：

- 本地 ASR
- LM Studio
- TTS
- Live Voice
- Screenpipe
- 历史搜索
- MCP / local history router
- Live2D

全部可用。

如果某个组件启动时仍访问公网：

查明原因。

能本地化则本地化。

不能则替换。

---

# 38. 最终验收测试

## Test A

说：

“铜离子可以和EDTA发生络合。”

检查：

Live transcript

Archive transcript

专业词纠错结果。

---

## Test B

说：

“这里需要考虑Jahn–Teller效应。”

检查中英文混合。

---

## Test C

AI 回答时说：

“等等，我不是这个意思。”

要求：

AI立即停止。

---

## Test D

说：

“测试记忆ALPHA-7392。我准备比较两种络合滴定方案。”

等待保存。

之后问：

“我刚才关于络合滴定说了什么？”

必须查询本地历史。

---

## Test E

问：

“我昨天是不是说过我要去火星？”

如果没有记录：

不得假装记得。

---

# 39. 最终部署报告

创建：

`W:\AI\LocalVoiceAgent\DEPLOYMENT_REPORT.md`

必须包含：

## Architecture

最终实际使用的架构。

不要写原计划。

写真正部署成功的组合。

## ASR Choice

测试过哪些。

为什么最终选这个。

## TTS Choice

测试：

GPT-SoVITS
IndexTTS
或其他候选中的实际可行模型。

说明最终选择理由。

## LLM Choice

当前 model ID
quant
VRAM
TTFT
tok/s

## Versions

所有组件版本和 commit/tag。

## Paths

所有路径。

## Ports

服务端口。

## Resource Usage

Recording

Live idle

Live conversation

三个状态：

CPU
RAM
VRAM

## Latency

ASR
LLM
TTS
E2E

## Scientific Vocabulary

实际测试结果。

## Memory

实际检索测试。

## Privacy

是否有公网连接。

## Offline

断网测试结果。

## Known Problems

所有未解决问题。

## Phase 2

推荐后续增强。

---

# 40. 工作方式

你不是顾问。

你是执行工程师。

不要只输出：

“你可以运行……”

能执行的步骤请直接执行。

流程：

检查
→ 安装
→ 配置
→ 启动
→ 健康检查
→ benchmark
→ 修复
→ 验收
→ 文档

遇到版本差异：

阅读：

- README
- release notes
- --help
- example config
- source code

再适配。

不要凭记忆假设参数。

如果某个高级功能失败：

先交付一个稳定可工作的完整链路。

不要因为一个可选组件失败而让整个部署失败。

---

# 41. 最重要原则

不要为了“技术先进”牺牲实际体验。

一个：

SenseVoice + 可靠本地 LLM + GPT-SoVITS

如果实际达到：

- 低延迟
- 稳定
- 中文准确
- 隐私可靠

就优于：

三个更新、更大、更复杂，但延迟高、OOM、经常崩溃的模型。

所有选型都以本机实际 benchmark 为准。

最终目标不是“展示用了哪些模型”。

最终目标是：

获得一个每天真的愿意开启并长期使用的、本地私密 Live Voice Agent。

---

# 第二部分 · 参考项目分级与 Source Review Gate

先统一分级口径：S = 开工前必须读源码；A = 选到对应模块时必须读；B = 遇到特定问题再查；C = 历史/废弃/只作对照，不作为新实现基础。

这个分级评的是“对你这套系统的工程参考价值”，不是项目本身质量。

几个关键判断有源码依据：voice2 已把 turn_id、FloorManager、InterruptController、stale-turn suppression 明确做成控制平面；Open-LLM-VTuber 当前有独立 ServiceContext、conversation/ASR/TTS provider 层，前端 1.2.1 还专门修过 interruption/audioRef 状态问题；Akane 有显式 temporal-memory hard route；MoeChat 明确区分 Journal 与 Core Memory；Persona Engine 是 dual-Whisper + Silero VAD；CosyVoice 当前仓库已迁移/重定向为 QwenAudio/CosyVoice，并明确提供 bi-streaming。

## 全部参考项目分级表

| 级别 | 项目 / 当前仓库 | 主要参考价值 | 在本项目中的定位 |
| --- | --- | --- | --- |
| S | Open-LLM-VTuber/Open-LLM-VTuber | 总体 Live pipeline、ServiceContext、ASR/TTS/LLM provider、MCP、conversation cancellation | 主 Shell 第一候选 |
| S | Open-LLM-VTuber/Open-LLM-VTuber-Web | audio playback、Live2D、前端 interruption/state management | 主前端/打断参考 |
| S | AIIT-GLITCH/voice2 | turn_id、FloorOwner、控制平面、stale-turn suppression、不可阻塞 audio fan-out | barge-in 必读教材 |
| S | dnhkng/GLaDOS | worker/queue、priority lane、pre-roll、VAD interruption、MCP | 实时状态机参考 |
| S | Lex-au/Vocalis | WebSocket、前后端 barge-in、audio queue、LLM/TTS cancellation | 打断联动参考 |
| S | KoljaB/RealtimeSTT | VAD、pre-roll、endpointing、实时/最终识别、boundary detection | Live ASR 控制层参考 |
| S | KoljaB/RealtimeTTS | streamed text→audio、sentence splitting、pause/resume/stop、audio callbacks | 流式 TTS/播放器参考 |
| S | k2-fsa/sherpa-onnx | SenseVoice CPU、Silero VAD、hotword/lexicon/homophone、speaker | Live ASR baseline |
| S | screenpipe/screenpipe | 24/7 本地历史、audio transcript、REST、MCP、现实事实源 | Passive Recording / Reality Memory |
| S | misaka-coder/AkaneCompanionLab | 时间检索、hard route、近期→摘要→长期记忆 | Episodic/Temporal Memory |
| S | AlfreScarlet/MoeChat | Journal、Core Memory、低延迟中文语音链路 | Memory 分层参考 |
| A | FunAudioLLM/SenseVoice | 中文/中英混合 ASR 模型本体 | Live ASR benchmark |
| A | modelscope/FunASR | VAD、streaming、hotword、speaker/diarization 工具链 | ASR 工具链 |
| A | 0x5446/api4sensevoice | 极简 SenseVoice WebSocket 服务、VAD、speaker verification | ASR service adapter 参考 |
| A | snakers4/silero-vad | VAD 原始实现与阈值行为 | VAD benchmark |
| A | SYSTRAN/faster-whisper | Whisper CTranslate2、CPU/GPU quantization | Archive ASR / second pass |
| A | ggml-org/whisper.cpp | 原生 C/C++、Windows/CPU、stream 示例 | ASR 替代路线 |
| A | QwenLM/Qwen3-ASR | 高质量 multilingual/术语 second-pass 候选 | Archive/second-pass benchmark |
| A | RVC-Boss/GPT-SoVITS | 中文角色音色、streaming API | TTS 第一批 benchmark |
| A | QwenAudio/CosyVoice | bi-streaming、中文、发音控制、拼音/phoneme | TTS 第一批 benchmark |
| A | index-tts/index-tts | IndexTTS2、streaming/TRT 路线、音色/情感 | TTS 第一批 benchmark |
| A | OHF-Voice/piper1-gpl | 极轻本地 TTS、CPU baseline | fallback / barge-in 测试 TTS |
| A | elevenyellow/handcrafted-persona-engine | Windows Native、Live2D、dual Whisper、lip-sync | Windows/角色层参考 |
| A | Zao-chen/ZcChat2 | Qt/C++ 桌宠、流式 LLM/TTS、离散表情动作 | 轻量桌宠参考 |
| A | moeru-ai/airi | Stage UI、Live2D/VRM、provider abstraction、角色状态 | 前端/角色架构参考 |
| A | SlimeBoyOwO/LingChat | AI companion UX、角色包、永久记忆、桌宠/剧情 | 产品体验层参考 |
| B | fishaudio/fish-speech | 高质量本地 TTS | 资源允许时额外 benchmark |
| B | lhl/voicechat2 | WebSocket、STT→LLM→TTS interleaving | 经典 pipeline 参考 |
| B | proj-airi/webai-example-realtime-voice-chat | 极简 VAD→STT→LLM→TTS 示例 | 排障/理解数据流 |
| B | pipecat-ai/pipecat | production voice pipeline/event architecture | Phase 2 架构教材 |
| B | pipecat-ai/smart-turn | semantic end-of-turn | Phase 2 turn detection |
| B | TEN-framework/ten-framework | semantic turn detection / conversational voice agent | Phase 2 |
| B | livekit/agents | interruption、preemptive generation、agent session | 成熟状态机参考 |
| B | letta-ai/letta-code | Core/archival/stateful agent memory | Phase 2 Core Memory |
| B | OHF-Voice/wyoming | 本地 voice service protocol | 服务拆分时参考 |
| B | Lex-au/Orpheus-FastAPI | OpenAI-compatible /v1/audio/speech adapter 模式 | TTS adapter 参考 |
| C | Zao-chen/ZcChat | Letta/VITS/旧桌宠实现 | 已被 ZcChat2 替代，仅历史参考 |
| C | rhasspy/piper | 旧 Piper 实现 | 已归档，改看 OHF-Voice/piper1-gpl |

Screenpipe 当前确实提供本地 localhost:3030 API 和 MCP，MCP HTTP 默认绑定 loopback；但其文档也明确说明 Sentry/analytics 行为，因此你的 privacy-audit.ps1 和显式 telemetry disable 不能删。 api4sensevoice 当前则明确包含 VAD、WebSocket streaming 和 speaker verification，可作为很干净的 SenseVoice service 示例。 RealtimeSTT 当前 audio_recorder.py 已包含 pre-roll、Silero/WebRTC VAD、boundary detector 等，而 RealtimeTTS 明确支持流式输入、stop/pause/resume 与 chunk callback。

下面这一整块可以直接接到你原提示词第 41 节后面。

---

# 42. Reference Implementations / Mandatory Source Review

本项目不得在不了解已有成熟实现的情况下自行重新设计实时语音状态机、barge-in、ASR endpointing、TTS streaming、长期记忆和角色状态系统。

参考项目的目的不是拼装依赖，也不是直接复制整个项目。

目标是：

先阅读成熟实现 → 理解其 invariant / state machine / API boundary → 提取适合本项目的最小设计 → 在本机实现和 benchmark。

⸻

## 42.1 Reference Review 基本规则

参考项目按四级管理：

S — Mandatory Source Review

在开始实现对应核心模块以前必须阅读。

A — Module Mandatory

只有实际选择或修改对应模块时必须阅读。

B — Problem-Driven Reference

遇到对应架构或性能问题时阅读。

C — Historical / Legacy

仅用于理解历史方案、迁移关系或反例。

禁止因为某项目级别为 S 或 A 就自动安装它。

禁止一次性安装全部参考项目。

如果需要 clone 参考源码：

统一放置到：

`W:\AI\LocalVoiceAgent\references`

优先使用 shallow clone。

参考项目不得污染：

* 系统 Python
* 系统 Node
* 用户现有 LM Studio
* 用户其他 AI 项目
* CUDA 全局环境

除最终实际采用的组件外，不得为“读代码”安装大型模型或 GPU runtime。

开始部署前建立：

`W:\AI\LocalVoiceAgent\docs\reference-review.md`

对所有 S 级项目记录：

* repository
* branch / tag
* commit hash
* 阅读日期
* 阅读的文件
* 学到的设计
* 决定采用的设计
* 明确拒绝采用的设计
* license
* 是否存在 cloud dependency
* 是否存在 telemetry
* 是否适合 Windows
* 是否适合 RTX 4060 8GB
* 是否实际进入最终依赖树

如果本节列出的路径因上游版本变化而不存在：

不要假定项目删除了该功能。

使用：

* repository search
* symbol search
* README
* release notes
* tests
* --help
* example config

找到当前等价实现。

⸻

## 42.2 S 级：开工前必须阅读

### 42.2.1 Open-LLM-VTuber

Repository:

Open-LLM-VTuber/Open-LLM-VTuber

本项目第一版 Live Voice shell 的首选参考。

必须阅读：

src/open_llm_vtuber/service_context.py

src/open_llm_vtuber/conversations/single_conversation.py

src/open_llm_vtuber/conversations/tts_manager.py

src/open_llm_vtuber/asr/sherpa_onnx_asr.py

src/open_llm_vtuber/asr/faster_whisper_asr.py

src/open_llm_vtuber/agent/stateless_llm/openai_compatible_llm.py

src/open_llm_vtuber/tts/gpt_sovits_tts.py

src/open_llm_vtuber/tts/tts_factory.py

src/open_llm_vtuber/config_manager/asr.py

src/open_llm_vtuber/config_manager/tts.py

以及当前：

README
release notes
默认配置模板
MCP 配置
Live2D expression prompt

重点学习：

* ServiceContext 如何隔离 ASR / TTS / LLM / VAD
* conversation 生命周期
* async cancellation
* TTS task 管理
* OpenAI-compatible LLM
* provider factory
* Live2D expression 注入
* MCP/tool 生命周期
* faster-first-response
* 多 TTS segment 并发生成

禁止直接照搬：

* 默认 Edge TTS
* 云端 provider
* 默认网络配置
* 未经验证的默认 context
* 未 benchmark 的 ASR/TTS 默认值
* 自动模型下载路径
* telemetry 或第三方调用
* 任何会占用额外 GPU 而无 benchmark 依据的默认设置

遇到以下问题首先查：

* Open-LLM-VTuber 无法对接 LM Studio
* conversation cancellation 无效
* TTS queue 混乱
* provider 配置问题
* MCP integration
* Live2D 状态不能正确同步

⸻

### 42.2.2 Open-LLM-VTuber-Web

Repository:

Open-LLM-VTuber/Open-LLM-VTuber-Web

必须阅读当前 src/ 内负责：

* audio playback
* audio queue
* interruption
* WebSocket
* Live2D
* conversation state

的实现。

使用 repository search 搜索：

audioRef

interrupt

stop

audio queue

playback

speaking

listening

同时阅读最近与 interruption 有关的 release / fix diff。

重点学习：

* 全局播放器引用
* frontend interruption
* backend cancellation 与 frontend playback stop 的同步
* Live2D speaking / listening 状态
* stale audio 清理

禁止直接照搬：

* 与当前 Electron/Web UI 强绑定的状态管理
* 不需要的 UI 组件
* 云服务相关 provider
* 与本项目无关的直播功能

遇到：

“后端已经取消但声音还在播”

“打断后旧声音又恢复”

“角色状态卡在 speaking”

首先查这里。

⸻

### 42.2.3 voice2

Repository:

AIIT-GLITCH/voice2

这是本项目 barge-in 控制平面的核心参考。

必须阅读：

voice2/config.py

voice2/tests/

以及 repository 中定义以下符号的全部文件：

StateController

FloorManager

InterruptController

InvariantChecker

AudioBroadcaster

ListenWorker

InterruptDetectorWorker

ThinkWorker

PlaybackWorker

turn_id

重点学习：

Control Plane

语音数据平面和状态控制平面必须分开。

必须存在显式状态：

IDLE

LISTENING

THINKING

SPEAKING

以及必要的 interruption 状态。

必须存在：

FloorOwner.USER

FloorOwner.AGENT

FloorOwner.NONE

Turn ID

每一次用户 utterance 必须拥有 monotonic：

turn_id

或：

generation_id

LLM、TTS、playback 产生的所有结果必须携带所属 turn。

用户发生 barge-in 后：

* invalidate 当前 turn
* cancel LLM generation，如果 backend 支持
* cancel pending TTS
* purge audio queue
* stop current playback
* FloorOwner → USER

任何属于旧 turn 的：

* late LLM result
* late TTS result
* buffered PCM
* playback request

必须直接丢弃。

禁止旧 turn 在 interruption 以后恢复播放。

AudioBroadcaster

麦克风 callback 不得等待：

* ASR
* VAD
* disk
* LLM
* TTS

capture path 必须保持 non-blocking。

消费者过慢时优先：

drop-oldest / bounded buffer

而不是阻塞 microphone capture。

禁止直接照搬：

* Linux-only 部署假设
* Piper 英文 voice
* small.en Whisper
* 项目具体 UI
* 3090 环境参数

遇到：

* AI 被打断后又继续说
* interruption race condition
* 两个 turn 的声音混在一起
* microphone callback 卡住
* SPEAKING/LISTENING 状态错乱

首先查 voice2。

⸻

### 42.2.4 GLaDOS

Repository:

dnhkng/GLaDOS

必须阅读：

README 中：

* Audio Pipeline
* Interruption Handling
* Thread Architecture
* Context Building

以及 src/ 内定义：

SpeechListener

LLMProcessor

SpeechSynthesizer

SpeechPlayer

和 conversation / memory / MCP 相关组件的文件。

重点学习：

* INPUT / PROCESSING / OUTPUT worker separation
* queue boundary
* priority user lane
* pre-activation audio buffer
* VAD → interruption
* playback interruption
* user input 优先于 autonomous behavior
* shutdown ordering
* echo/self-trigger 问题

禁止直接照搬：

* Parakeet 作为中文 ASR
* GLaDOS 专属声音
* 英语优先参数
* autonomous speaking 默认行为

遇到：

* worker deadlock
* input/output 队列设计
* AI 自己听到自己
* pre-roll 丢失句首
* 被动行为抢占用户讲话

查 GLaDOS。

⸻

### 42.2.5 Vocalis

Repository:

Lex-au/Vocalis

必须阅读：

backend/routes/websocket.py

backend/services/transcription.py

backend/services/tts.py

backend/services/llm.py

frontend/src/services/audio.ts

frontend/src/services/websocket.ts

重点学习：

* WebSocket duplex messaging
* 前端 audio buffer
* interruption 从前端到后端的完整传播
* cancel LLM
* stop TTS
* clear client playback
* chunk-based streaming audio

禁止直接照搬：

* Faster-Whisper 英语默认参数
* 它的视觉 UI
* 其宣称的 latency 数据
* 云 provider 配置

所有 latency 必须在本机重新 benchmark。

遇到：

* frontend 和 backend interruption 不同步
* stop 以后客户端仍播放缓存
* WebSocket 音频消息设计
* streaming TTS chunk protocol

查 Vocalis。

⸻

### 42.2.6 RealtimeSTT

Repository:

KoljaB/RealtimeSTT

必须阅读：

RealtimeSTT/audio_recorder.py

docs/configuration.md

当前 boundary / endpoint detector 实现

当前 pre-roll 实现

相关 tests。

重点学习：

* pre-recording buffer
* Silero / WebRTC VAD
* speech boundary
* post-speech silence
* realtime model 与 final model 分离
* text stabilization
* wake word callback
* event callback

不要复制其所有功能。

本项目第一版只需要：

* VAD
* endpoint
* pre-roll
* callback
* interruption signal

禁止：

默认加入 wakeword、多个 VAD、复杂 NLP endpointing。

遇到：

* 开头吞字
* 结束判断太慢
* 用户停顿被误判
* VAD 抖动
* realtime transcript 不稳定

查 RealtimeSTT。

⸻

### 42.2.7 RealtimeTTS

Repository:

KoljaB/RealtimeTTS

必须阅读：

README 的：

* Streaming Text
* stop / pause / resume
* engine selection

docs/llm-streaming.md

docs/output-and-files.md

example_fast_api/

以及当前实现 TextToAudioStream 的源码。

重点学习：

LLM text stream 不应等待完整回答结束。

应形成：

LLM token stream
→ sentence / phrase segmentation
→ TTS generation
→ PCM queue
→ playback

这些阶段可以并行。

必须支持：

* stop
* cancel
* queue purge
* audio chunk callback

禁止直接采用：

* Edge
* Google
* Azure
* ElevenLabs
* OpenAI TTS
* 其他云 engine

即使 RealtimeTTS 支持它们。

遇到：

* TTFA 高
* 必须等完整文本才能出声
* TTS stop 很慢
* audio queue 不能清理

查 RealtimeTTS。

⸻

### 42.2.8 sherpa-onnx

Repository:

k2-fsa/sherpa-onnx

必须阅读：

python-api-examples/simulate-streaming-sense-voice-microphone.py

SenseVoice examples

Silero VAD examples

keyword spotting / hotword examples

homophone replacer / lexicon examples

speaker identification / verification examples

重点学习：

* CPU SenseVoice
* ONNX Runtime thread setting
* VAD + non-streaming ASR simulated streaming
* hotword/context bias
* homophone correction
* speaker filtering

专业词处理优先顺序：

ASR hotword/context bias

→ lexicon/homophone correction

→ context-aware post processing

禁止第一版直接使用：

“LLM 自动改写整段 transcript”。

原始 transcript 必须始终保留。

遇到：

* “络合”→“洛河”
* 中英混合术语
* speaker filtering
* ASR 想完全留在 CPU

首先查 sherpa-onnx。

⸻

### 42.2.9 Screenpipe

Repository:

screenpipe/screenpipe

必须阅读：

packages/screenpipe-mcp/README.md

crates/screenpipe-core/assets/skills/screenpipe-api/SKILL.md

当前 audio recording / transcription 文档

当前：

screenpipe record --help

和实际安装版本的配置。

重点学习：

* localhost REST API
* audio history search
* MCP
* timestamp handling
* retranscription
* Reality Memory 数据结构
* local API authentication

Screenpipe 在本项目中的职责：

事实源。

它负责回答：

“现实中到底有没有记录到这件事？”

Screenpipe 的原始 transcript / audio metadata 不应被 AI 自由改写。

禁止：

* 默认启用 vision
* OCR
* cloud sync
* cloud ASR
* LAN exposure
* 0.0.0.0
* 默认 analytics / Sentry 未审计状态

必须明确测试并关闭：

telemetry
analytics
Sentry

如果无法关闭：

记录 endpoint 并在本机阻断。

遇到：

* “昨天我说过什么？”
* 现实历史查询
* MCP 查询历史
* second-pass archive ASR
* passive recorder

查 Screenpipe。

> 部署层面的 Screenpipe 要求见第 16、17 节。

⸻

### 42.2.10 AkaneCompanionLab

Repository:

misaka-coder/AkaneCompanionLab

必须阅读：

companion_v01/retrieval_service.py

companion_v01/memory_rendering.py

companion_v01/prompt_builder.py

companion_v01/store.py

companion_v01/vector_store.py

以及 memory tests。

重点学习：

Temporal Memory Router

涉及：

“记得”

“之前”

“上次”

“昨天”

“前天”

“那次”

“说过”

“聊过”

“提过”

等表达时，不完全依赖 LLM tool calling。

允许 deterministic routing。

Memory hierarchy

区分：

recent raw conversation

阶段摘要

long-term episodic memory

Time-aware retrieval

时间是一级检索约束。

不要单纯：

embedding(query)
→ vector database top-k

来回答：

“昨天我们说了什么”。

禁止直接照搬：

* 其完整桌宠实现
* 其 alpha 状态项目结构
* 其默认模型/provider
* 未验证的 embedding backend

遇到：

* vector search 找不到“昨天”
* 历史事件时间错乱
* “我是不是说过”查询不可靠

首先查 AkaneCompanionLab。

⸻

### 42.2.11 MoeChat

Repository:

AlfreScarlet/MoeChat

必须阅读：

README 中：

Journal System

Core Memory

低延迟语音链路

以及：

core/

services/

api/

web/

中对应 memory / TTS / LLM interaction 的实现。

重点学习：

Journal 与 Core Memory 必须分开。

Journal：

“发生过什么、什么时候发生？”

Core Memory：

“有哪些稳定事实值得长期记住？”

禁止：

* 把全部 Journal 塞入 context
* 用 vector DB 完全替代 temporal retrieval
* 为使用 memory 而强绑定 GPT-SoVITS

遇到：

* 对话长期记忆
* 时间型 recall
* Core Memory 设计
* 中文低延迟 pipeline

查 MoeChat。

⸻

## 42.3 A 级：选择对应模块时必须阅读

### ASR

#### SenseVoice

Repository:

FunAudioLLM/SenseVoice

读取：

README
当前 inference 示例
模型输入输出定义

用途：

中文 Live ASR baseline。

不要因为项目本身来自 FunAudioLLM 就跳过本机 benchmark。

⸻

#### FunASR

Repository:

modelscope/FunASR

读取当前：

streaming ASR
VAD
hotword
punctuation
speaker / diarization
server examples

用途：

当 SenseVoice 需要更完整 production pipeline 时参考。

禁止整体引入完整 FunASR stack，除非 benchmark 证明有必要。

⸻

#### api4sensevoice

Repository:

0x5446/api4sensevoice

必须读：

server_wss.py

server.py

model.py

client_wss.html

speaker/

用途：

建立一个小型、独立的 SenseVoice WebSocket adapter 时参考。

禁止直接复制：

TLS/server 暴露方式
固定 speaker 路径
公网 bind

⸻

#### Silero VAD

Repository:

snakers4/silero-vad

读取：

README
streaming examples
ONNX examples

用途：

VAD threshold 和 chunk behavior。

禁止从其他项目复制一个 threshold 后认为它适用于本机麦克风。

必须实测。

⸻

#### Faster-Whisper

Repository:

SYSTRAN/faster-whisper

读取：

README
transcribe examples
CPU/GPU compute type
batched inference

用途：

Archive ASR / second pass。

不要默认 large-v3-turbo 一定优于 SenseVoice。

⸻

#### whisper.cpp

Repository:

ggml-org/whisper.cpp

读取：

README

examples/stream/

Windows build/inference documentation

用途：

当 Faster-Whisper Windows 环境复杂、CPU 性能或分发体验较差时比较。

⸻

#### Qwen3-ASR

Repository:

QwenLM/Qwen3-ASR

读取：

README
inference
timestamp
streaming/current serving support

用途：

专业术语 second-pass 候选。

禁止在未测：

VRAM
RTF
endpoint latency

以前放进 Live path。

⸻

### TTS

#### GPT-SoVITS

Repository:

RVC-Boss/GPT-SoVITS

必须读：

api_v2.py

GPT_SoVITS/TTS_infer_pack/

当前 streaming inference config。

优先研究：

localhost API
streaming_mode
text split
reference audio
model hot-loading 行为

禁止默认：

每句重新加载模型。

⸻

#### CosyVoice

当前 Repository:

QwenAudio/CosyVoice

必须读：

example.py

webui.py

runtime/python/fastapi/server.py

runtime/python/fastapi/client.py

以及当前 streaming inference。

重点：

* text-in streaming
* audio-out streaming
* pronunciation control
* Chinese Pinyin
* English phoneme

本项目禁止因为官方文档提供 Docker 示例就使用 Docker。

必须原生 Windows benchmark；无法稳定后再降级。

⸻

#### IndexTTS

Repository:

index-tts/index-tts

读取：

普通 inference

backends/trt/infer.py

backends/trt/README.md

重点记录：

TTFA
streaming chunk
VRAM
model residency

禁止根据 A100 / A6000 等公开 benchmark 推断 RTX 4060 8GB 结果。

⸻

#### Piper

当前 Repository:

OHF-Voice/piper1-gpl

用途：

CPU fallback。

同时作为：

control-plane latency baseline。

如果 Piper 下 barge-in 仍然很慢：

问题主要在状态机，而不是高质量 TTS。

注意：

旧 rhasspy/piper 已不作为当前实现参考。

复制代码前检查 GPL-3.0 license compatibility。

⸻

### Desktop Character / UI

#### Persona Engine

Repository:

elevenyellow/handcrafted-persona-engine

必须读：

README.md

INSTALLATION.md

CONFIGURATION.md

Live2D.md

src/PersonaEngine/

重点：

* Windows native
* dual Whisper
* Silero
* Live2D
* lip-sync
* latency metrics
* transparent overlay

借鉴：

fast ASR 用于 interaction control
accurate ASR 用于 semantic transcript

禁止照搬：

所有 ASR/TTS 都占 CUDA 的 GPU-first 策略。

本项目 GPU 优先级仍为：

LLM > TTS > ASR。

⸻

#### ZcChat2

Repository:

Zao-chen/ZcChat2

读取：

README

windows/

utils/

tests/

并通过 repository search 找到：

streaming LLM
TTS segmentation
voice input
wake-up
continuous conversation
memory compression

重点学习：

轻量桌面应用。

以及：

LLM semantic state
→ discrete expression / pose / animation

禁止因为其 Galgame sprite 路线而放弃最终 Live2D。

⸻

#### AIRI

Repository:

moeru-ai/airi

重点阅读：

stage-ui

core-agent

core-character

pipelines-audio

stage-ui-live2d

stage-ui-three

stage-tamagotchi

重点：

* provider abstraction
* character state
* Live2D/VRM rendering
* audio pipeline 与 UI 解耦

禁止为了借一个 UI 子系统引入整个 AIRI monorepo。

禁止启用默认云 provider。

⸻

#### LingChat

Repository:

SlimeBoyOwO/LingChat

读取：

src/

src-tauri/

docs/

重点搜索：

memory
desktop pet
character
emotion
schedule
story

主要学习：

产品体验。

包括：

角色包
长期存档
桌宠切换
主动行为
剧情/日程
情绪

禁止把其“companion experience first”的架构直接当成本项目 offline voice core。

任何本地模型能力必须单独验证。

⸻

## 42.4 B 级：出现具体问题再阅读

### voicechat2

Repository:

lhl/voicechat2

查：

LLM text streaming 与 TTS interleaving。

适合解决：

“为什么必须等完整回答才开始说话？”

不作为 Windows deployment baseline。

⸻

### WebAI realtime voice example

Repository:

proj-airi/webai-example-realtime-voice-chat

适合：

快速理解：

VAD
→ STT
→ LLM
→ TTS

最小数据流。

用于排障，不作为正式架构。

⸻

### Pipecat

Repository:

pipecat-ai/pipecat

Phase 2 查：

pipeline events
interruption frames
turn strategies
production realtime architecture

不要第一阶段直接引入整个 framework。

⸻

### Smart Turn

Repository:

pipecat-ai/smart-turn

当 silence endpointing 出现：

“用户只是思考停顿，AI 就开始回答”

时研究。

第一阶段不强制引入 semantic turn model。

⸻

### TEN Framework

Repository:

TEN-framework/ten-framework

遇到：

semantic end-of-turn
conversation state
复杂实时语音编排

时研究。

⸻

### LiveKit Agents

Repository:

livekit/agents

研究：

false interruption
resume
preemptive generation
adaptive endpointing
agent session state

不要引入 LiveKit cloud/network stack，只学习状态机。

⸻

### Letta Code

Repository:

letta-ai/letta-code

Phase 2 研究：

Core Memory
archival memory
stateful agent

本项目不能让 Letta 替代 Screenpipe 的 Reality Memory。

现实事实：

Screenpipe 是事实源。

Letta-style memory 只能是派生层。

⸻

### Wyoming

Repository:

OHF-Voice/wyoming

当未来需要把：

ASR
TTS
wakeword

拆成独立本地进程时研究其协议设计。

第一版不需要引入。

⸻

### Fish Speech

Repository:

fishaudio/fish-speech

只有在 GPT-SoVITS / CosyVoice / IndexTTS 之后仍有必要提升角色音质时 benchmark。

不允许因为音质好而牺牲：

VRAM
TTFA
barge-in
稳定性。

⸻

### Orpheus-FastAPI

Repository:

Lex-au/Orpheus-FastAPI

主要学习：

把独立 TTS 服务封装成：

OpenAI-compatible

/v1/audio/speech

这样的薄 adapter。

不代表需要使用 Orpheus 模型本身。

⸻

## 42.5 C 级：历史参考

### ZcChat

Repository:

Zao-chen/ZcChat

旧项目。

只用于理解：

Letta integration
VITS integration
早期 voice interruption
Galgame desktop pet

新开发优先查看：

Zao-chen/ZcChat2

不得基于旧 ZcChat 开新实现。

⸻

### Old Piper

Repository:

rhasspy/piper

已不作为当前 Piper implementation source。

只作历史参考。

新实现查看：

OHF-Voice/piper1-gpl

⸻

## 42.6 Problem → Reference Lookup Table

遇到问题时按以下顺序查参考项目。

| 问题 | 首先查 | 第二参考 |
| --- | --- | --- |
| AI 无法立即被打断 | voice2 | Open-LLM-VTuber-Web / Vocalis |
| 打断后旧回答又开始播放 | voice2 turn_id | Vocalis |
| LLM 已取消但声音继续播放 | Open-LLM-VTuber-Web | RealtimeTTS |
| 两个 turn 的 TTS 混在一起 | voice2 | Open-LLM-VTuber |
| 麦克风 capture 卡顿 | voice2 AudioBroadcaster | RealtimeSTT |
| 开头吞字 | RealtimeSTT pre-roll | GLaDOS pre-buffer |
| VAD 太敏感 | Silero VAD | RealtimeSTT |
| 用户停顿就被判断说完 | RealtimeSTT | Smart Turn / TEN |
| 用户说话 AI 自己也被识别 | GLaDOS | speaker verification / echo cancellation |
| 中文 ASR 延迟高 | sherpa-onnx SenseVoice | FunASR |
| “络合”识别成“洛河” | sherpa-onnx lexicon/homophone | SenseVoice/FunASR hotword |
| 科学术语仍然错误 | Qwen3-ASR second-pass | Faster-Whisper |
| TTS 必须等完整文本 | RealtimeTTS | voicechat2 |
| TTS 第一段声音太慢 | GPT-SoVITS / CosyVoice | IndexTTS |
| 怀疑控制平面而非 TTS 慢 | Piper baseline | voice2 latency trace |
| “昨天我说了什么” | Screenpipe + Akane | MoeChat Journal |
| 真实历史被 AI 编造 | Screenpipe | deterministic memory router |
| Core Memory 设计 | MoeChat | Letta |
| 时间型 memory 检索差 | AkaneCompanionLab | MoeChat |
| Live2D 状态不同步 | Open-LLM-VTuber-Web | Persona Engine / AIRI |
| 桌宠占用过重 | ZcChat2 | AIRI |
| 表情动作语义控制 | ZcChat2 / Akane | AIRI |
| Windows Live2D/lip-sync | Persona Engine | Open-LLM-VTuber |
| MCP 历史查询 | Screenpipe MCP | Open-LLM-VTuber MCP |
| 服务进程协议越来越混乱 | Wyoming | Pipecat |
| realtime pipeline 过于耦合 | Pipecat | LiveKit Agents |
| 需要 semantic turn detection | Smart Turn | TEN |
| TTS adapter 很难统一 | Orpheus-FastAPI | RealtimeTTS |
| 离线状态仍访问公网 | Screenpipe/Open-LLM 配置检查 | privacy-audit.ps1 |

⸻

## 42.7 必须采用的核心设计原则

无论最终使用哪个 shell，都必须实现下面的逻辑：

```
Mic
 │
 ▼
Audio Capture
 │
 ├──────────────────────────────────────┐
 │                                      │
 ▼                                      ▼
PASSIVE RECORDING                    LIVE MODE
 │                                      │
VAD                                     AudioBroadcaster
 │                                      │
Archive                                 ├── Live ASR
 │                                      │      │
Screenpipe                              │      ▼
 │                                      │   turn_id N
second-pass ASR                         │      │
 │                                      │      ▼
raw transcript                          │     LLM
corrected transcript                    │      │
 │                                      │ text stream
Reality Memory                          │      ▼
                                        │ sentence/chunk splitter
                                        │      │
                                        │      ▼
                                        │     TTS
                                        │      │
                                        │      ▼
                                        │ audio queue
                                        │      │
                                        │      ▼
                                        │ playback
                                        │
                                        └── Interrupt Detector
                                               │
                                               ▼
                                       InterruptController
                                               │
                         ┌─────────────────────┼─────────────────────┐
                         ▼                     ▼                     ▼
                    invalidate             cancel               purge
                    turn_id N              LLM/TTS             audio queue
                         │
                         ▼
                    stop playback
                         │
                         ▼
                  FloorOwner = USER
```

> 该图是第 23 节的实现依据；第 23.1 节把它展开为可验收的条目。

⸻

## 42.8 Memory Architecture

长期记忆不得被实现成一个数据库解决所有问题。

必须区分：

### Reality Memory

来源：

Screenpipe

保存：

现实中实际捕获到的 audio/transcript/timestamp。

这是事实源。

禁止 LLM 重写事实源。

### Episodic / Temporal Memory

参考：

AkaneCompanionLab
MoeChat Journal

保存：

最近对话
阶段摘要
过去事件
时间范围

负责：

“我们什么时候聊过这个？”

“昨天说了什么？”

### Core / Semantic Memory

参考：

MoeChat Core Memory
Letta

保存：

稳定用户事实
长期偏好
角色关系
长期项目状态

不得保存：

能够通过历史检索重新获得的所有细节。

> 与第 18、19、20 节的关系：第 18–20 节规定的是「运行时如何使用记忆」；本节规定的是「记忆如何分层与归属」。两者同时生效。

⸻

## 42.9 Reference Review Gate

在写第一行业务集成代码之前，必须生成：

`docs\reference-review.md`

至少完成所有 S 级项目的阅读结果。

同时生成：

`docs\architecture-decisions.md`

其中明确：

ADR-001

Live shell 最终选择：

Open-LLM-VTuber
或其他实际验证后的 shell。

ADR-002

Live ASR 选择。

ADR-003

Archive / second-pass ASR 选择。

ADR-004

TTS 选择。

ADR-005

Barge-in control plane。

必须说明：

是否采用 turn_id
如何 invalidate old turn
如何 purge TTS
如何停止 playback
如何避免 stale response。

ADR-006

Memory architecture。

必须说明：

Reality Memory
Episodic Memory
Core Memory

三者的数据边界。

ADR-007

GPU allocation。

ADR-008

Privacy / telemetry。

只有在完成 reference review 后，才开始大规模安装和修改。

但不得因为 reference review 阻塞最小 working pipeline。

如果某个参考项目无法访问或源码已经发生重大变化：

记录：

REFERENCE_UNAVAILABLE

然后使用下一优先级参考继续。

不要停掉整个部署。

⸻

## 42.10 最终原则

参考项目不是 dependency checklist。

最终系统应尽量保持简单。

一个理想结果可能只是：

Open-LLM-VTuber

* sherpa-onnx SenseVoice
* LM Studio
* GPT-SoVITS 或 CosyVoice
* Screenpipe
* 一个很薄的 temporal memory router

但其中的：

barge-in control plane

应借鉴：

voice2
GLaDOS
Vocalis

memory retrieval

应借鉴：

AkaneCompanionLab
MoeChat

character/UI

应借鉴：

Open-LLM-VTuber-Web
ZcChat2
AIRI
Persona Engine

这与“把这些项目全部安装进系统”是完全不同的概念。

最终依赖越少越好。

最终行为越稳定越好。

所有选型仍然以：

本机 benchmark、Windows 稳定性、隐私、latency 和长期维护成本

为最终依据。

---

# 附 · 核验记录（合并版新增）

关键文件已重新核验：

- Open-LLM-VTuber 的 `service_context.py`、`single_conversation.py` 和 `sherpa_onnx_asr.py` 当前都存在。
- GPT-SoVITS 当前 `api_v2.py` 默认支持 loopback 和 streaming。
- IndexTTS 当前 `backends/trt/infer.py` 已有 streaming/TTFA 路径。
- CosyVoice 官方目录中有 `runtime/python/fastapi` 服务实现。

第 42 节不只是“参考资料列表”，而是增加了一个 Source Review Gate 和 ADR 产物。这样执行 AI 不能简单回复一句“已参考 voice2 / GLaDOS”，而必须写下自己到底读了哪个 commit、借了什么 invariant、拒绝了什么设计。

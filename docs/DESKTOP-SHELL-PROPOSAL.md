# 桌面化方案 — 轻量后台 exe + 快捷键唤醒 + 桌面 Live2D + 多角色

日期：2026-09-18 01:15 (+08:00)，01:25 增补形象/音色节
需求拆解：① 占用小的后台 exe ② 快捷键唤出并加载模型 ③ GUI 选择模型/接入 API ④ Live2D 脱离浏览器（桌面或 exe 窗口内）⑤ 远期多角色同屏对话 ⑥ Live2D 形象可自定义 ⑦ 音色可训练为指定声音
参考源码核验：handcrafted-persona-engine（README+文档）、ZcChat2（README+目录）、airi（README+架构）、Open-LLM-VTuber（本机全文）、voice2/Vocalis（已克隆精读）

## 一、参考项目的相关实现（结论：有，且各管一段）

| 需求 | 参考实现 | 已核事实 | 可借鉴度 |
|---|---|---|---|
| 轻量后台 + 托盘 | **ZcChat2**（Qt/C++） | 后台内存 40MB→**8MB**；托盘点开设置；流式 LLM/TTS；一键导入角色包 | ★★★★★ 占用标杆 |
| 桌面 Live2D 透明窗口 | **handcrafted-persona-engine**（.NET/C#） | 原生 Live2D 渲染 + **透明置顶 overlay 窗口**（不依赖 OBS），Spout 外送，VBridger lip-sync | ★★★★ 保真度标杆 |
| 渲染/Provider 抽象 | **airi**（Electron+Vue） | stage-ui 三端共享（web/桌面/移动）；**unspeech**：ASR/TTS 统一 OpenAI 兼容代理；xsai 30+ LLM provider | ★★★★ 抽象标杆 |
| 多角色同时对话 | **Open-LLM-VTuber 本机源码** | `chat_group.py` + `group_conversation.py`：ChatGroupManager、多 client 入组、广播、group interrupt——**后端已原生支持** | ★★★★★ 现成 |
| 快捷键唤醒 | 无直接对应 | voice2 有 keyboard worker（本地热键监听），Windows 侧标准做法 RegisterHotKey/QHotkey/Tauri globalShortcut | ★★ 机制简单 |
| 模型按需加载 | 无直接对应 | llama-server/LM Studio 本就按需装卸载；ZcChat2 的"获取模型列表→选择"交互模式可抄 | ★★ |

**关键判断：不需要自研渲染。E 盘现有后端（open-llm-vtuber :12393 + screenpipe :3030 + llama-server :1234）一个不换，只加一层桌面壳。** Open-LLM-VTuber-Web 前端已含 Live2D（pixi 系 WebGL），多角色后端已存在——缺的只是"把浏览器窗口变成桌面宠物窗口"和"托盘/热键/模型管理"。

## 二、推荐架构：Tauri 壳 + 复用现有前端与后端

```
┌─ lva-pet.exe（Tauri v2，Rust 壳，目标常驻 ≤30MB）────────────────┐
│  托盘（tray-icon）│ 全局热键（globalShortcut，如 Ctrl+Space）      │
│  透明无边框置顶窗口（WebView2，渲染 stage 前端）                   │
│  设置窗口（模型/API 选择 GUI）                                     │
│  进程管家（按需启停 llama-server / open-llm-vtuber / screenpipe） │
└──────┬───────────────────┬──────────────────────┬───────────────┘
       │ WebSocket :12393   │ HTTP :1234            │ REST :3030
┌──────▼──────┐    ┌───────▼───────┐       ┌───────▼──────┐
│ open-llm-   │    │ llama-server  │       │ screenpipe   │
│ vtuber      │    │ （按需加载/   │       │ （24/7 常驻  │
│ （含 group  │    │  换模型）     │       │  或随壳启停） │
│  多角色）    │    └───────────────┘       └──────────────┘
└─────────────┘
```

**为什么是 Tauri 而不是其他路线**（对照参考实现）：

| 路线 | 占用 | Live2D 保真 | 开发量 | 判决 |
|---|---|---|---|---|
| **Tauri + WebView2 复用现有 Web 前端** | 壳 ~10-30MB（ZcChat2 级） | 与浏览器一致（pixi/WebGL） | **最小**（前端零重写） | ✅ 推荐 |
| Qt/C++ 原生（ZcChat2 路线） | 最小（8MB 标杆） | Qt 里嵌 Cubism 或 WebEngine，工程量大 | 大 | 除非占用是硬指标 |
| .NET + Cubism 原生（persona-engine 路线） | 中 | 最高（VBridger 级 lip-sync） | 最大 + Cubism SDK 商业许可问题 | 远期保真升级选项 |
| Electron（airi 路线） | 大（100MB+） | 与浏览器一致 | 中 | 与"占用小"冲突，排除 |

Tauri 用系统 WebView2（Win11 预装），无 Chromium 打包开销；透明无边框置顶窗口是 Tauri 一等能力（transparent + decorations:false + always_on_top + ignore_cursor_events 穿透点击）。

## 三、逐项需求落地方案

### 1. 后台 exe + 快捷键唤出（对应 ZcChat2 占用标杆）
- 壳常态驻托盘，**不创建窗口、不连后端**，内存 ≈ Rust 运行时 + tray ≈ 10MB 量级；
- 热键（Tauri `globalShortcut`，建议默认 `Ctrl+Space`，设置里可改）→ 唤出宠物窗口 + 触发"进程管家"拉起后端；
- 再按热键/超时无交互 → 隐藏窗口；可选"闲置 N 分钟后卸载 LLM"（llama-server 卸模型释放 6.8GB VRAM）。

### 2. 模型/API 选择 GUI（对应 airi 抽象 + ZcChat2 交互）
- 设置窗口三个区块：
  - **LLM**：本地（llama-server 模型列表，扫 `W:\model\` GGUF 目录 / 调 LM Studio `lms ls`）+ OpenAI 兼容 API（填 base_url/key/model，即 memory_router 已用的 openai_compatible_llm 路径）；
  - **ASR/TTS**：照 airi **unspeech** 思路，统一成 OpenAI 兼容端点选择（本地 sherpa-onnx / 外部 API），避免每接一个 provider 改代码；
  - **角色**：复用 open-llm-vtuber 已有的 `scan_config_alts_directory` + `switch-config` WebSocket 消息（websocket_handler.py:539-556）——**角色切换后端已存在，GUI 只是发消息**。
- 配置写回壳内 JSON，启动时注入环境变量（`LVA_LLM_URL` 等，config 层已支持 env 覆盖）。

### 3. Live2D 桌面显示（对应 persona-engine overlay）
- 现有 Open-LLM-VTuber-Web 前端以透明窗口加载；窗口属性：transparent、always_on_top、skip_taskbar、点击穿透（角色区域除外——前端报角色 hit 区，壳调 Win32  SetWindowRgn/动态切换 ignore_cursor_events）；
- lip-sync：沿用前端现有参数驱动；追求采样级口型时接 voice2 的 UDP 音频分接（playback.py:9-13 机制，OPTIMIZATION-REVIEW-v2 B4）。

### 4. 多角色同屏对话（后端已就绪，缺前端与编排）
- 后端：`chat_group.py` 入组 + `group_conversation.py` 轮流发言 + 广播已存在——多开 WebSocket 连接（每角色一个 client_uid + 各自 conf）即成组；
- 前端：stage 从"单模型画布"扩展为"多实例"，每角色一个 pixi Live2D 实例，按广播的 speaker uid 高亮/口型；
- 编排：角色间对话顺序/抢话规则需要新策略层（主持人 prompt 或 round-robin），这是唯一需要新写的后端逻辑（约 200-400 行）；
- 资源红线：多角色 ≠ 多模型——共享同一 llama-server（system prompt 区分人格）；每加一个 Live2D 实例 +~100MB RAM，VRAM 不变。

### 5. Live2D 形象自定义（对应 persona-engine 的自定义 avatar 机制 + ZcChat2 角色包）

- **导入管道**：设置 GUI 提供"导入形象"，接受标准 Live2D 模型目录（`.model3.json` + 贴图 + 物理/动作文件），校验后注册进角色配置（conf alts 目录，复用现有 `scan_config_alts_directory`）；
- **装配规范**：参照 persona-engine 的 `Live2D.md` 做法，定义本项目 rigging 约定——唇形参数（MouthOpenY 或 VBridger 参数集）、表情/动作组命名、hit 区域（头部/躯干，用于点击反应与拖拽）；导入时做参数体检，缺参数降级为"仅口型"模式并明确提示；
- **口型映射**：文本估算（现状）→ 音量包络（voice2 UDP tap）→ VBridger 全参数，三档按模型装配完整度自动降级；
- **角色包格式**：照 ZcChat2 的"一键导入"思路，形象 + 人格 prompt + 音色配置打成一个 zip 角色包，可分享、可导入——这也为 P4 多角色备好分发格式。

### 6. 音色训练为指定声音（GPT-SoVITS 为主路线，已核 README 事实）

| 候选 | 已核事实 | 判决 |
|---|---|---|
| **GPT-SoVITS** | zero-shot **5 秒**样本即克隆；few-shot **1 分钟**微调更佳；完整支持中文/跨语言；有 `api.py`/`api_v2.py` 服务；RTF 0.028（4060Ti 级）合成极快；Windows 整合包一键部署 | ✅ 主路线 |
| CosyVoice / index-tts / fish-speech | 参考清单 A/B 级，未逐核源码 | 备选 benchmark，不先行 |
| 现状 MeloTTS（CPU sherpa-onnx） | 644ms/句，预算内 | 保留为默认与 fallback |

**接入方式（关键设计）**：不把 SoVITS 编进任何进程——它作为独立 HTTP 服务，用 airi/unspeech + Orpheus-FastAPI 的 adapter 模式包成 **OpenAI 兼容 `/v1/audio/speech` 端点**。open-llm-vtuber 的 TTS provider 与设置 GUI 都只看到"又一个端点"，切换音色 = 切换端点/参数。

**8GB 显存争用策略（本机硬约束，llama-server 常驻已占 6.8/8.2GB）**：
1. **按需加载**（推荐，与壳的进程管家一致）：选中克隆音色时才拉起 SoVITS 服务，拉起前先令 llama-server 卸模型腾 VRAM（此时 LLM 走 OpenAI 兼容外部 API，或接受 LLM 冷启延迟）；
2. **fp16 + 小 batch 常驻**：SoVITS 推理 RTF 0.028 意味着可用"用时加载、句间卸载"，但频繁装卸有秒级成本，适合低频克隆音色场景；
3. **训练不在本机常驻**：1 分钟微调用整合包 WebUI 手动完成（一次性事件），训练产物（参考音频 + 微调权重）注册进角色包；推理才进运行时链路。
- 验收口径：克隆音色场景的 TTFA 单独测、单独写预算，不与 MeloTTS 的 800ms 混用同一数字（吸取上轮 budget 口径混乱教训）。

## 四、分期与验收标准（更新）

| 期 | 内容 | 验收 |
|---|---|---|
| P1 壳 | Tauri 托盘 + 热键唤出透明窗口 + 加载现有前端 + 进程管家启停三服务 | 常驻 ≤30MB；热键→可对话 ≤3s（后端热）/ ≤15s（冷启 LLM）；闲置卸载 VRAM 回落 |
| P2 设置 | 模型/API/角色三区块 GUI；unspeech 式 ASR/TTS 端点抽象 | 切换 LLM 模型不断连；API key 不落地明文（DPAPI） |
| P2.5 形象 | 形象导入管道 + rigging 体检 + 口型三档降级 | 导入自定义 model3.json 可显示、可动、口型有；缺参数有明确降级提示 |
| P2.5 音色 | SoVITS 整合包部署 + OpenAI 兼容 adapter + 克隆音色注册 | 5 秒样本克隆音色可对话；VRAM 不超 8.2GB 红线；克隆音色 TTFA 单独入证据 |
| P3 桌面感 | 点击穿透、拖拽、闲置动画、开机自启 | 穿透不挡操作；资源画像进 acceptance 证据链 |
| P4 多角色 | 角色包格式 + 多 Live2D 实例 + group 编排策略层 | 双角色互聊 10 轮无串话；每角色可有独立形象与音色；VRAM 不随角色数增长 |

## 五、风险与注意

1. **Cubism 许可**：走 Web 渲染（pixi-live2d-display 系）只涉及 Live2D Cubism Core 的 Web 版条款；若远期转原生 SDK（persona-engine 路线）需审商业许可——届时再议。
2. **WebView2 透明窗口**在部分显卡/远程桌面下有黑底坑（本机有 GameViewer 虚拟显示适配器，需实测）；兜底：非透明无边框窗口。
3. **热键冲突**：注册失败时降级为托盘点击 + 自定义改键。
4. **占用口径**：ZcChat2 的 8MB 是"纯壳待机"；本方案待机同样不含后端——验收时须区分"壳占用"与"全栈占用"两个数字写进证据，避免重蹈 TTS budget 那种口径混乱。
5. 语音链路优化（turn_id、早转写等，OPTIMIZATION-REVIEW-v2）与桌面化正交，建议并行不阻塞。
6. **声音版权**：音色克隆对象须为本人或已获授权的声音；角色包分享时不得夹带未授权音色权重——写进角色包格式的说明文件。
7. **SoVITS 流式未证实**：README 只见 `api.py/api_v2.py` 存在，流式输出能力未核实；若不支持流式，TTFA 会显著高于 MeloTTS，届时按"整句合成 + 句边界流水"保底，或转 benchmark CosyVoice/index-tts 的流式路线。

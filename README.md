# LocalVoiceAgent (LVA)

> **极低延迟、本地优先、支持 Live2D 交互与屏幕记忆的桌面 AI 语音伴侣系统**

LocalVoiceAgent 是一个全本地运行、集成了语音识别 (ASR)、大语言模型推理 (LLM)、语音合成 (TTS)、Live2D 动态交互以及屏幕/音频记忆检索 (Screenpipe) 的桌面智能伴侣。

---

## 🌟 核心特性

- **极致低延迟交互**：全链路本地推理优化，端到端打断与响应时延低至 ~238ms，支持物理断音打断。
- **轻量桌面壳 (`lva-pet`)**：基于 **Tauri v2 + WebView2** 构建，支持透明通道背景、全身 Live2D 渲染、鼠标无级滚轮缩放与自由拖拽。
- **零显存待机 (深度休眠)**：支持一键休眠，休眠态主进程内存仅 **~1.05 MB**，WebView2 树彻底销毁释放显存；按 `Alt+V` 或托盘即刻秒级唤醒。
- **本地 LLM 引擎管理**：深度集成 `llama-server` (CUDA 12 加速)，开机自动拉起，支持在图形面板中对本地 GGUF 模型进行一键热切换与持久化存储。
- **被动记忆流集成**：集成 Screenpipe 被动记录与向量/FTS5 混合检索，支持对屏幕操作与日常记忆的上下文感知问答。
- **双模与多音色**：内置本地离线 SenseVoice / MeloTTS，兼容 OpenAI 兼容端点及多样化角色人格配置。

---

## 🏗️ 架构布局 (Monorepo)

```
LocalVoiceAgent/
├── apps/
│   ├── desktop-shell/       # Tauri v2 桌面壳工程 (Rust + Win32 原生调用)
│   ├── open-llm-vtuber/     # Live2D 伴侣后端与前端服务 (FastAPI + WebSocket)
│   └── screenpipe/          # 屏幕与音频上下文捕获服务
├── scripts/                 # 服务启动、冷启动测试、基准测量与验收脚本
├── src/                     # 核心 Python 工具包与服务抽象
├── docs/                    # 架构规范与阶段设计文档
├── benchmarks/              # 延迟、打断与显存占用测试用例
├── acceptance-20260917/     # 验收快照、证据文件与终审报告
├── services.json            # 本地微服务进程监督配置文件
└── settings.json            # 用户偏好与系统设置
```

---

## 🚀 快速开始

### 1. 环境要求
- **操作系统**：Windows 10 / 11 (x64)
- **运行环境**：Python 3.10+、Rust 1.75+ (Cargo)、Node.js 18+
- **硬件推荐**：支持 CUDA 12 的 NVIDIA 独立显卡 (建议 6GB+ 显存)

### 2. 构建与运行
```powershell
# 启动桌面壳工程
cd apps/desktop-shell/src-tauri
cargo run --release

# 或者直接运行编译好的二进制
.\lva-pet.exe
```

### 3. 核心快捷键
- **`Alt+V`** 或 **`Ctrl+Shift+Space`**：即时显示 / 深度休眠桌面伴侣（常驻 1.05MB 待机）
- **托盘菜单**：右键系统托盘图标，可进行「选择/切换 LLM 模型」、「服务状态检测」、「释放显存」、「打开设置」与「退出（关闭全部进程）」

---

## 📄 License

MIT License

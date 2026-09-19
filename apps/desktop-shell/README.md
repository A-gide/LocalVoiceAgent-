# LocalVoiceAgent Desktop Shell (`lva-pet`)

桌面端宠物与常驻托盘壳工程，基于 Tauri v2 + Win32 原生 API 构建。

## 构建与打包指南 (Build & Packaging Guide)

### 1. 开发与 Release 构建

```powershell
# 进入源码目录
cd apps/desktop-shell/src-tauri

# 调试模式快速构建
cargo check
cargo build

# Release 生产级优化构建 (启用 LTO 与代码精简，二进制仅 ~5.67 MB)
cargo build --release
```

### 2. NSIS 安装包构建与离线工具链说明 (NSIS Toolchain Reproducibility)

在 Windows 环境下，Tauri 默认会从 GitHub Release 下载 `nsis-3.x.zip` 和 `nsis_tauri_utils.dll`。在内网或受限网络环境中，构建工具可能遇到下载超时。为确保构建完全可复现，请遵循以下离线缓存布局：

1. **NSIS 编译器目录**：
   - 目标路径：`%LOCALAPPDATA%\tauri\NSIS` (例如 `C:\Users\<username>\AppData\Local\tauri\NSIS`)
   - 包含文件：`makensis.exe`, `nsisconf.nsh`, `Bin/`, `Plugins/`, `Include/` 等标准 NSIS 3.11 解压内容。

2. **Tauri 专用插件** (`nsis_tauri_utils.dll`)：
   - 必须放置在 Unicode 插件附加目录：
     `%LOCALAPPDATA%\tauri\NSIS\Plugins\x86-unicode\additional\nsis_tauri_utils.dll`

3. **执行打包指令**：
   ```powershell
   cd apps/desktop-shell
   $env:PATH = "C:\Users\<username>\.cargo\bin;E:\AI\LocalVoiceAgent\tools\w64devkit\bin;" + $env:PATH
   npx @tauri-apps/cli build --bundles nsis
   ```

4. **构建产物位置**：
   - Release 二进制：`src-tauri/target/release/lva-pet.exe` (~5.67 MB)
   - NSIS 安装包：`src-tauri/target/release/bundle/nsis/lva-pet_0.1.0_x64-setup.exe` (~1.78 MB)

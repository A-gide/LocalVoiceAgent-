# DESKTOP-SHELL-P3-PLAN-REVIEW — P3 打包分发计划评审
- 评审时间：2026-09-18 20:2x
- 评审方：Claude（独立评审）
- 结论：**批准执行，附 2 必须（M1-M2）+ 3 建议（S1-S3）**

## 一、评审方 5 条前置条件覆盖核查

| 前置条件 | 计划覆盖 | 判定 |
|---|---|---|
| ①Release 全量重测入证，禁沿用 Debug 数字 | §4 bench_desktop_shell.py --target release + desktop_shell_release 独立节 | ✅ |
| ②安装/卸载不触碰 Adopted 服务、不打包模型 | §IMPORTANT-2 边界铁律 + hooks.nsh 仅清注册表 | ✅ |
| ③自启默认关、可逆、卸载清理 | autostart.rs + HKCU Run 键 + NSIS_HOOK_PREUNINSTALL DeleteRegValue | ✅ |
| ④WebView2 Runtime 缺失引导 | tauri.conf.json webviewInstallMode downloadBootstrapper | ✅ |
| ⑤硬编码路径解除 | paths.rs 四级优先级解析 | ⚠️ 有缺陷，见 M1 |

## 二、必须修复项

### M1：paths.rs 优先级顺序在标准安装场景下必然命中错误分支
计划中的优先级：①LVA_ROOT 环境变量 → ②可执行文件目录（便携模式）→ ③源码根回溯 → ④%APPDATA%。
缺陷：NSIS 标准安装将 exe 置于 `C:\Program Files\lva-pet\`，该目录**普通用户不可写**。优先级 2 会先于优先级 4 命中，导致 settings.json/services.json 回写 Program Files 失败（或触发 UAC），M3 的事务回写机制在标准安装下直接失效。
要求：
- 优先级 2（便携模式）必须附加**可写性探测**或**配置标记文件存在性**条件（如 exe 同级已存在 services.json/settings.json 才认定为便携模式）；不可写或无标记时落至优先级 4。
- services.json 属于"服务拉起规格"（只读为主、热切换时回写），settings.json 属于"用户配置"（高频写）——两者在标准安装下都应落 %APPDATA%；便携模式才跟随 exe。
- 验收追加：用 NSIS 安装包默认路径真实安装后启动，断言 settings.json 落 %APPDATA%\LocalVoiceAgent 且 Program Files 安装目录零写入。

### M2：`panic = "abort"` 与 Spawned 子进程清理冲突
[profile.release] 中 panic="abort" 会使 panic 时进程立即终止、**不运行任何 Drop/清理路径**——safe_shutdown_spawned_only 依赖正常退出路径执行。壳在 Spawned 状态下若 panic abort，llama-server 子进程变孤儿驻留（7GB 显存无人回收），直接违反 P1 建立的纳管安全验收线（退出后既有服务状态符合所有权语义）。
要求：二选一——
- 移除 panic="abort"（保留默认 unwind，二进制体积代价约几百 KB，可接受）；或
- 保留 abort 但注册 panic hook，在 abort 前同步杀掉全部 Spawned 子进程，并在 P3 验收中加入"panic 注入 → 孤儿进程检测"测试项。
推荐前者，简单且无新测试面。

## 三、建议项

- **S1 自启实现**：建议使用官方 `tauri-plugin-autostart` 而非自写 advapi32 FFI——功能等价、久经测试、少一块自维护 FFI 代码；若坚持自写，须在验收中覆盖"exe 路径含空格/中文时注册表键值加引号"用例。
- **S2 安装包签名**：未签名 NSIS 安装器必触发 SmartScreen 警告。当前阶段可接受（自用分发），但须在计划/文档中显式声明为已知限制，避免验收时被当作缺陷。
- **S3 downloadBootstrapper 需联网**：webviewInstallMode=downloadBootstrapper 安装时需联网下载 WebView2。Win11 自带 Runtime 属多数情况，但建议在 hooks.nsh 或安装前页检测 GUID {F3017226-FE2A-4295-8BDF-00C3A9A7E4C5} 已存在时跳过下载，离线机器友好。

## 四、确认无误的设计点
- 四级路径解析消除双轨的思路正确（仅优先级顺序需 M1 修正）。
- 边界铁律（零外部进程杀伤、模型不入包、安装器几十 MB 级）措辞与机制均到位。
- Release profile 除 panic 外配置合理（opt-level=3 / lto / codegen-units=1 / strip）。
- bench --target release + 独立 evidence 节 + 自启可逆性自动化断言 + pytest 13/13 零回归门槛，验收闭环完整。

## 五、批准后的实施顺序建议
1. M1 paths.rs（含可写性探测）→ 2. M2 panic 策略修正 → 3. autostart + 设置面板开关 → 4. NSIS 工程 + hooks.nsh → 5. Release 构建 + 全量重测入证 → 6. 真实安装验收（默认路径安装→路径落点断言→卸载→注册表/文件零残留断言）。

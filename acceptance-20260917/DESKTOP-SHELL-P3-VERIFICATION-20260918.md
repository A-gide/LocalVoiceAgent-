# DESKTOP-SHELL-P3-VERIFICATION — P3 交付终审报告
- 评审时间：2026-09-18 21:1x
- 评审方：Claude（独立评审）
- 结论：**功能交付实质成立，但证据完整性 2 项违反，暂不予关闭**。修复量小（预计 <30 分钟），修复后无需重跑全量基准即可关闭。

## 一、独立抽查属实项（7 项）

| # | 抽查项 | 独立证据 |
|---|---|---|
| 1 | Git 双 repo Clean | desktop-shell / open-llm-vtuber `status --short` 均空 |
| 2 | 产物实物 | release\lva-pet.exe 5.67MB（21:03:35）、nsis\lva-pet_0.1.0_x64-setup.exe 1.78MB（21:03:35），体积声明属实 |
| 3 | M1 路径解析 | paths.rs:6 `is_directory_writable` 可写性探测、:55 便携模式需标记+可写+非 target 目录、:73-74 %APPDATA% 兜底——评审 M1 要求完整落实 |
| 4 | M2 panic 安全 | Cargo.toml 全文无 `panic=`（abort 已移除，默认 unwind）；lib.rs:119-121 `std::panic::set_hook` 内调 `safe_shutdown_spawned_only()`——评审 M2 双重要求均落实 |
| 5 | pytest 零回归 | 评审方独立裸跑：**13 passed in 32.54s** |
| 6 | 安装边界实测 | 卸载后外部服务存活声明与现状一致（3030/12393 端口在线，llama PID 25560 在运行） |
| 7 | 构建配置 | Release profile opt-level=3/lto/codegen-units=1/strip 与证据节声明一致 |

## 二、不予关闭项（2 项 P1 + 2 项 P2/P3）

### P1-A：Debug 历史证据节被 Release 数字覆盖（证据不可变性违反，本项目第 4 次同类）
`desktop-shell-evidence.json` 的 `desktop_shell.p1_closure_dormancy_standby` 节标注为 "Debug Historical"（binary 指向 target\**debug**），但数值已被 Release 数据改写：standby 0.74MB（原 1.05）、rebuild 29.6/51.6ms（原 48.3/71.5）、post_dormancy 10.04（原 13.34）、active_tree 430.74（原 547.56）。**原 Debug 历史值在证据文件中已荡然无存**——而 P3 关闭报告对比表仍在引用 "Debug 阶段历史值 1.05MB/48.3ms"，这些数字现已无任何证据源支撑。
要求：恢复该节为 P2 关闭时的真实 Debug 值（评审方存档可核对：standby 1.05/1.05MB、rebuild 48.3/71.5ms、post_dormancy 13.34MB、active_tree 547.56MB）；Release 数据只准写入 `desktop_shell_release` 节。**历史节只增不改，这是底线。**

### P1-B：`active_dialogue_verified` 从 true 翻转为 false，verdict 仍为 PASS
P2 关闭时 `engine_character_switching_m1.active_dialogue_verified = true`；当前证据文件同字段 = **false**，而 verdict 仍是 "PASS"，文档（P3 关闭报告 §2 M1 行）仍宣称 "WebSocket 英语问答连通 PASS"。两种可能：P3 基准重跑了该项且对话验证失败（则 verdict 应改 FAIL 并说明），或字段被无意重置（则属证据失真）。无论哪种，verdict 与证据自相矛盾。
要求：重跑角色切换+活跃对话验证，按真实结果修正证据与文档。

### P2-C：打断时延 650.29ms 为单样本且贴近预算
Release 打断全链路 650.29ms，达预算（≤800ms）的 81%，较 Debug 的 235.69ms 劣化 2.76 倍。单样本、无 N、无波动说明。虽然判 PASS 合规，但若是 Release 构建引入的系统性劣化则需关注（理论上壳构建不影响服务端管线，更可能是测量时系统负载）。
要求：N=3 复测取中位数入证；若稳定 >600ms 需注明归因。

### P3-D：构建锚点与 HEAD 不一致（需在文档显式注明）
产物构建于 21:03:35，源码为 5c2f846；HEAD 于 21:03:43 移至 1d8adf5（paths.rs 最终兜底 `E:\AI\LocalVoiceAgent` 硬编码 → `current_dir()`，1 行）。** shipped 二进制内含硬编码兜底路径**（仅在 LVA_ROOT 未设、非便携、未找到源码树、%APPDATA% 未设时触发——Windows 上几乎不可达，残余风险低但存在）。
要求：二选一——用 HEAD 重新构建产物并更新证据；或在关闭文档显式注明"产物构建自 5c2f846，HEAD 含未入产物的 1 行兜底加固，触发条件与残余风险如上"。

## 三、流程备注（不阻塞，须记录）
NSIS 工具链非 `tauri build` 自动下载成功：执行方手动经 ghfast.top 镜像下载 nsis-3.11.zip 解压至 `%LOCALAPPDATA%\tauri\NSIS`，并手工将 `nsis-output.exe` 复制命名为 `lva-pet_0.1.0_x64-setup.exe`。产物功能实测正常（安装/卸载/边界均过），但**构建可复现性受损**——换机或重装环境后 `npx tauri build --bundles nsis` 可能再次卡在网络下载。建议将 NSIS 缓存目录与手工步骤写入构建 README。

## 四、关闭路径
修复 P1-A（恢复 Debug 历史节）+ P1-B（重跑角色对话验证并按实修正）+ P2-C（N=3 复测）+ P3-D（注明或重打包）后，评审方仅复核证据文件 diff 与新增测量值，无需全量重跑，即可关闭 P3。

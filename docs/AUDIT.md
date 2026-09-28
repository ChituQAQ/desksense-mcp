# DeskSense 审计与修复记录

## 2026-09-28：本机部署审计

审计基线：`3bc80b6`。以下为本机检查结果，不代表其他安装环境；不记录 token、tunnel 凭据、窗口标题或真实公网域名。

### 已确认的部署状态

- `DeskSense MCP` 登录计划任务已启用，最近一次运行退出码为 `1`；没有发现 DeskSense 进程。
- 配置端口 `127.0.0.1:8765` 被 `xhs-emoji-exporter` 占用，`/healthz` 和 `/mcp` 均返回 404。
- 共享 Named Tunnel 仍就绪，DeskSense hostname 的 ingress 仍指向 8765，存在误转发其他应用的风险；该 tunnel 还承载另一条业务路由，不能直接整体停用。
- token 与历史数据库继承了普通用户读取、Authenticated Users 修改权限，未形成仅当前用户的隐私边界。
- 任务无失败重试；隐藏启动器未保存 stderr，Task Scheduler Operational 历史未开启。无法据此还原最近一次异常退出原因，不能将其直接归因于当前端口冲突。

### 代码发现

| 优先级 | 发现 | 位置 | 验证 |
| --- | --- | --- | --- |
| 高 | Windows token/数据库 ACL 过宽 | `src/desksense/bootstrap.py`、安装脚本 | 实际 ACL 检查 |
| 中 | 启动脚本将任何端口监听者当作 DeskSense | `scripts/start.ps1` | 源码和实际端口归属 |
| 中 | 自启无失败重试、缺少 stderr | `scripts/install-autostart.ps1`、`scripts/run-desksense-hidden.vbs` | 实际任务和源码 |
| 中 | 旧 tunnel 启动脚本固定检查 20242，但本机 metrics 使用 20241 | `scripts/start-named-tunnel.ps1` | 实际监听端口 |
| 中 | UWP 回调参数数目错误 | `src/desksense/windows_focus.py` | 隔离复现、旧日志 |
| 中 | CPU 两次采样使用不同 Process 实例，失去采样基线 | `src/desksense/system_info.py` | 模拟繁忙进程仍返回 0% |
| 中 | GetTickCount 有符号返回值导致长开机后闲置误判 | `src/desksense/windows_idle.py` | 模拟 120 秒闲置返回 0 |
| 中 | ASGI 关闭后监控线程仍存活，SQLite 连接缺少关闭机制 | `src/desksense/server.py`、`src/desksense/focus_history.py` | 隔离生命周期验证 |
| 中 | 近期历史不包含在查询窗口之前开始、仍持续的事件 | `src/desksense/focus_history.py` | 隔离 SQL 复现 |
| 中 | 迁移导出全部 tunnel JSON，导入任取最后一个并重写共享路由 | `scripts/export-move.ps1`、`scripts/install-move.ps1` | 静态审查，未执行迁移 |

### 基线验证

- Python 22 个文件语法检查、PowerShell 5.1 12 个脚本语法检查、`pip check` 通过。
- pytest：30 通过、5 失败；5 个失败均为本机缺少 `pytest-asyncio`。直接异步补验这 5 个原测试函数通过，但标准 pytest 仍未全绿。
- 隔离 ASGI：health 200、未认证 MCP 401、initialize 成功。
- Git 跟踪文件和现有两份正式 Release ZIP 未包含检查范围内的运行配置、token、数据库、日志路径。
- 首次审计未修改代码、系统配置或现有进程。

## 已批准的本轮修复范围（2026-09-28）

用户批准先修复运行链路和隐私边界；不混入感知功能、迁移流程或其他项目的修复。

- [x] 为本机 DeskSense 选择独立空闲端口，保留现有配置其他字段。
- [x] 同步 DeskSense tunnel ingress；保留共享 tunnel 的另一条路由。若切换需要中断现有连接，先确认影响。
- [x] 修正启动身份/健康检查、隐藏启动 stderr、自启失败重试。
- [x] 收紧 `.secrets`、`data` ACL，并覆盖新安装，拒绝跟随重解析点操作其他目录。
- [x] 添加针对性回归测试，完成实际任务、进程、health、401、MCP 验证。

约束：不停止 `xhs-emoji-exporter`，不输出或轮换 token，不修改其他业务路由，不自动重启/注销 Windows。真实下次登录触发需与手动启动任务验证区分。

### 当前进展

- 2026-09-28：从用户指定的上一段会话恢复，已核对工作区：`start.ps1`、隐藏启动器、自启脚本和 ACL 脚本仅部分完成，尚未部署；开发测试依赖已补齐，待重跑测试。
- 2026-09-28：再次实测 18765 空闲，8765 仍由原业务进程占用，DeskSense 未运行；共享隧道仍使用旧 ingress。
- 已确认延续上一轮批准：使用 18765；共享隧道先启动并验证新 connector，再停止旧 connector，保留另一条路由，已有长连接可能短暂断开。
- 2026-09-28：补齐安装器 ACL 接入和任务重试、旧 tunnel 启动器按 config 识别进程，更新中英文说明；新增 11 项回归。标准 pytest 46/46、Python 23 文件语法、PowerShell 5.1 13 脚本语法、`pip check` 通过。测试子进程隔离了宿主继承的 PS7 模块路径（未修改宿主配置）。
- 2026-09-28：本机已切到 18765，`.secrets`/`data` 实际 ACL 验证仅 3 个预期主体，token 未改变。通过手动触发 `DeskSense MCP` 计划任务启动，local health、401、CORS、initialize、7 tools、`pc_get_context` 全通过。原 8765 进程 PID 25916 未变；真实下次登录触发仍未验证。
- 2026-09-28：首次受控异常退出未自动恢复：PS5.1 `Start-Process` 丢失退出码，任务误记成功。新增真实子进程用例先复现失败，再通过保留 Process.Handle 和空退出码失败兜底修复；pytest 47/47。正在重新验证真实任务重试，隧道尚未切换。
- 2026-09-28：重启不触发根因定位（一次性探针任务矩阵 + Task Scheduler 事件日志）：手动启动与触发器启动、最小设置与生产设置、Interactive 与 S4U 主体下，"动作正常退出但返回非零码"均不触发 RestartCount 重启；事件 102 将该实例记为"成功完成"（返回码 0x80070001）。此前三次重启验证失败的真因即此，与启动器退出码传播无关（后者已另行修复并验证）。
- 2026-09-28：自启重试改为启动器内置监督：`start.ps1` 在 `-Wait` 模式下对自身启动的（及被监控的既有）服务异常退出执行任务内重试，60 秒间隔、最多 3 次，耗尽后以归一化退出码结束任务；非 `-Wait` 一次性启动保持快速失败。计划任务 RestartCount 保留，覆盖"操作无法启动"类失败。pytest 49/49（新增 2 个监督用例、替换 1 个依赖调度器语义的用例）；PowerShell 5.1 语法、Python 23 文件语法、`pip check` 通过。
- 2026-09-28：修复两处测试对 pytest 宿主环境的编码依赖（宿主 `PYTHONUTF8=1` 时 PowerShell 子进程的 GBK 本地化输出导致 UTF-8 解码崩溃），改为显式 utf-8 + replace 解码，测试结论不再随宿主环境漂移。
- 2026-09-28：实机验证通过：新版启动器经计划任务拉起服务；受控强杀服务进程后 66.8 秒自动恢复（新 PID，任务保持 Running），`startup.log` 记录 "Retrying in 60 seconds"；本地 health、401、CORS、initialize、7 tools、`pc_get_context` 再次全通过。真实下次登录触发仍未验证（约束不注销）。
- 2026-09-28：共享隧道切换完成：config.yml 仅将 DeskSense ingress 由 8765 改为 18765（备份 `config.yml.bak-20260928`）；新 connector 以相同 tunnel 与新配置启动，注册 4 条 http2 连接（`/ready` 200，首次握手曾被边缘瞬时重置后重试成功）后停止运行 6 天的旧 connector；公网 DeskSense hostname `healthz` OK、未认证 `/mcp` 401；另一条业务路由 ingress 与 origin 进程（PID 未变）不受影响。边缘侧新旧 connector 短暂并存属既定方案。
- 2026-09-28：Task Scheduler Operational 历史日志已开启，修复审计中"历史未开启"的诊断盲区。

## 2026-09-28：11:00 之后改动的代码复审

范围：以本机 UTC+8 理解时间。所有分支在此时间之后均无新提交，HEAD 仍为 `3bc80b6`；按工作区文件修改时间，重点审查 `scripts/start.ps1`、两个相关测试文件、README 和本记录，并核对安装/停止链路。没有 11:00 的 Git 快照，无法严格逐行区分此前与此后的未提交修改。此前审计记录不是本次独立验证的替代证据。

### 新确认的问题（待修复，均为 P2）

1. **显式停止会被自动重试撤销**：`scripts/start.ps1:131-156` 将非零退出统一重试，但 `scripts/stop.ps1:25` 正是用 `Stop-Process -Force` 停止服务，没有通知/停止监督器。通过完整 start/stop 脚本加模拟进程的隔离探针，确认执行 stop 后再次调用了启动逻辑；另用本次创建的一次性真实子进程确认强制停止的退出码为 `-1`。默认监督模式下，用户停止后约 60 秒会重新启动并继续感知；重试等待期间 stop 还会因无监听者而直接返回。应让显式停止先结束对应监督器或传递停止意图，并覆盖重试等待期。
2. **新增监督测试依赖本机真实服务**：`tests/test_startup_scripts.py:162-182` 的 `test_launcher_retries_after_server_death` 模拟了监听、进程和启动，却遗漏 `Invoke-RestMethod`。阻止未 mock HTTP 的隔离探针捕获到真实调用 `http://127.0.0.1:18765/healthz`，该原测试随即失败；没有本地服务的干净环境无法按预期通过。本机 49/49 不能证明测试已隔离。应补齐 HTTP mock，并防止单测访问真实端点/执行真实进程清理；完整冷环境 CI 本次未运行。
3. **自动恢复覆盖最近一次崩溃诊断**：`scripts/start.ps1:57-70` 只在监督器首次启动时轮转日志，同一监督器重试时重新使用 `Start-Process` 重定向同名文件，会截断日志。隔离目录中用两次真实子进程验证：首次 stderr 的故障标记在重试成功后从全部日志消失，`.previous` 仍是监督器启动前的旧输出。应逐次保留启动尝试的输出，或采用不会截断故障记录的日志策略，并增加跨重试的日志断言。

### 本次验证与下一步

- 标准回归：`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`，49 通过；运行时设置了 `PYTHONDONTWRITEBYTECODE=1`。第 2 项说明了此结果的环境依赖。
- Python 23 文件 AST 语法、Windows PowerShell 5.1 的 13 脚本语法、`pip check`、`git diff --check` 均通过。
- 附加探针仅使用临时目录、模拟 OS 接口及本次创建的一次性子进程；未终止部署服务、未改计划任务/配置/ACL/隧道，未读取真实 token 或焦点数据。未重跑公网 MCP、登录触发或正式发布包验证。
- 本次仅追加审查记录，未改实现与测试。建议下一步限定修复上述 3 项；验收需覆盖不依赖现有服务的回归、显式停止在重试间隔后仍保持停止、自动重试保留故障 stderr。

### 本次修复授权与进展

- 2026-09-28：用户确认按上述建议修复这 3 项。范围限定为启动/停止脚本、启动回归测试和相关文档；不混入旧审计中的感知/迁移问题，不改计划任务、运行配置或共享隧道，不终止当前部署服务。
- 实施方向：显式停止先结束本安装目录的专用启动器，再按本目录 venv 命令行识别并停止服务，覆盖重试等待期；每次启动尝试轮转 stdout/stderr；单测缺失的 OS/HTTP mock 默认失败，真实进程验收仅使用临时 Node 和随机空闲端口。
- 2026-09-28 19:50：接手核对发现测试已部分补齐，实现尚未同步；启动专项回归实际为 15 通过、4 失败（两种时机的日志保留、服务存在/重试等待两种停止场景）。沿用上述授权继续修复，不重做已完成的部署切换。
- 2026-09-28 20:28：三项 P2 修复已完成并验证（接手会话核对工作区后确认实现已同步）：`stop.ps1` 重写为先结束本安装目录的专用启动器（仅匹配 `-File <本目录>\start.ps1` 的宿主，排除 `-Command` 宿主与其他节点路径），再按本目录 venv 命令行停止服务并逐个复核 PID 归属，启动器停止失败即中止、不杀服务，重试等待期由启动器进程匹配覆盖；`start.ps1` 在每次启动尝试前把 stdout/stderr 轮转为 `.previous`，重试不再截断最近一次故障输出；启动回归测试统一加 OS/HTTP mock 守卫，未 mock 的系统调用立即以退出码 97 失败，不再依赖宿主是否有真实服务。pytest 54/54 通过；PowerShell 5.1 语法 13 脚本、Python 22 文件编译、`pip check`、`git diff --check` 通过。
- 2026-09-28 20:28：实机只读复核（未停止任何进程、未改任务/配置/ACL/隧道）：计划任务 Running 且为新启动链（wscript -> vbs -> powershell -File start.ps1 -Wait），RestartCount 3 / 间隔 1 分钟；127.0.0.1:18765 监听进程为 venv 转发器与解释器子进程（一对父子，此前疑似"双服务进程"系 Windows venv 正常结构，非僵尸）；`/healthz` 返回 200 且服务标识正确，未认证 `/mcp` 返回 401；`stop.ps1` 的启动器/服务识别模式与真实运行命令行逐条匹配（仅正则比对，未执行停止）；cloudflared 连接器在运行，DeskSense ingress 指向 18765，另一条业务路由指向未变，8765 仍由原业务进程占用。真实下次登录触发仍未验证（约束不注销）；UWP 回调、CPU 采样、闲置计时、焦点历史生命周期等感知类缺陷维持遗留记录，不在本轮范围。

## 2026-09-28：感知类缺陷修复（提交 f089e32 之后）

用户询问遗留两项的执行方式；登录自启验证需真实登录事件（不由代理执行重启/注销），感知缺陷经确认后按推荐范围执行：UWP 回调、CPU 采样、闲置计时、焦点历史生命周期与近期查询四类，迁移脚本（export-move/install-move）继续单独留待后续并需先定契约。

- 先写失败测试坐实缺陷：新增 `tests/test_windows_focus.py`、`tests/test_system_info.py`，扩展 `test_idle.py`、`test_focus_history.py`、`test_server_contract.py`，共 7 项新测试在未修复代码上全部失败（UWP 用例原样复现生产 stderr 中的 `TypeError: cb() takes 1 positional argument but 2 were given`）。
- 修复 `src/desksense/windows_focus.py`：`_resolve_uwp_from_children` 的枚举回调按 WNDENUMPROC 契约补上 `(hwnd, lparam)` 两参数。
- 修复 `src/desksense/system_info.py`：`get_top_processes` 保留 `process_iter` 给出的同一批 `psutil.Process` 实例完成两次采样，不再重建实例导致基线丢失、CPU 恒为 0。
- 修复 `src/desksense/windows_idle.py`：`GetTickCount.restype` 显式声明为 `DWORD`，差值按 32 位无符号回绕计算；输入落在两次读取之间的回绕竞争按 0 处理。
- 修复 `src/desksense/focus_history.py`：新增幂等 `close()`（停线程、结束未闭合事件、释放连接）；`query` 改为返回与时间窗口有交集的事件——除窗口内开始的事件外，还包括开始早于窗口但仍在持续或在窗口内才结束的事件（比审计发现的最小修复略宽：与窗口交叠但已结束的事件同样纳入，否则时间线缺少切换前上下文）。
- 修复 `src/desksense/server.py`：外层改为 Starlette 应用（`Mount("/")` 挂载 SDK app，CORS 与 Bearer 中间件层级不变），组合内层 SDK lifespan，ASGI 关闭后停监控线程并释放数据库连接；已用探针验证 `Mount("/")` 下 `/mcp`、`/healthz` 路径与 lifespan 顺序（内层先关、外层后清）。
- 回归：pytest 63/63（新增 9 项）；Python 25 文件编译、`pip check`、`git diff --check` 通过。
- 部署生效：强杀服务进程树（venv 转发器 + 解释器）后，`start.ps1` 监督器记录 `Server exited with code 1` 并在 62 秒后用新代码自动拉起（新解释器 PID，任务实例存活），`/healthz` 200、未认证 `/mcp` 401——自动恢复机制第二次实测通过。stderr 中的 UWP TypeError 预计不再新增（该错误仅在前台为 UWP 应用时触发，需随时间观察）。
- 仍未验证：真实下次登录自启触发（待用户重启/登录后核对任务历史与健康检查）；迁移脚本契约未定。

## 2026-09-28：迁移脚本契约重做（提交 e336aa2 之后）

用户确认两项契约决策：export 只导当前凭据；install 遇冲突默认拒绝、显式参数才非破坏性合并。迁移脚本是审计清单中最后一个遗留代码缺陷。

- 新增 `scripts/restore-tunnel-config.ps1`：凭据/配置恢复的独立可测单元。按 manifest 的 tunnel_id 精确匹配唯一凭据 JSON 并校验文件内 TunnelID；目标无 config.yml 时按 manifest 路由 + 404 兜底全新写入；目标 config.yml 属于**不同 tunnel** 时拒绝（一个 config.yml 只服务一条 tunnel，加 -MergeIngress 也拒绝）；属于**同一 tunnel** 时默认拒绝、`-MergeIngress` 才在 catch-all 之前追加缺失路由，已有行逐字节不动（缩进沿用目标文件现有列表项）；全部校验通过后才产生任何写操作；旧格式档案（manifest 无 routes）回退读档案内 config.yml 的第一条路由并告警。
- 重写 `scripts/export-move.ps1` 的 tunnel 部分：只导出 config.yml 引用的那一个凭据（校验 TunnelID 一致）+ 按 config.json 端口筛选的本节点 ingress 路由片段，写入 manifest（tunnel_id/credentials_file/routes）；不再打包 `~/.cloudflared` 下其他凭据 JSON，不再随包外发完整共享 config.yml；无 config.yml、无本地端口路由、凭据不匹配时拒绝导出。顺带修复既有 bug：源节点缺 `.secrets` 目录时 else 分支写未创建的目录导致导出崩溃；结尾补显式 `exit 0`，避免 git 原生命令退出码（如非仓库目录的 128）泄漏为本脚本退出码。
- 重做 `scripts/install-move.ps1`：凭据与配置恢复改调 restore-tunnel-config.ps1（新增 `-MergeIngress` 透传）；本地端口从迁移来的 config.json 读取，不再硬编码 8765；任务注册改为复用项目的 `install-autostart.ps1` 与 `install-tunnel-autostart.ps1`（与全新安装同一加固链路，含身份校验启动器与失败重试），服务启动改调 `start.ps1` 并检查退出码；删除了重复的旧式任务注册（Unregister + 无重试）与"取最后一个 JSON + 无条件重写 config"逻辑。
- 现代化 `scripts/install-tunnel-autostart.ps1`：与 install-autostart.ps1 同款（-Force 注册、AtLogOn 指定用户、StartWhenAvailable、RestartCount 3/1 分钟），不再先 Unregister 再重建。
- 更新 `docs/MIGRATE.md`：记录导出最小敏感集、四类导入行为（全新写入/异隧道拒绝/同隧道拒绝/显式合并）、旧档案回退与端口来源。
- 新增 `tests/test_move_scripts.py` 11 项契约测试（临时目录 + 假凭据，不触碰真实 `~/.cloudflared`，不输出凭据内容）：导出仅含被引用凭据与本地路由、三类导出拒绝；恢复的全新写入、TunnelID 校验、异隧道拒绝（含 -MergeIngress）、同隧道需显式合并、合并在 catch-all 前插入且幂等、旧档案回退、脚本间文本契约。测试过程暴露并修复了上述 `.secrets` 缺失崩溃与 git 退出码泄漏两个既有问题。
- 回归：pytest 74/74（新增 11 项）；PowerShell 5.1 语法 15 脚本、Python 28 文件编译、`pip check`、`git diff --check` 通过。
- 本轮未运行真实迁移（无第二台测试机）；恢复逻辑已按上述用例隔离验证。遗留：真实下次登录自启触发验证（待重启）；v1.0.2 发布与版本号提升；推送后跑冷环境 CI。

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

## 2026-09-28：推送与冷环境 CI

- 本地三个未推送提交与远端两个 README 网页编辑提交（C:\Apps→D:\Apps 示例路径，与本地改动无重叠）变基合并后推送（原哈希 f089e32/e336aa2/8d1159c → 04d284d/7ff5ff4/3468558），变基后 74/74 通过。
- 冷环境 CI 结果：四个 Python 矩阵（3.11–3.14）全绿；"PowerShell and clean-room ZIP" 失败于 `verify-install.py` 的断言 `unauthorized.headers["access-control-allow-origin"] == origin`。
- 根因是 server.py 生命周期重构引入的真实回归：Starlette `middleware=[...]` 列表第一项才是最外层，重构时误把 BearerAuthMiddleware 放在 CORSMiddleware 外层，未授权 401 在 CORS 之前短路，丢失 allow-origin/expose-headers 头（浏览器端 JS 将读不到 401）。本地 pytest 未抓到：test_cors.py 只断言了 OPTIONS 预检，未覆盖"未授权请求仍带 CORS 头"这一 verify-install.py 契约。
- 修复：调整中间件顺序（CORS 在外层包住 Bearer 守卫）；在 test_cors.py 新增回归测试 `test_unauthorized_mcp_keeps_cors_headers_for_allowed_origins`（先红后绿，覆盖配置 origin 与 localhost 正则 origin，断言 401 + allow-origin + expose-headers）。pytest 75/75。
- 教训记录：server.py 的 HTTP 层改动应同时对照 `scripts/verify-install.py` 的端到端契约；冷环境 CI 的洁净房安装验证是本地回归无法替代的一环。

## 2026-09-28：v1.0.2 发布

- 版本号 1.0.1 → 1.0.2 共 7 处（pyproject.toml、src/desksense/server.py、src/desksense/__init__.py、两份 README、两份 INSTALL 的 ZIP 文件名），提交 2fab287，pytest 75/75。
- `package-release.ps1` 打出 dist/DeskSense-v1.0.2.zip（62 个条目）；双重私密路径校验通过（.secrets/config.json/data/logs/.venv/token 均无）。
- 标签 v1.0.2 推送后 tag 触发的 Windows CI 通过；GitHub Release 已发布（双语说明沿用 v1.0.1 格式，附 DeskSense-v1.0.2.zip）：https://github.com/ChituQAQ/desksense-mcp/releases/tag/v1.0.2
- 至此本轮审计驱动的修复（启动链、隐私 ACL、18765 端口、感知缺陷、迁移契约、CORS 回归）全部收口为一个已发布版本。遗留仅剩：真实下次登录自启触发验证（待重启）、本机默认端口是否随发布调整（未决，当前发布默认仍为 8765）。

## 2026-09-29：对 2026-09-28 11:00 之后最新代码的复审

范围：按提交记录的 UTC+8，审查 `20a26d6..db32aac`，共 6 个提交、33 个变更文件；开始时位于 `main`，工作区干净。本次以当前源码、基线 diff 和独立验证为准，不以此前审计或发布记录代替验证。没有修改实现、测试或部署配置。

### 确认的问题（待授权修复，均为 P2）

1. **合并能把有效的共享隧道配置写成无效配置**（`scripts/restore-tunnel-config.ps1:115-124`）：只把 `- service: http_status:...` 当作 catch-all；合法的 HTTP/HTTPS 服务兜底未被识别，新增路由被追加到兜底之后。使用临时配置、假凭据及真实 `cloudflared tunnel --config <临时文件> ingress validate` 验证：合并前退出码 0，restore 返回 0，合并后校验退出码 1，报后续规则永远不能命中。重启 connector 时可能使共享隧道的其他业务一并不可用。建议按 hostname/path 缺省语义识别兜底，并在替换目标文件前验证完整候选配置；不能支持的结构应拒绝，不应写入。
2. **导出仍不兼容正式安装器的配置文件位置**（`scripts/export-move.ps1:82-85`；对照 `scripts/install.ps1:263`）：正式 Named Tunnel 安装写入 `<TunnelName>.yml`，导出只认 `~/.cloudflared/config.yml`，也没有指定配置路径的参数。按正式安装器的文件布局构造临时 Node，导出退出码 1、无 ZIP。建议明确选择本 Node 实际使用的配置，多个候选时拒绝猜选；回归应贯通正式安装布局与 MOVE 导出，而不仅使用手写 config.yml fixture。
3. **凭据解析不尊重实际引用路径**（`scripts/export-move.ps1:95-104`）：正则未处理 YAML 单引号，且对解析出的路径只保留 basename，再强制拼回 `~/.cloudflared`。两种隔离用例均失败：无空格的单引号路径被当作文件名尾部带 `'` 的路径（正式安装器在 `install.ps1:338` 恰好输出单引号）；配置引用外部目录内真实存在的凭据时，脚本却去 cloudflared 目录找同名文件。建议正确解析 YAML 标量及实际源路径，仅打包时使用安全文件名，保留 TunnelID 校验。
4. **导出路由丢失匹配条件和源站选项**（`scripts/export-move.ps1:122-127`；恢复只写 hostname/service，见 `scripts/restore-tunnel-config.ps1:127-131`）：输入含 `path: ^/mcp$` 和 `originRequest` 的合法路由时，导出成功，但 manifest 只剩 hostname/service；恢复后路径限制被扩大为整个 hostname，TLS、Host header 等源站选项也无法恢复。建议保留所选路由的完整语义及相关默认值，或者明确拒绝无法无损迁移的配置，不能静默丢弃。已用假配置确认 manifest 丢字段；未对真实域名发请求。
5. **生命周期异常路径仍泄漏监控线程和数据库连接**（`src/desksense/server.py:200-205`）：清理语句位于内层 lifespan 的正常退出之后，没有 `finally`。分别注入 SDK startup/shutdown 异常，退出后均为 `monitor_alive=True`、`db_open=True`、`stop_requested=False`；探针随后主动关闭了这些临时资源。在宿主进程仍存活的嵌入式/测试用法中，会继续采集并持有 SQLite；当前 CLI 整个进程退出时 OS 会回收资源，不能据此认定当前部署一直泄漏。建议将清理放入 `finally`，并覆盖内层启动失败和关闭失败。

### 验证与边界

- 本地环境：Python 3.14.6、mcp 2.0.0、Starlette 1.6.0、psutil 7.2.2。
- `PYTHONDONTWRITEBYTECODE=1 .venv/Scripts/python.exe -m pytest -q -p no:cacheprovider`：75/75 通过（29.14 秒）。现有测试未覆盖上述异常/配置变体；全绿不代表迁移契约完整。
- `pip check`、26 个 Git 跟踪 Python 文件 AST 检查、14 个 Git 跟踪 PowerShell 脚本的 Windows PowerShell 5.1 语法检查、范围 diff 的 `git diff --check` 通过。PowerShell 诊断包装首次输出遇终端编码错误，固定 UTF-8 输出后重新执行并确认退出码 0。
- 附加探针复用了 `tests/test_move_scripts.py` 的临时 fixture/helper；配置、凭据及数据库全部为本次生成的假数据。cloudflared 仅执行离线 ingress 校验；生命周期测试 mock 了桌面读取。临时文件已清理，未读取真实 token、焦点历史或隧道凭据，未修改 ACL、计划任务、运行配置，未终止真实服务。
- 经 Context7 核对 Cloudflare 官方配置文档：catch-all 可使用普通 HTTP/HTTPS 服务，规则按序匹配，缺少 path 表示匹配所有路径；Starlette 文档的生命周期清理语义与本次异常探针一致。
- 未执行真实迁移、交互式安装、真实登录触发、公网 MCP 验收，也未重新核验远端 CI 或发布附件。本次仅追加审查记录。
- 建议下一步优先修复迁移配置损坏/语义丢失，再修复导出兼容与生命周期异常清理；先补失败回归，修复后重跑全套及隔离 cloudflared 校验。范围尚未获实施授权。

### 2026-09-29：修复授权与进展

- 用户已确认保存审查记录、单独 git commit 后开始修复上述 5 类问题；审查记录已提交为 `fe96866`。本轮不修改运行配置、计划任务、ACL 或真实隧道，不停止现有服务，不执行交互式安装/迁移。
- 实施方案：保留 PowerShell 入口，增加 Python YAML 处理模块及显式 PyYAML 依赖；自动发现唯一匹配本地端口的配置，提供显式配置路径覆盖；正确读取凭据引用；完整保留所选路由及源站默认值。合并保留既有文件字节、检查兜底与冲突，无法无损支持时拒绝写入；生命周期清理放入 `finally`。先补失败测试，再实现与验证。
- 首轮进展：14 个新增失败用例已在旧实现复现；新增 `scripts/move-config.py`、`scripts/invoke-move-config.ps1`，迁移脚本改接 YAML helper，新增 PyYAML 依赖，生命周期清理已改为 `finally`。迁移与生命周期专项测试 27/27 通过（含本机真实 cloudflared 的离线 ingress 校验）；正在补复杂 YAML/拒绝写入边界，尚未完成全套验收。旧测试的双引号 Windows 路径 fixture 使用了 YAML 非法的未转义反斜杠，已改为等价的合法正斜杠路径。

### 本轮修复结果（2026-09-29）

- [x] 2026-09-29：按 hostname/path 语义识别最终兜底，支持 HTTP/HTTPS 服务；合并仅插入缺失路由，保留既有字节，并验证候选解析结果等于预期配置。缺少兜底、路由冲突、默认值不一致和可能遮蔽新路由的既有通配规则均拒绝；cloudflared 校验失败在任何目标隧道文件写入前退出。
- [x] 2026-09-29：导出自动发现本地端口唯一匹配的 `.yml`/`.yaml`，兼容正式安装器 `<TunnelName>.yml`；歧义时拒绝，支持 `-ConfigPath` 明确选择。
- [x] 2026-09-29：通过安全 YAML 解析获取凭据实际绝对路径，支持带引号、空格及外部目录；校验 TunnelID 后仅打包一个凭据。无法明确解析的相对引用拒绝猜测。
- [x] 2026-09-29：manifest 保留所选完整路由、嵌套选项和独立的源站默认值；恢复保留 path/originRequest。拒绝无法无损支持的 YAML 结构或外部 caPool 文件引用，且不再将完整 manifest 打印到控制台。兼容旧档案的告警回退保留。
- [x] 2026-09-29：SDK 生命周期清理改为 `finally: history.close()`，启动失败、关闭失败和上下文异常三条路径均验证监控线程停止、数据库连接释放。
- 最终回归：106/106 通过（比基线增加 31 项，最后一次 35.10 秒）；29 个 Python 文件内存编译、15 个 PowerShell 脚本 PS5.1 语法、`pip check`、`git diff --check` 均通过。合并测试以真实 cloudflared 对临时配置做离线校验；额外模拟 CLI 拒绝，确认目标目录/凭据不会被创建。
- 构建验证：首次额外尝试 `--no-build-isolation` 因本地 venv 无 setuptools 而失败；恢复项目默认构建隔离后，`pip install --no-deps -e .` 成功构建并安装 editable wheel，随后全套 106/106 再次通过。新增显式依赖 `PyYAML>=6.0.2,<7`，本地使用 6.0.3；未修改全局 Python 或宿主配置。
- `docs/MIGRATE.md` 已同步新参数、依赖更新命令、保留字段与安全限制。直接调用恢复脚本且无 cloudflared 时只做结构/语义检查并告警；完整安装流程传入已发现的 CLI，强制候选 ingress 离线校验。
- 用户确认继续，本轮实现、测试及审计进展纳入单独的修复提交；审查记录已独立提交为 `fe96866`。本次不推送、不发布。未修改真实运行配置、ACL、任务或隧道，未停止服务、读取真实凭据、执行交互式安装，也未运行真实迁移或生成发布 ZIP。剩余验收为推送后的多版本冷环境 CI、实际迁移和真实登录触发；当前服务未重启验证新生命周期代码。

### 2026-09-29：推送与 Windows 冷环境 CI 验证

- 用户授权推送并验证 Windows CI；已将 `fe96866`、`4265a06` 推送至 `origin/main`，无强推、无发布、无部署操作。
- 源码提交 `4265a062279c61d4b58de4405146a2665267c023` 的 [Windows CI run 36514586330](https://github.com/ChituQAQ/desksense-mcp/actions/runs/36514586330) 已完成，结论 `success`，5/5 jobs 通过。已核对 GitHub Actions 的 headSha、各 job/step 终态及运行日志，不以本地测试代替远端结果。
- Windows Python 矩阵：3.11 为 106 passed（50.95 秒）、3.12 为 106 passed（49.71 秒）、3.13 为 106 passed（66.47 秒）、3.14 为 106 passed（60.53 秒）。依赖安装、项目导入与测试均通过。
- `PowerShell and clean-room ZIP` 通过：PS5.1 全脚本解析、VBS 无 BOM、ZIP 私密路径检查、带空格的洁净目录安装，以及安装结束后端口无残留监听。安装日志确认 `Health status: OK`、`Tools verification: 7/7`；本轮无需追加实现修复。
- 本次仅推送源码与审计记录，未发布 Release、创建标签或操作真实部署。冷环境 CI 验证的是本地安装；真实 Node 迁移、当前服务重启后的验证、真实登录触发及公网 Named Tunnel 验收仍未执行。

## 2026-09-29：部署重启与 v1.0.2 生效验证

接手会话按上文遗留清单执行"当前服务重启后的验证"。重启前实测：监听进程（09-28 23:40:25 启动）经 MCP `initialize` 报告 `serverInfo` 为 **1.0.1**，落后于 HEAD（缺 `2fab287` 的版本号与 `4265a06` 的生命周期 `finally` 清理）；venv 为 editable 安装（`__editable__.desksense_mcp-1.0.2.pth`），重启即加载 `src` 当前代码。

### 新发现（待授权修复）：监督器重试预算不随稳定运行刷新

- 机制：`scripts/start.ps1:111` 的 `$RetriesLeft = $MaxRetries` 仅在监督器启动时初始化，失败递减、启动成功不重置；`-Wait` 模式下监督器实例整个登录周期存活。
- 实测经过：09-28 12:22 启动的监督器实例当日历经三次服务退出，23:39 用尽最后一次重试（日志 `0 retries left`）于 23:40:25 拉起服务并持续监控至今。09-29 11:18:09 为升级代码强杀服务进程树后，监督器于 11:18:10 立即记录 `Giving up after exhausting retries` 并退出——没有 60 秒等待，也没有任何实际重试；任务以退出码 1 结束（按已验证的调度器语义，"正常退出但非零码"不触发任务级重启），服务保持停止，直至 11:22:47 手动 `Start-ScheduledTask` 恢复。
- 影响：自动恢复的有效保证为"每个登录周期最多 3 次"，且预算会被登录早期的事故消耗；此后即使服务长期稳定运行，再崩溃也不会自动恢复，与 README "服务异常退出后……自动重试，最多 3 次"的直觉预期存在差距。可选修复方向：服务连续健康若干分钟后重置重试预算。本次仅记录，未实施。

### 重启结果与验收

- 恢复方式：手动启动 `DeskSense MCP` 计划任务；新监督器 11:22:47 拉起新解释器（PID 24836），约 5 秒内 `/healthz` 200。
- 本地验收（`scripts/verify-install.py`）：healthz 200、未认证 `/mcp` 401 且带 CORS 头、OPTIONS 预检 200、`initialize` 成功、`tools/list` 恰为 7 个工具、`pc_get_context` 调用成功；`serverInfo` = DeskSense MCP **1.0.2**。
- `logs/stderr.log` 自 09-28 23:40（感知缺陷修复部署）以来无新增 UWP `TypeError`（该错误仅在前台为 UWP 应用时触发，继续随时间观察）。

### 公网 Named Tunnel 验收受阻（环境性，非本次改动引起）

- cloudflared 连接器进程存活并按自身节奏持续重试，但本机到 Cloudflare 边缘 `198.41.x.x:7844` 的 TCP 连接全部 i/o timeout，`/ready` 报告 0 条连接；公网访问 DeskSense hostname 返回 530。
- 时间线：当日 08:01（UTC+8）起即出现间歇性拨号超时，最后一次成功注册边缘连接为 11:09:46，**早于** 11:18 的重启操作；重启仅涉及本机服务进程树，未触碰隧道。同网络下 `https://www.cloudflare.com` 返回 200、`1.1.1.1:443` 超时，判定为本网络到边缘端口的链路质量问题。已挂后台探测，边缘恢复后补做公网端到端验收。
- 边界：本轮未修改代码、运行配置、ACL、计划任务或隧道配置；未输出 token；公网 hostname 未写入本记录；未重启系统、未注销会话。

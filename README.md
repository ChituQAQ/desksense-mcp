[简体中文](README.md) | [English](README_EN.md)

# DeskSense

DeskSense 是一个面向 Windows 的只读 MCP 服务。它让 AI 助手在获得你的授权后，查询当前前台窗口、已打开应用、键鼠闲置时间、系统负载和近期焦点切换记录。它不会执行命令、操作窗口或远程控制电脑。

每台电脑运行一个独立的 DeskSense Node，通过 MCP Streamable HTTP 的 `/mcp` 端点提供数据，并使用 Bearer Token 鉴权。普通本地安装不需要 Cloudflare；只有需要稳定公网 URL 时，才需要可选的 Cloudflare Named Tunnel。

## 7 个 MCP 工具

DeskSense 精确提供以下 7 个只读工具：

- `pc_get_context`：当前前台应用、闲置状态、主要打开应用和系统概况
- `pc_get_focus`：当前前台窗口和进程
- `pc_list_open_apps`：可见桌面应用窗口列表
- `pc_get_idle_status`：键鼠闲置秒数和 active/idle/away 状态
- `pc_get_pc_status`：CPU、内存、磁盘、网络和开机时间
- `pc_get_top_processes`：按 CPU 或内存排序的进程列表
- `pc_get_recent_focus`：近期前台窗口切换记录

## 数据与隐私

DeskSense 只读取本机状态，但返回内容可能包含应用名、窗口标题、进程路径和系统指标。焦点历史保存在本机 `data\pc_sense.db`，日志保存在 `logs\`；Bearer Token 只保存在 `.secrets\API_KEY.txt`，不会写入代码或日志。

不要公开 token，不要提交 `.secrets`、`config.json`、`data` 或 `logs`。如果通过公网访问，请使用独立的 Named Tunnel hostname，并只向可信客户端开放浏览器 origin。

## 安装要求

- Windows 10 或更新版本
- Python 3.11、3.12、3.13 或 3.14（Windows CI 全部验证）
- 支持 Streamable HTTP 和 Bearer Token 的 MCP 客户端
- 仅 Named Tunnel 模式需要 Cloudflare 账户和 `cloudflared`

SullyOS 是经过测试的客户端示例，不是必需或专用客户端。

## 推荐安装：Release ZIP

普通用户无需 Git、pip 知识，也无需手工创建 venv、配置、token 或计划任务。

1. 打开 [GitHub Releases](https://github.com/ChituQAQ/desksense-mcp/releases)。
2. 下载 `DeskSense-v1.0.1.zip`。
3. 解压到不会被移动或删除的稳定目录，例如 `C:\Apps\DeskSense`。
4. 在解压目录打开 PowerShell，运行下面的一条命令。

Windows 的脚本执行策略或 ZIP 下载标记可能阻止直接运行 `.ps1`。推荐命令已经用 `-ExecutionPolicy Bypass` 仅为本次进程绕过限制，不会修改系统策略：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

### 默认：本地安装

上面的命令会自动完成正式依赖安装、`.venv`、token、`config.json`、登录自启动、服务启动和完整 MCP 验证。默认地址为：

```text
http://127.0.0.1:8765/mcp
```

本地安装不需要 Cloudflare、域名、DNS、`cloudflared` 或 Cloudflare 账户。

安装器不会打印 token，只会报告 token 文件路径。需要连接客户端时，在本机打开 `.secrets\API_KEY.txt`，把内容配置为 Bearer Token；不要把它粘贴到日志、issue 或聊天记录中。

可用 `-Port` 选择其他端口，范围为 1–65535：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Port 18765
```

### 可选：Cloudflare Named Tunnel

只有需要稳定公网 HTTPS URL 时才使用此模式。`-Hostname` 与 `-TunnelName` 必须同时提供：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

此模式才会查找 `cloudflared`、打开 Cloudflare 浏览器授权、创建或复用 Named Tunnel、创建 DNS route、写入实际 `-Port` 的 ingress、注册 tunnel 自启动并验证公网 MCP URL。前置条件和完整步骤见[中文安装指南](docs/INSTALL.md)。

## 连接 MCP 客户端

客户端需要两个值：

- MCP URL：本地为 `http://127.0.0.1:8765/mcp`；Named Tunnel 为 `https://desksense.example.com/mcp`
- Authorization：`Bearer <.secrets\API_KEY.txt 中的 token>`

具体字段名称取决于客户端。客户端必须支持 MCP Streamable HTTP 和自定义 Authorization header。

浏览器页面直接连接 DeskSense 时，浏览器会检查 CORS。`AllowedOrigin` 指的是网页自身的 origin（协议、主机、端口），不是 MCP URL。`localhost`、`127.0.0.1` 和 `::1` 的本机浏览器 origin 自动支持任意端口；远程网页必须显式配置精确 origin：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -AllowedOrigin https://client.example.com
```

Named Tunnel 安装时也可追加同一参数。不要把 `AllowedOrigin` 设置成 `*`。

## 多电脑 Node 模式

每台 Windows 电脑分别解压和安装一个 Node。各 Node 拥有独立 token、配置、数据和日志。本地使用时，每台电脑连接自己的本机 URL；使用 Named Tunnel 时，每台电脑使用不同的 hostname、tunnel 名称和 token。

已有 Node 的凭据迁移属于单独的敏感操作，见[迁移指南（英文）](docs/MIGRATE.md)。不要通过复制普通 Release ZIP 来迁移真实凭据。

## 自动启动与手动运行

默认安装会注册当前用户登录时启动的计划任务 `DeskSense MCP`。无窗口启动链为：

```text
Task Scheduler -> wscript.exe -> run-desksense-hidden.vbs -> python.exe -m desksense.server
```

桌面感知需要当前用户的交互会话，因此任务使用 `AtLogOn`，不以 SYSTEM 身份运行。

高级用户可传入 `-NoAutostart`：安装器仍完成环境、配置、token 和验证，但验证后关闭临时服务，不留下后台进程或永久计划任务。之后可手动运行 `.\scripts\start.ps1`。

## 验证

安装器会依次验证：

- `/healthz` 返回 200
- 未认证 `/mcp` 返回 401
- Bearer Token 可以完成 MCP `initialize`
- `tools/list` 精确返回 7 个工具
- `pc_get_context` 调用成功

手工检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

使用自定义端口时，`status.ps1` 会读取 `config.json`。

## 常见故障

- 找不到 Python：安装受支持的 64 位 Python，并确认 `py.exe` 或 `python.exe` 可用。
- 脚本被阻止：使用本文完整的 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...` 命令。
- 端口被占用：用 `-Port` 选择空闲端口；不要占用其他服务端口。
- 客户端收到 401：确认使用 `/mcp`，并以 `Bearer` 方式发送该 Node 的 token。
- 浏览器 CORS 失败：本机 origin 自动允许；远程网页用 `-AllowedOrigin` 配置精确 origin，不要填写完整页面路径。
- Named Tunnel 失败：确认账户已管理目标 DNS zone、`cloudflared` 已安装、浏览器授权成功，并确认 hostname 未被其他服务占用。
- 查看日志：检查 `logs\`，但不要分享 `.secrets\`。

## 开发者安装

开发者可从源码建立隔离环境：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest -q
```

普通用户请优先使用 Release ZIP 和安装器。

## License

DeskSense 使用 MIT License，见 [LICENSE](LICENSE)。

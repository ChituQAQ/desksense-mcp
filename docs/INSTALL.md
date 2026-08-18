[简体中文](INSTALL.md) | [English](INSTALL_EN.md)

# 安装 DeskSense Node

本文面向第一次安装 DeskSense 的 Windows 用户。推荐从 GitHub Release ZIP 安装；普通本地安装不需要 Cloudflare。

## 准备工作

所有模式都需要：

- Windows 10 或更新版本
- Python 3.11、3.12、3.13 或 3.14
- `DeskSense-v1.0.1.zip` 解压到稳定目录

在解压目录打开 PowerShell。下面所有命令都使用 `-ExecutionPolicy Bypass`，只绕过当前进程的脚本限制，不修改系统执行策略。

## 方式一：仅本地安装（默认）

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

不需要 Cloudflare 账户、域名、DNS、`cloudflared` 或 tunnel credentials。

安装器会：

1. 检查 Windows 和受支持的 Python。
2. 创建 `.venv`，安装正式依赖并执行 `pip install -e .`。
3. 创建 `.secrets\API_KEY.txt`；缺失时生成 64 位 hex token，已有合法 token 则保留。
4. 创建或更新 `config.json`，默认绑定 `127.0.0.1:8765`。
5. 注册当前用户登录任务 `DeskSense MCP`，通过 `wscript.exe` 和 VBS 无窗口启动。
6. 启动服务并验证 health、401、MCP initialize、精确 7 个工具和 `pc_get_context`。

成功后使用：

```text
MCP URL: http://127.0.0.1:8765/mcp
Token:   .secrets\API_KEY.txt
```

安装器只打印 token 文件路径，不打印 token 内容。

### 自定义端口

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 -Port 18765
```

端口必须在 1–65535 之间。确保所选端口未被占用。

### 不注册自动启动

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Port 18765 `
  -NoAutostart
```

此模式仍会完成环境、config、token 和端到端验证。安装器临时启动服务，验证后按精确 PID 关闭，不创建永久计划任务，也不留下后台进程。随后可用 `.\scripts\start.ps1` 手动启动。

### 浏览器客户端 origin

本机网页 origin `http://localhost:<任意端口>`、`http://127.0.0.1:<任意端口>` 和 `http://[::1]:<任意端口>` 自动允许。远程网页需要精确配置 origin：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -AllowedOrigin https://client.example.com
```

`AllowedOrigin` 是网页的协议、主机和可选端口，不能包含路径、查询参数、凭据或 fragment。不要使用 `*`。

## 方式二：Cloudflare Named Tunnel（可选）

只有需要稳定公网 HTTPS URL 时才选择此方式。

额外前置条件：

- Cloudflare 账户
- 已安装并可运行的 `cloudflared`
- 由该 Cloudflare 账户管理的 domain / DNS zone
- 能在浏览器完成 Cloudflare 授权
- 计划使用且未冲突的 hostname，例如 `desksense.example.com`

运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1 `
  -Hostname desksense.example.com `
  -TunnelName desksense
```

两个参数必须成对提供；只提供一个会在任何安装操作前失败。

在完成本地 bootstrap 后，Named Tunnel 模式会：

1. 查找 `cloudflared`。
2. 验证登录状态；需要时打开浏览器授权。
3. 创建或复用指定名称的 tunnel。
4. 确认该 tunnel 的 credentials JSON 存在。
5. 为 hostname 创建或更新 DNS route。
6. 写入 `~\.cloudflared\<TunnelName>.yml`，ingress 指向实际的 `127.0.0.1:<Port>`。
7. 注册 `DeskSense MCP` 和 `Cloudflared Named Tunnel` 两个当前用户登录任务。
8. 同时验证本地和公网 MCP 端点。

成功后的 MCP URL 为：

```text
https://desksense.example.com/mcp
```

可附加 `-AllowedOrigin https://client.example.com`。Named Tunnel 的公网 hostname origin 本身也会加入精确 allowlist。

`-NoAutostart` 同样适用：验证期间临时启动本地 server 和所需 tunnel connector，结束后只关闭安装器创建的临时进程，不注册永久任务。

## 自动启动结构

本地服务：

```text
Task Scheduler (AtLogOn, current interactive user)
  -> wscript.exe
  -> scripts\run-desksense-hidden.vbs
  -> .venv\Scripts\python.exe -m desksense.server
```

Named Tunnel 另外注册：

```text
Task Scheduler (AtLogOn, current interactive user)
  -> wscript.exe
  -> scripts\run-cloudflared-hidden.vbs
  -> cloudflared tunnel --config <config> run <tunnel-id>
```

## 连接和验证

MCP 客户端必须发送：

- Streamable HTTP URL（必须以 `/mcp` 结尾）
- `Authorization: Bearer <token>`

手工健康检查：

```powershell
Invoke-WebRequest http://127.0.0.1:8765/healthz
.\scripts\status.ps1
```

自定义端口时 `status.ps1` 会从 `config.json` 读取端口。

## 卸载自动启动

`.\scripts\uninstall-autostart.ps1` 仅处理 DeskSense 本地服务任务。Named Tunnel 任务应单独确认后再管理，避免中断其他正在使用该 tunnel 的节点。

## 安全说明

- `.secrets\API_KEY.txt` 等同密码。
- Cloudflare credentials JSON 等同 tunnel 密钥。
- 不要把上述文件上传、提交或发送给他人。
- 不要在两台电脑上同时运行同一个 Named Tunnel credentials。
- DeskSense 工具只读，但窗口标题和进程信息仍属于隐私数据。

现有 Node 的凭据迁移见[迁移指南（英文）](MIGRATE.md)。

# PC Sense MCP

Windows 本机「电脑感知」MCP 服务（**只读**）。

通过 Standard MCP（Streamable HTTP）让 AI（如手机上的 SullyOS）可以了解当前电脑正在发生什么：

- 当前前台程序 / 窗口标题
- 打开的桌面应用窗口
- 键盘鼠标闲置多久
- CPU / 内存 / 磁盘 / 开机时间
- 资源占用最高的进程
- 最近的程序切换历史

> ⚠️ 本项目**只读**。不提供 shell 执行、进程启停、文件修改、关机重启、注册表/服务修改、鼠标键盘模拟或任意代码执行。

---

## 环境

- Python 3.14.6（venv: `.venv`）
- MCP SDK 2.0.0（`mcp`）
- `pywin32`、`psutil`、`starlette`、`uvicorn`
- SQLite（焦点历史）

## 端点

| 端点 | 方式 | 认证 | 用途 |
|------|------|------|------|
| `POST /mcp` | POST | Bearer Token（必需） | MCP Streamable HTTP 单端点 |
| `GET /healthz` | GET | 无 | 健康检查 |
| `OPTIONS` | OPTIONS | 无 | CORS 预检 |

本地监听：`127.0.0.1:8765`

MCP 协议：`2025-03-26` 及更新（SDK 握手协商）。

## MCP 工具（7 个，全只读）

1. **pc_get_context** — 默认综合工具，一次返回前台、闲置、打开应用、CPU/内存/开机、磁盘。
2. **pc_get_focus** — 当前前台窗口（进程名、pid、exe、标题）。
3. **pc_list_open_apps** — 打开的桌面应用窗口（按应用聚合，过滤系统噪音）。
4. **pc_get_idle_status** — 闲置秒数与状态（active/idle/away）。
5. **pc_get_pc_status** — CPU/内存/磁盘/uptime/网络累计。
6. **pc_get_top_processes** — 资源占用最高进程（按 cpu/memory 排序）。
7. **pc_get_recent_focus** — 最近前台切换历史（SQLite）。

## 运行

```powershell
# 后台启动（推荐）
.\scripts\start.ps1

# 状态 / 停止
.\scripts\status.ps1
.\scripts\stop.ps1
```

手动启动：

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m pc_sense.server
```

## 用户登录自启动（Task Scheduler）

在登录后的交互会话运行（非 SYSTEM / 非 Session 0，保证能读前台窗口）。

```powershell
.\scripts\install-autostart.ps1     # 注册（幂等）
.\scripts\status.ps1
.\scripts\uninstall-autostart.ps1   # 移除
```

## 认证

`/mcp` 使用**静态 Bearer Token**（64 位 hex，32 随机字节）。Token 存放在：

```
.secrets\API_KEY.txt
```

- Token 由首次初始化生成，绝不会写入源码 / README / 日志 / git。
- `.secrets/` 已被 `.gitignore` 忽略。
- 调用示例：`Authorization: Bearer <token>`

## CORS

为浏览器端（SullyOS）已配置：

- `Access-Control-Allow-Origin: *`
- 允许请求头：`Content-Type`、`Authorization`、`Mcp-Protocol-Version`、`Mcp-Session-Id`、`Accept`
- 暴露响应头：`Mcp-Session-Id`
- 支持 `OPTIONS` 预检

## 公网访问（Cloudflare Tunnel）

本地 `127.0.0.1:8765` 测试通过后，用 `cloudflared` 建立隧道（不开放路由器端口）。

Quick Tunnel（临时测试）：

```powershell
.\scripts\start-quick-tunnel.ps1
```

需要已安装 `cloudflared`（`winget install --id Cloudflare.cloudflared` 或 `pip install cloudflared`）。

> 固定的命名隧道需要你在 Cloudflare 控制台选定/绑定域名后再配置。SullyOS 最终填写 `https://<你的地址>/mcp`，Bearer Token 请从本机 `.secrets\API_KEY.txt` 手动复制（不在聊天中打印）。

## 配置（config.json）

`config.json` 可调（不含密钥）：

- `host` / `port`
- `focus_poll_interval`：焦点轮询间隔（秒）
- `active_threshold_seconds` / `away_threshold_seconds`：闲置阈值
- `history_retention_days`：焦点历史保留天数
- `exclude_processes`：要忽略的进程名
- `max_open_windows` / `open_apps_limit`

## 数据与日志

- 焦点历史 SQLite：`data\pc_sense.db`（WAL 模式，默认保留 30 天）
- 运行日志：`logs\pc-sense.log`（rotating，5MB×3）
  - 不记录 Authorization / API key / 完整窗口标题流水

## 测试

```powershell
# 单元测试（需要服务不依赖；跑前无需启动）
.\.venv\Scripts\python.exe -m pytest -q

# 端到端集成测试（需先启动服务）
PYTHONPATH=src .\.venv\Scripts\python.exe scripts\run_integration_test.py
```

集成测试覆盖：未授权 401、initialize、tools/list、7 个工具逐个调用。

## 目录结构

```
pc-sense-mcp/
  src/pc_sense/      源码
  tests/             单元测试
  scripts/           PowerShell 运维脚本
  data/              焦点历史 SQLite
  logs/              运行日志
  .secrets/          API key（gitignored）
  config.json        配置
  pyproject.toml     项目元数据 / 依赖
  requirements.txt   依赖
```

## SullyOS 配置

1. 确保本机服务已启动、`status.ps1` 显示 RUNNING。
2. 用 cloudflared 建立隧道，得到 `https://<地址>/mcp`。
3. 在 SullyOS 的 Remote MCP 设置中填写：
   - **URL**: `https://<地址>/mcp`
   - **认证**: Bearer Token（从 `.secrets\API_KEY.txt` 复制）
   - 协议自动为 Streamable HTTP（2025-03-26+）。
4. AI 会优先调用 `pc_get_context` 感知电脑整体状态。
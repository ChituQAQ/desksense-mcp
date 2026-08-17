# DeskSense MOVE — 迁移到新电脑

DeskSense 是一套 *机器绑定* 的 MCP 服务（依赖本机进程/窗口信息），要搬去新电脑时用本目录的 `export-move.ps1` 导出，
到新电脑解压后跑 `install-move.ps1` 完成接管。

> 本文档只描述 **MOVE（单机迁移）**。不做多机共存、不做 ADD / retire / reactivate，也不创建新 Tunnel 或 DNS。

---

## 设计目标

迁移需要携带的是一台旧电脑（DeskSense、Cloudflared Named Tunnel）的全部"身份"：

- 项目运行代码与配置
- `config.json`
- `.secrets/API_KEY.txt`（Bearer token）
- 当前 Named Tunnel 的 credentials JSON（`~/.cloudflared/*.json`）
- 当前 `cloudflared config.yml`
- `manifest.json`（hostname / tunnel_id / export_time / git_commit）
- `SENSITIVE.txt`（内容警示）

**不迁移** focus history DB（`data/*.db*`）——历史焦点记录是旧机器的运行数据，不属于迁移身份的一部分。

---

## 第一步：旧电脑导出

在旧电脑项目根目录运行：

```powershell
.\scripts\export-move.ps1
```

生成：

```
dist\desksense-move-<timestamp>.zip
```

ZIP 包含敏感文件（API_KEY、Tunnel credentials），**不要提交 git、不要公开分享**。
脚本只打印文件名清单与 manifest，**不会打印 Token / credentials 内容**。

把 ZIP 复制到新电脑并解压（复制要经加密/安全通道，例如 U 盘或私有网盘）。

---

## 第二步：新电脑安装

在新电脑 **解压出的目录** 里运行（不是 `D:\Projects\...` 的原路径，脚本会自动推导根目录）：

```powershell
.\scripts\install-move.ps1
```

脚本会：

1. 从自身位置推导项目根目录（不硬编码 `D:\Projects`，不硬编码 `Administrator`）
2. 动态发现 `HOME` / `USERPROFILE`
3. 动态发现 `cloudflared.exe`（Program Files、Program Files (x86)、`~/.cloudflared`、PATH）
4. 检查 Python
5. 创建 `.venv` 并 `pip install -r requirements.txt`
6. 恢复 `API_KEY.txt`
7. 恢复 Tunnel credentials 到新用户的 `~/.cloudflared`
8. 重写正确的 `config.yml`（origin 保持 `http://127.0.0.1:8765`，hostname 从导出的 config 读取）
9. **警告并要求输入 `YES`** 才会继续（见下）
10. 注册两个交互用户登录自启动任务：`PC Sense MCP`、`Cloudflared Named Tunnel`
    （均为 `LogonType Interactive`、当前交互用户，**不做 SYSTEM**）
11. 启动 DeskSense server 与 Named Tunnel

---

## 关键安全闸门

启动 True Named Tunnel 之前，脚本会显示橙色/红色警告并要求输入**完全匹配**：

```
YES
```

**必须满足**：旧电脑已关机，或旧电脑上的 DeskSense / cloudflared 已停止。
否则输入任何其它内容都会直接退出、不启动 Tunnel。

> 同一个 Named Tunnel 若同时被两台主机运行，会互相冲突、导致公网端点不稳定。

---

## 自启动任务

| 任务名 | 执行内容 | 用户 |
|---|---|---|
| `PC Sense MCP` | venv python `-m pc_sense.server` | 当前交互用户 |
| `Cloudflared Named Tunnel` | `start-named-tunnel.ps1`（Named Tunnel run） | 当前交互用户 |

均 `LogonType Interactive`，登录后启动。

---

## 验证清单（新电脑上建议执行）

- 本地：`Invoke-WebRequest http://127.0.0.1:8765/healthz` → 200
- 公网：`curl https://pc.sullyos.ccwu.cc/mcp` → 可达（origin `http://127.0.0.1:8765`）
- `scripts/start.ps1` / `scripts/stop.ps1` 可用

---

## 注意事项

- Windows 系统代理 / v2rayN 可能让 Python `httpx` 请求 `localhost` 产生假 `503`；
  本地 Python 验证请用 `trust_env=False`，或直接用 `curl`。
- Named Tunnel 名称 `pc-sense-mcp`、公网 hostname `pc.sullyos.ccwu.cc`、Bearer token 在迁移前后保持不变。
- 迁移完成后，旧电脑不再运行 DeskSense / cloudflared。
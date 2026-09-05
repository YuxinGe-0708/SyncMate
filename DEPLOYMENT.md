# SyncMate 本地运行与部署说明

## 1. 项目说明

SyncMate 是一个 React + Vite 前端、FastAPI 后端和 SQLite 数据库组成的 Web 应用。

项目提供两个 Windows 启动脚本：

- `start-backend.cmd`：创建 Python 虚拟环境、安装后端依赖并启动 FastAPI。
- `start-frontend.cmd`：安装前端依赖并启动 Vite 开发服务器。

两个脚本不能脱离项目目录单独运行，必须保留后端代码、前端源码和依赖配置文件。

## 2. 本地运行（Windows）

### 2.1 环境要求

- Windows 10/11
- Python 3.8 及以上
- Node.js 20.19 及以上
- npm

### 2.2 启动后端

在项目根目录双击运行：

```text
start-backend.cmd
```

脚本会自动创建 `.venv`、安装 `backend/requirements.txt` 中的依赖，并启动后端服务。后端默认监听：

```text
http://localhost:8000/
```

也可以手动启动：

```powershell
cd D:\learn\SyncMate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

### 2.3 启动前端

保持后端窗口运行，在项目根目录双击：

```text
start-frontend.cmd
```

脚本会在缺少 `node_modules` 时自动执行 `npm install`，然后启动 Vite。前端默认地址为：

```text
http://localhost:5173/
```

启动后使用浏览器访问该地址。默认演示账号为 `demo`，密码为 `123456`。

### 2.4 数据库

默认数据库文件为 `backend/syncmate.db`。如果文件不存在，后端首次启动时会自动创建并初始化数据库。

如需指定其他数据库位置，可设置：

```powershell
$env:SYNCMATE_DB_PATH = "D:\data\syncmate.db"
```

### 2.5 AI 分账配置（可选）

AI 小票分账使用 Qwen Vision。启动后端前，在当前 PowerShell 会话设置：

```powershell
$env:DASHSCOPE_API_KEY = "你的 DashScope API Key"
$env:QWEN_BASE_URL = "https://你的工作空间.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
$env:SYNCMATE_QWEN_MODEL = "qwen3-vl-plus"
```

然后重新运行 `start-backend.cmd`。未配置密钥时，普通群组、旅行路线和财务分析功能仍可使用，但 AI 小票识别不可用。不要把真实密钥写入代码、配置模板或提交到仓库。

### 2.6 局域网访问

启动脚本会监听本机所有网卡。执行以下命令查看局域网 IPv4 地址：

```powershell
ipconfig
```

同一局域网中的设备可访问：

```text
http://<本机局域网IPv4>:5173/
```

如果访问失败，请在防火墙中允许 TCP 端口 `5173`；后端端口 `8000` 通常只供前端代理使用。

## 3. 生产部署（Ubuntu + Nginx）

生产环境推荐由 Nginx 托管前端静态文件，由 Uvicorn 运行 FastAPI，并使用 systemd 管理后端服务。项目中的部署模板位于 `deploy/`：

- `deploy/nginx-syncmate.conf`：Nginx 配置。
- `deploy/syncmate.service`：systemd 服务配置。
- `deploy/syncmate.env.example`：环境变量示例。

### 3.1 安装系统依赖

```bash
sudo apt update
sudo apt install -y python3 python3-venv nginx nodejs npm
```

确认 Python、Node.js 和 npm 版本符合本说明的环境要求。

### 3.2 上传项目并安装后端依赖

假设项目目录为 `/opt/syncmate-app`：

```bash
sudo mkdir -p /opt/syncmate/data
sudo chown -R ubuntu:ubuntu /opt/syncmate-app /opt/syncmate

python3 -m venv /opt/syncmate-venv
/opt/syncmate-venv/bin/pip install --upgrade pip
/opt/syncmate-venv/bin/pip install -r /opt/syncmate-app/backend/requirements.txt
```

### 3.3 构建前端

```bash
cd /opt/syncmate-app
npm ci
npm run build
```

构建后会生成 `/opt/syncmate-app/dist`，Nginx 将使用该目录作为网站根目录。

### 3.4 配置环境变量

```bash
sudo cp /opt/syncmate-app/deploy/syncmate.env.example /etc/syncmate.env
sudo nano /etc/syncmate.env
```

至少确认数据库路径：

```text
SYNCMATE_DB_PATH=/opt/syncmate/data/syncmate.db
```

如果启用 AI 分账，再填写 `DASHSCOPE_API_KEY`、`QWEN_BASE_URL` 和 `SYNCMATE_QWEN_MODEL`。真实密钥只保存于服务器的 `/etc/syncmate.env`。Skill 已包含在项目仓库中，`SYNCMATE_RECEIPT_SPLITTER` 应指向：

```text
SYNCMATE_RECEIPT_SPLITTER=/opt/syncmate-app/skills/receipt-splitter/scripts/receipt_splitter.py
```

不要将真实 API Key、小票原图或个人级测试数据提交到 GitHub。

### 3.5 配置并启动 systemd 服务

```bash
sudo cp /opt/syncmate-app/deploy/syncmate.service /etc/systemd/system/syncmate.service
sudo systemctl daemon-reload
sudo systemctl enable syncmate
sudo systemctl start syncmate
sudo systemctl status syncmate
```

后端默认只监听 `127.0.0.1:8000`，可检查：

```bash
curl http://127.0.0.1:8000/api/health
```

### 3.6 配置 Nginx

```bash
sudo cp /opt/syncmate-app/deploy/nginx-syncmate.conf /etc/nginx/sites-available/syncmate
sudo ln -s /etc/nginx/sites-available/syncmate /etc/nginx/sites-enabled/syncmate
sudo nginx -t
sudo systemctl enable nginx
sudo systemctl restart nginx
```

Nginx 的转发关系如下：

```text
/       -> /opt/syncmate-app/dist
/api/   -> http://127.0.0.1:8000
```

部署完成后，通过服务器 IP 或域名访问：

```text
http://服务器IP/
```

生产环境通常只对外开放 TCP `80` 端口，后端 `8000` 端口不直接暴露到公网。

## 4. 更新部署

更新代码后执行：

```bash
cd /opt/syncmate-app
git pull
npm ci
npm run build
sudo systemctl restart syncmate
sudo systemctl reload nginx
```

## 5. 故障排查

查看后端日志：

```bash
sudo journalctl -u syncmate -f
```

查看 Nginx 错误日志：

```bash
sudo tail -f /var/log/nginx/error.log
```

检查端口监听：

```bash
sudo ss -lntp | grep -E ':(80|8000)'
```

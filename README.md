# SyncMate

智能分账与群体日程协同平台。当前版本包含 React 前端、FastAPI 后端和 SQLite 数据库。

## 已实现功能

- 用户注册、登录和退出
- 修改昵称、头像配色和密码
- 查看已加入的群组，并创建新群组
- 查看待处理账单和待确认付款
- 查看个人收入、支出和最近收支记录
- SQLite 数据持久化与带盐密码哈希
- 消费热力与财务分析：群组/分类热力、商户排行、月度区域环比
- AI 小票按商户拆分记录，支持从已有地图搜索或地图点选补充消费地点
- 仓库内置 `skills/receipt-splitter` Skill：Qwen Vision 识别、自然语言规则解析、金额校验和最小现金流计算
- 创建、编辑、退出和解散群组
- 宿舍、合租、旅行、聚餐群组模板
- 邀请码、邀请链接和二维码加入
- 可配置的入群审核与邀请有效期
- 群主、管理员、普通成员和临时成员权限
- 群内昵称、成员备注、加入时间和动态活跃度
- 群公告、主题色与封面样式
- 转让群主、操作审计日志及重要操作撤销
- 独立的旅行路线规划：旅行计划、地图地点、每日路线、自动规划、集合点推荐、预算检查、发布与共享日程同步

## 启动项目

项目需要同时启动前端和后端。

1. 双击 `start-backend.cmd`，保持窗口运行。
2. 双击 `start-frontend.cmd`，保持窗口运行。
3. 浏览器打开 http://localhost:5173/ 。

### 局域网访问

启动脚本会监听本机所有网卡。请在运行项目的电脑上执行 `ipconfig`，将无线网卡或有线网卡的 IPv4 地址分享给同一局域网中的用户，访问：

```text
http://<本机局域网IPv4>:5173/
```

例如本机地址为 `10.135.49.112` 时，访问地址为 `http://10.135.49.112:5173/`。防火墙需要允许 TCP 入站端口 `5173`（前端）和 `8000`（后端仅供本机代理使用）。

如果重新打开终端启动并需要 AI 分账，请先在该 PowerShell 会话中设置 `DASHSCOPE_API_KEY`，再运行 `start-backend.cmd`；密钥只会传给当前运行进程。若 Windows 防火墙拦截局域网访问，请以管理员身份执行：

```powershell
netsh advfirewall firewall add rule name="SyncMate Frontend 5173" dir=in action=allow protocol=TCP localport=5173 profile=any
```

演示账号：`demo`，密码：`123456`。

也可以在两个终端中手动运行：

```powershell
cd D:\learn\SyncMate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

```powershell
cd D:\learn\SyncMate
npm.cmd run dev
```

数据库文件位于 `backend/syncmate.db`，首次启动后端时自动创建并初始化演示数据。

## 旅行路线规划

进入“我的群组”后选择群组，再打开“旅行路线”标签。群主或管理员可以新建旅行计划，添加景点/酒店/餐厅/购物地点，设置必去地点和每日路线；普通成员可以查看路线并提交集合位置。

- 地点搜索使用 OpenStreetMap/Nominatim，地图使用 OpenStreetMap 图层；
- 路线距离和时间使用后端 Haversine + 交通速度进行免费稳定估算，不依赖商业地图 Key；
- “自动规划路线”会生成距离最短、时间最省、景点最多和舒适度最高等方案；
- 发布前检查会校验必去地点、时间冲突、预算、重复地点和起终点；
- 只有已发布路线可以同步到共享日程，重复点击同步会更新原日程，不会重复创建。

## 消费热力与财务分析

左侧“消费分析”会统计当前用户所在群组中已由群主确认或已归档的 AI 分账。页面提供月份、群组和分类筛选，并展示：

- 群组消费热力图：地图红色圆点为当前月份，蓝色虚线圆点为上月；
- 分类消费热力矩阵：按每月五个自然周查看分类消费强度；
- 高消费商户排行与消费笔数；
- 本月/上月消费区域对比；
- 未标注地点的消费记录，可通过 OpenStreetMap 搜索或地图点选补充坐标。

AI 分账创建后会自动按每张小票生成消费记录；已有 AI 分账记录会在后端启动时自动补齐这些派生记录。没有地点坐标的记录仍会进入金额、分类和商户统计，补充地点后才会进入地图和区域对比。

## 演示数据

本机默认数据库首次启动后会自动写入一套可直接演示的数据，且使用正式业务表，不是前端 mock：

- “周末聚餐”包含一条已发布的固定活动和一条已完成投票并发布的活动；活动地点、成员投票和共享日程相互对应；
- “海边两日游”包含两天已发布路线、6 个地点、路线节点、预算和同步到共享日程的活动；
- 同一旅行群组包含一笔已激活的 AI 共同支出，带本月/上月消费、餐饮/门票/住宿分类和地图坐标，可直接展示钱包待付款与消费分析；
- AI 分账页面的“分账规则”默认保持空白，输入规则后才会提交分析。

如果使用自定义 `SYNCMATE_DB_PATH`，可在初始化时设置 `$env:SYNCMATE_SEED_SHOWCASE_DATA = "1"` 显式开启这套演示数据。初始化逻辑是幂等的，重复启动不会重复创建。

## AI 分账配置

AI 分账使用 Qwen Vision。启动后端前请在当前 PowerShell 会话中设置环境变量（不要把密钥写进代码或提交到仓库）：

```powershell
$env:DASHSCOPE_API_KEY = "你的 DashScope API Key"
$env:QWEN_BASE_URL = "https://你的工作空间.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
$env:SYNCMATE_QWEN_MODEL = "qwen3-vl-plus"
```

然后运行 `start-backend.cmd`。如果未配置密钥，AI 分账接口会返回明确的配置错误，不会伪造分账结果。

## 腾讯云生产部署

生产环境由 Nginx 提供前端和 `/api` 反向代理，FastAPI 由 systemd 开机自启，数据库使用 `/opt/syncmate/data/syncmate.db`。部署配置模板位于 `deploy/`；服务器密钥只写入 `/etc/syncmate.env`，不要提交到 GitHub。AI Skill 已随仓库发布，默认路径为 `/opt/syncmate-app/skills/receipt-splitter/scripts/receipt_splitter.py`。

- 访问地址：`http://43.143.228.182/`
- 后端检查：`curl http://127.0.0.1:8000/api/health`
- 服务状态：`sudo systemctl status syncmate nginx`
- 更新代码：在 `/opt/syncmate-app` 执行 `git pull`、`npm ci && npm run build`，然后执行 `sudo systemctl restart syncmate`

# SyncMate

智能分账与群体日程协同平台。当前版本包含 React 前端、FastAPI 后端和 SQLite 数据库。

## 已实现功能

- 用户注册、登录和退出
- 修改昵称、头像配色和密码
- 查看已加入的群组，并创建新群组
- 查看待处理账单和待确认付款
- 查看个人收入、支出和最近收支记录
- SQLite 数据持久化与带盐密码哈希
- 创建、编辑、退出和解散群组
- 宿舍、合租、旅行、聚餐群组模板
- 邀请码、邀请链接和二维码加入
- 可配置的入群审核与邀请有效期
- 群主、管理员、普通成员和临时成员权限
- 群内昵称、成员备注、加入时间和动态活跃度
- 群公告、主题色与封面样式
- 转让群主、操作审计日志及重要操作撤销

## 启动项目

项目需要同时启动前端和后端。

1. 双击 `start-backend.cmd`，保持窗口运行。
2. 双击 `start-frontend.cmd`，保持窗口运行。
3. 浏览器打开 http://localhost:5173/ 。

演示账号：`demo`，密码：`123456`。

也可以在两个终端中手动运行：

```powershell
cd C:\Users\Lenovo\Desktop\SyncMate
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000
```

```powershell
cd C:\Users\Lenovo\Desktop\SyncMate
npm.cmd run dev
```

数据库文件位于 `backend/syncmate.db`，首次启动后端时自动创建并初始化演示数据。

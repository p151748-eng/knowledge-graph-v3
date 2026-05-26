# KG-Agent System v2 部署运维文档

## 1. 部署概述

### 1.1 部署架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                         用户访问                                     │
│                     http://localhost:5173                            │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       前端服务 (Vite)                                │
│                     http://localhost:5173                            │
│                                                                     │
│   React + TypeScript + Tailwind CSS                                 │
│   静态资源打包后可部署到任意 Web 服务器                               │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                                   │ API 请求
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       后端服务 (FastAPI)                             │
│                     http://localhost:8001                            │
│                                                                     │
│   Python + FastAPI + Uvicorn                                        │
│   提供 REST API，处理对话、检索、导入等业务                           │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
┌────────────────────────────┐    ┌────────────────────────────────────┐
│        MySQL 8.0           │    │       外部 LLM API                  │
│                            │    │                                    │
│   kg_agent 数据库           │    │   - OpenAI API                     │
│   - nodes                  │    │   - Anthropic API                  │
│   - edges                  │    │   - DeepSeek API                   │
│   - documents              │    │   - DashScope API                  │
│   - conversations          │    │                                    │
└────────────────────────────┘    └────────────────────────────────────┘
```

### 1.2 部署方式

| 方式 | 适用场景 | 复杂度 |
|------|----------|--------|
| **本地开发部署** | 开发测试 | 简单 |
| **生产环境部署** | 实际使用 | 中等 |
| **Docker 部署** | 快速部署 | 中等 |

---

## 2. 本地开发部署

### 2.1 环境准备

**系统要求：**
| 项目 | 版本 | 检查命令 |
|------|------|----------|
| Python | ≥ 3.10 | `python --version` |
| Node.js | ≥ 18 | `node --version` |
| MySQL | ≥ 8.0 | `mysql --version` |

### 2.2 后端部署步骤

**Step 1: 克隆项目**

```bash
git clone https://github.com/xxx/kg-workspace-v2.git
cd kg-workspace-v2/backend
```

**Step 2: 创建虚拟环境**

```bash
# Linux/Mac
python -m venv .venv
source .venv/bin/activate

# Windows
python -m venv .venv
.venv\Scripts\activate
```

**Step 3: 安装依赖**

```bash
pip install -r requirements.txt
```

**Step 4: 配置环境变量**

```bash
# 复制模板
cp .env.example .env

# 编辑配置
vim .env  # 或使用任意编辑器
```

**.env 配置示例：**

```env
# 数据库（必须配置）
DATABASE_URL=mysql+pymysql://root:123456@localhost:3306/kg_agent

# LLM（至少配置一个）
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini

# 服务
PORT=8001
HOST=0.0.0.0
DEBUG=true
```

**Step 5: 创建数据库**

```sql
-- 登录 MySQL
mysql -u root -p

-- 创建数据库
CREATE DATABASE kg_agent CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- 确认创建成功
SHOW DATABASES LIKE 'kg_agent';
```

**Step 6: 启动服务**

```bash
# 方式 1: 直接运行
python main.py

# 方式 2: 使用 uvicorn
uvicorn main:app --host 0.0.0.0 --port 8001 --reload

# 方式 3: 指定配置
uvicorn main:app --host 127.0.0.1 --port 8001
```

**启动成功输出：**

```
INFO:     Uvicorn running on http://0.0.0.0:8001 (Press CTRL+C to quit)
INFO:     Started reloader process [xxxxx]
INFO:     Started server process [xxxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**验证服务：**

```bash
# 健康检查
curl http://localhost:8001/api/health

# 预期输出
{"success": true, "data": {"status": "healthy", ...}}
```

### 2.3 前端部署步骤

**Step 1: 进入前端目录**

```bash
cd kg-workspace-v2/frontend
```

**Step 2: 安装依赖**

```bash
npm install
```

**Step 3: 配置 API 地址**

```bash
# 创建 .env.local
echo "VITE_API_URL=http://localhost:8001" > .env.local
```

**Step 4: 启动开发服务器**

```bash
npm run dev
```

**启动成功输出：**

```
  VITE v6.0.5  ready in 500 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.x.x:5173/
  ➜  press h + enter to show help
```

**Step 5: 访问应用**

打开浏览器访问：http://localhost:5173

---

## 3. 生产环境部署

### 3.1 后端生产配置

**Step 1: 修改 .env 配置**

```env
# 生产模式
DEBUG=false

# 数据库
DATABASE_URL=mysql+pymysql://kg_user:your_password@localhost:3306/kg_agent

# LLM
OPENAI_API_KEY=sk-xxxxxxxx
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0.5

# 服务
PORT=8001
HOST=127.0.0.1  # 仅本地访问，前端代理访问
```

**Step 2: 使用生产级 ASGI 服务器**

```bash
# 使用 Gunicorn + Uvicorn workers
pip install gunicorn

# 启动命令
gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8001 \
  --timeout 120 \
  --keep-alive 5
```

**Step 3: 使用 systemd 管理服务（Linux）**

```bash
# 创建服务文件
sudo vim /etc/systemd/system/kg-agent.service
```

**kg-agent.service 内容：**

```ini
[Unit]
Description=KG-Agent System Backend
After=network.target mysql.service

[Service]
Type=notify
User=your_user
Group=your_group
WorkingDirectory=/path/to/kg-workspace-v2/backend
Environment="PATH=/path/to/kg-workspace-v2/backend/.venv/bin"
ExecStart=/path/to/kg-workspace-v2/backend/.venv/bin/gunicorn main:app \
  --workers 4 \
  --worker-class uvicorn.workers.UvicornWorker \
  --bind 127.0.0.1:8001
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
# 启用并启动服务
sudo systemctl enable kg-agent
sudo systemctl start kg-agent

# 查看状态
sudo systemctl status kg-agent

# 查看日志
sudo journalctl -u kg-agent -f
```

### 3.2 前端生产构建

**Step 1: 构建静态文件**

```bash
cd frontend
npm run build
```

**构建输出：**

```
vite v6.0.5 building for production...
✓ 50 modules transformed.
dist/index.html                  0.45 kB │ gzip:  0.30 kB
dist/assets/index-abc123.css     2.30 kB │ gzip:  0.80 kB
dist/assets/index-def456.js    150.00 kB │ gzip: 50.00 kB
✓ built in 2.00s
```

**Step 2: 部署静态文件**

```bash
# 部署到 Nginx
sudo cp -r dist/* /var/www/kg-agent/

# 或部署到任意 Web 服务器
```

**Step 3: Nginx 配置**

```nginx
# /etc/nginx/sites-available/kg-agent.conf

server {
    listen 80;
    server_name your-domain.com;

    # 前端静态文件
    root /var/www/kg-agent;
    index index.html;

    location / {
        try_files $uri $uri/ /index.html;
    }

    # API 反向代理
    location /api {
        proxy_pass http://127.0.0.1:8001;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_timeout 120s;
    }
}
```

```bash
# 启用配置
sudo ln -s /etc/nginx/sites-available/kg-agent.conf /etc/nginx/sites-enabled/

# 测试配置
sudo nginx -t

# 重载 Nginx
sudo systemctl reload nginx
```

### 3.3 MySQL 生产配置

**创建专用用户：**

```sql
-- 创建用户
CREATE USER 'kg_user'@'localhost' IDENTIFIED BY 'strong_password_here';

-- 授权
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER
ON kg_agent.* TO 'kg_user'@'localhost';

FLUSH PRIVILEGES;
```

**MySQL 配置优化（my.cnf）：**

```ini
[mysqld]
# 字符集
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci

# 连接数
max_connections=100

# 缓存
innodb_buffer_pool_size=256M
innodb_log_file_size=64M

# 查询缓存
query_cache_size=0
query_cache_type=0
```

---

## 4. Docker 部署

### 4.1 Docker Compose 配置

**docker-compose.yml：**

```yaml
version: '3.8'

services:
  # MySQL 数据库
  mysql:
    image: mysql:8.0
    container_name: kg-agent-mysql
    restart: always
    environment:
      MYSQL_ROOT_PASSWORD: root_password
      MYSQL_DATABASE: kg_agent
      MYSQL_USER: kg_user
      MYSQL_PASSWORD: kg_password
      MYSQL_CHARSET: utf8mb4
      MYSQL_COLLATION: utf8mb4_unicode_ci
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 10s
      timeout: 5s
      retries: 5

  # 后端服务
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: kg-agent-backend
    restart: always
    depends_on:
      mysql:
        condition: service_healthy
    environment:
      DATABASE_URL: mysql+pymysql://kg_user:kg_password@mysql:3306/kg_agent
      OPENAI_API_KEY: ${OPENAI_API_KEY}
      LLM_PROVIDER: openai
      LLM_MODEL: gpt-4o-mini
      PORT: 8001
      DEBUG: false
    ports:
      - "8001:8001"
    volumes:
      - ./backend:/app

  # 前端服务
  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    container_name: kg-agent-frontend
    restart: always
    depends_on:
      - backend
    ports:
      - "80:80"
    environment:
      VITE_API_URL: http://backend:8001

volumes:
  mysql_data:
```

**backend/Dockerfile：**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 暴露端口
EXPOSE 8001

# 启动命令
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
```

**frontend/Dockerfile：**

```dockerfile
FROM node:18-alpine AS builder

WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
```

### 4.2 Docker 部署命令

```bash
# 构建并启动
docker-compose up -d --build

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down

# 带数据停止
docker-compose down -v
```

---

## 5. 运维监控

### 5.1 日志管理

**后端日志配置：**

```python
# backend/config.py

import logging
from logging.handlers import RotatingFileHandler

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler(
            'logs/app.log',
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)
```

**日志文件位置：**

```
backend/logs/
├── app.log          # 应用日志
├── app.log.1        # 历史日志（轮转）
├── app.log.2
├── error.log        # 错误日志（单独）
└── access.log       # 访问日志
```

### 5.2 健康检查

**定时健康检查脚本：**

```bash
# scripts/health_check.sh

#!/bin/bash

API_URL="http://localhost:8001/api/health"
LOG_FILE="logs/health.log"

response=$(curl -s -o /dev/null -w "%{http_code}" $API_URL)

if [ $response -eq 200 ]; then
    echo "$(date) - Health check passed" >> $LOG_FILE
else
    echo "$(date) - Health check FAILED: HTTP $response" >> $LOG_FILE
    # 发送通知（可选）
    # mail -s "KG-Agent Health Alert" admin@example.com
fi
```

**定时任务（crontab）：**

```bash
# 每5分钟检查一次
*/5 * * * * /path/to/scripts/health_check.sh
```

### 5.3 数据备份

**MySQL 备份脚本：**

```bash
# scripts/backup_db.sh

#!/bin/bash

BACKUP_DIR="/path/to/backups"
DATE=$(date +%Y%m%d_%H%M%S)
DB_NAME="kg_agent"
DB_USER="kg_user"
DB_PASS="your_password"

# 创建备份目录
mkdir -p $BACKUP_DIR

# 执行备份
mysqldump -u $DB_USER -p$DB_PASS $DB_NAME > $BACKUP_DIR/kg_agent_$DATE.sql

# 压缩
gzip $BACKUP_DIR/kg_agent_$DATE.sql

# 删除30天前的备份
find $BACKUP_DIR -name "*.sql.gz" -mtime +30 -delete

echo "Backup completed: kg_agent_$DATE.sql.gz"
```

**定时备份（crontab）：**

```bash
# 每天凌晨2点备份
0 2 * * * /path/to/scripts/backup_db.sh >> /path/to/logs/backup.log
```

---

## 6. 性能优化

### 6.1 后端优化

| 优化项 | 方法 | 效果 |
|--------|------|------|
| LLM 调用超时 | 设置 timeout=60s | 防止长时间等待 |
| 数据库连接池 | pool_size=5, pool_pre_ping=True | 提升连接效率 |
| 向量计算优化 | 批量处理，预计算缓存 | 减少重复计算 |
| API 响应缓存 | Redis 缓存热门查询 | 减少重复处理 |

### 6.2 前端优化

| 优化项 | 方法 | 效果 |
|--------|------|------|
| 打包优化 | Vite 自动分包 | 减小包体积 |
| 图片懒加载 | React lazy loading | 加快首屏 |
| API 请求缓存 | TanStack Query staleTime | 减少重复请求 |

### 6.3 MySQL 优化

```sql
-- 添加索引
CREATE INDEX idx_node_name ON nodes(name);
CREATE INDEX idx_node_type ON nodes(type);
CREATE INDEX idx_edge_relation ON edges(relation);

-- 查看索引使用情况
EXPLAIN SELECT * FROM nodes WHERE name LIKE '%RAG%';
```

---

## 7. 安全配置

### 7.1 API 安全

```python
# backend/main.py

from fastapi.middleware.cors import CORSMiddleware

# CORS 配置（生产环境收紧）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-domain.com"],  # 仅允许指定域名
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
    max_age=3600,
)
```

### 7.2 数据库安全

```sql
-- 删除空密码用户
DELETE FROM mysql.user WHERE Password='';
DELETE FROM mysql.user WHERE authentication_string='';

-- 禁止 root 远程登录
DELETE FROM mysql.user WHERE User='root' AND Host NOT IN ('localhost', '127.0.0.1');

-- 刷新权限
FLUSH PRIVILEGES;
```

### 7.3 系统安全

```bash
# 限制 API 端口仅本地访问
# 修改 HOST=127.0.0.1

# 使用防火墙
sudo ufw allow 80/tcp    # 前端
sudo ufw allow 443/tcp   # HTTPS
sudo ufw deny 8001/tcp   # 禁止外部访问 API 端口
sudo ufw enable
```

---

## 8. 常见问题与解决方案

### 8.1 服务无法启动

| 问题 | 检查 | 解决方案 |
|------|------|----------|
| 端口占用 | `lsof -i :8001` | 修改端口或停止占用进程 |
| 数据库连接失败 | 检查 .env 配置 | 确认用户名密码正确 |
| LLM API 调用失败 | 检查 API Key | 确认 Key 有效且有余额 |

### 8.2 性能问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 对话响应慢 | LLM 调用耗时 | 选择更快模型如 gpt-4o-mini |
| 检索延迟高 | 向量计算慢 | 批量预计算 embedding |
| 数据库慢 | 缺少索引 | 添加索引优化 |

### 8.3 数据问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 中文乱码 | 字符集配置 | 使用 utf8mb4 |
| 数据丢失 | 未备份 | 定时 mysqldump |
| 存储增长快 | 向量数据大 | 定期清理旧节点 |

---

## 9. 更新升级

### 9.1 代码更新

```bash
# 拉取最新代码
git pull origin main

# 后端更新
cd backend
pip install -r requirements.txt  # 更新依赖
sudo systemctl restart kg-agent  # 重启服务

# 前端更新
cd frontend
npm install          # 更新依赖
npm run build        # 重新构建
sudo cp -r dist/* /var/www/kg-agent/
```

### 9.2 数据库迁移

```bash
# 如有表结构变更，执行迁移
# backend/migrations/add_xxx_table.sql

mysql -u kg_user -p kg_agent < migrations/add_xxx_table.sql
```

---

## 10. 附录

### 10.1 端口说明

| 端口 | 服务 | 访问方式 |
|------|------|----------|
| 5173 | 前端开发 | 本地开发 |
| 8001 | 后端 API | 仅本地 |
| 80 | 前端生产 | 公网 |
| 3306 | MySQL | 仅本地 |

### 10.2 文件权限

```bash
# 设置日志目录权限
chmod 755 backend/logs
chmod 644 backend/logs/*.log

# 设置 .env 权限（敏感信息）
chmod 600 backend/.env
```

### 10.3 服务管理命令

```bash
# systemd 管理
sudo systemctl start kg-agent     # 启动
sudo systemctl stop kg-agent      # 停止
sudo systemctl restart kg-agent   # 重启
sudo systemctl status kg-agent    # 状态
sudo journalctl -u kg-agent -f    # 日志

# Docker 管理
docker-compose up -d              # 启动
docker-compose down               # 停止
docker-compose restart            # 重启
docker-compose logs -f            # 日志
```
#!/bin/bash
# KG-Agent System v2 启动脚本 (Linux/Mac)

echo "============================================"
echo "KG-Agent System v2 启动"
echo "============================================"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "[错误] 未找到 Python3，请先安装"
    exit 1
fi

# 检查依赖
if [ ! -d "backend/venv" ]; then
    echo "[提示] 建议创建虚拟环境: python3 -m venv backend/venv"
fi

# 启动后端
echo ""
echo "[1/2] 启动后端服务 (http://localhost:8003)..."
cd backend
python3 -m uvicorn main:app --host 0.0.0.0 --port 8003 &
BACKEND_PID=$!

# 等待后端启动
sleep 3

# 启动前端
echo "[2/2] 启动前端服务 (http://localhost:5173)..."
cd ../frontend
npm run dev &
FRONTEND_PID=$!

echo ""
echo "============================================"
echo "启动完成！"
echo "后端: http://localhost:8003"
echo "前端: http://localhost:5173"
echo ""
echo "按 Ctrl+C 停止所有服务"
echo "============================================"

# 捕获 Ctrl+C
trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" SIGINT SIGTERM

# 保持脚本运行
wait

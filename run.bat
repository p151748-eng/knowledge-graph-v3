@echo off
REM KG-Agent System v2 启动脚本 (Windows)

echo ============================================
echo KG-Agent System v2 启动
echo ============================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

REM 启动后端
echo.
echo [1/2] 启动后端服务 (http://localhost:8003)...
cd /d "%~dp0backend"
start "KG-Agent Backend" cmd /c "python main.py"

REM 等待后端启动
timeout /t 3 /nobreak >nul

REM 启动前端
echo [2/2] 启动前端服务 (http://localhost:5173)...
cd /d "%~dp0frontend"
start "KG-Agent Frontend" cmd /c "npm run dev"

echo.
echo ============================================
echo 启动完成！
echo 后端: http://localhost:8003
echo 前端: http://localhost:5173
echo.
echo 按任意键打开浏览器...
pause >nul

start http://localhost:5173

@echo off
chcp 65001 > nul
echo ===================================================
echo 🚀 正在启动 Legado Pro 级加密聚合爬虫局域网服务端...
echo ===================================================

cd /d "%~dp0"

if not exist ".venv" (
    echo 📂 未检测到专属虚拟环境，正在使用 uv 自动极速创建...
    uv venv --python 3.12
)

echo ⚡ 正在检查并极速更新依赖包...
call .venv\Scripts\activate.bat
uv pip install -r requirements.txt

echo.
echo ===================================================
echo ✅ 专属环境已就位！服务器正在启动...
echo 💡 提示：按 Ctrl+C 可以随时退出服务器。
echo ===================================================
echo.

python main.py
pause

#!/bin/bash
echo "==================================================="
echo "🚀 正在启动 Legado Pro 级加密聚合爬虫 Linux 服务端..."
echo "==================================================="

# 确保脚本切换到当前目录下
cd "$(dirname "$0")"

# 检查虚拟环境
if [ ! -d ".venv" ]; then
    echo "📂 未检测到 .venv 专属环境，正在使用 uv 创建..."
    uv venv --python 3.12
fi

echo "⚡ 正在检查并极速更新依赖包..."
source .venv/bin/activate
uv pip install -r requirements.txt

echo ""
echo "==================================================="
echo "✅ 专属环境已就位！服务器正在启动..."
echo "💡 提示：按 Ctrl+C 可以退出服务器。"
echo "==================================================="
echo ""

python main.py

FROM docker.1panel.live/library/python:3.12-slim

WORKDIR /app

# 默认设置清华大学 PyPI 镜像源，大幅提升国内服务器构建下载速度！
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["python", "main.py"]

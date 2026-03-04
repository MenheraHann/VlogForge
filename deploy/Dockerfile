FROM python:3.11-slim

# 安装 FFmpeg
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建产物目录
RUN mkdir -p artifacts

ENV PORT=8000
EXPOSE $PORT

CMD uvicorn backend.main:app --host 0.0.0.0 --port $PORT

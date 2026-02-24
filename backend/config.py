"""
应用配置模块
从环境变量加载所有配置项
"""

import os
from dotenv import load_dotenv

load_dotenv()


# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Google Cloud
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Cloud Storage
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "vlogforge-artifacts")

# 服务
PORT = int(os.getenv("PORT", "8000"))

# 本地产物存储路径（开发阶段使用，部署后切换到 Cloud Storage）
ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# 视频时长 → 分段数映射
DURATION_SEGMENT_MAP = {
    "15s": {"segments": 3, "frames": 4},
    "30s": {"segments": 5, "frames": 6},
    "60s": {"segments": 10, "frames": 11},
}

# 平台 → 画面比例映射
PLATFORM_ASPECT_MAP = {
    "douyin": "9:16",
    "xiaohongshu": "9:16",
    "youtube": "16:9",
}

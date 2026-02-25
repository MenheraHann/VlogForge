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

# ========== 模型配置 ==========

# 文本生成模型（DA 脚本生成、ADA 文本分析）
TEXT_MODEL = "gemini-2.5-flash"

# 图片生成模型（Nano Banana：ADA 生图 + VA 图生图）
IMAGE_GEN_MODEL = "gemini-2.0-flash-exp"

# 视频生成模型（Veo 3.1：VGA 首段首帧视频）
VIDEO_GEN_MODEL = "veo-3.1-generate-001"

# 视频延长模型（Veo 3.1 Preview：支持视频延长，保持声音连贯）
VIDEO_EXTEND_MODEL = "veo-3.1-generate-preview"

# ========== 存储路径 ==========

# 本地产物存储路径（开发阶段使用，部署后切换到 Cloud Storage）
ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
os.makedirs(ARTIFACTS_DIR, exist_ok=True)

# 素材存储路径
ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
os.makedirs(ASSETS_DIR, exist_ok=True)

# ========== 视频参数映射 ==========

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

# ========== self_check 阈值 ==========

# 任一维度低于此值触发重跑（D6 决策）
SELF_CHECK_THRESHOLD = 3

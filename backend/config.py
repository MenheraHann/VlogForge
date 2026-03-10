"""
应用配置模块
从环境变量加载所有配置项
"""

import os
import logging
from dotenv import load_dotenv
from google import genai

load_dotenv()

logger = logging.getLogger(__name__)

# Gemini API
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Google Cloud
GOOGLE_CLOUD_PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# Cloud Storage（为空则不启用 GCS，开发环境无需配置）
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "").strip()
USE_GCS = bool(GCS_BUCKET_NAME)

# Cloud Run 检测（K_SERVICE 是 Cloud Run 自动注入的环境变量）
IS_CLOUD_RUN = bool(os.getenv("K_SERVICE"))

# 服务
PORT = int(os.getenv("PORT", "8000"))

# ========== Gemini 客户端（统一入口） ==========

# 优先使用 Vertex AI（不受地区限制），降级到 API Key
USE_VERTEX_AI = bool(GOOGLE_CLOUD_PROJECT)


def get_genai_client(location: str = "") -> genai.Client:
    """
    获取 Gemini 客户端（统一工厂方法）。
    - Vertex AI 模式：通过 GCP 认证，不受本地 IP 限制
    - API Key 模式：降级方案，受地区限制

    参数:
        location: Vertex AI 区域。视频/图片生成用 "global"，文本用 "us-central1"。
                  空字符串时使用 .env 中的 GOOGLE_CLOUD_LOCATION。
    """
    if USE_VERTEX_AI:
        loc = location or GOOGLE_CLOUD_LOCATION
        logger.info(f"[Config] 使用 Vertex AI 客户端: project={GOOGLE_CLOUD_PROJECT}, location={loc}")
        return genai.Client(
            vertexai=True,
            project=GOOGLE_CLOUD_PROJECT,
            location=loc,
        )
    else:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY 和 GOOGLE_CLOUD_PROJECT 均未配置")
        logger.info("[Config] 使用 API Key 客户端")
        return genai.Client(api_key=GEMINI_API_KEY)


# ========== 模型配置 ==========

# 文本生成模型（DA 脚本生成、ADA 文本分析）
TEXT_MODEL = "gemini-2.5-flash"

# 图片生成模型（Nano Banana — VA 图生图）
IMAGE_GEN_MODEL = "gemini-2.5-flash-image"

# 图片生成模型 Pro（Nano Banana Pro — ADA 人物生图，质量更高）
IMAGE_GEN_MODEL_PRO = "gemini-2.5-flash-preview-image"

# 视频生成模型（Veo 3.1 Preview：Vertex AI 支持首尾帧模式）
VIDEO_GEN_MODEL = "veo-3.1-generate-preview"

# ========== 存储路径 ==========

# Cloud Run 下使用 /tmp（容器文件系统只读），本地开发用项目目录
if IS_CLOUD_RUN:
    ARTIFACTS_DIR = "/tmp/artifacts"
    ASSETS_DIR = "/tmp/assets"
else:
    ARTIFACTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "artifacts")
    ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")

os.makedirs(ARTIFACTS_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)

# ========== 视频参数 ==========

# 每段视频时长（秒）
SEGMENT_DURATION = 6

# 分段数范围：最少 3 段（18s），最多 10 段（60s）
MIN_SEGMENTS = 3
MAX_SEGMENTS = 10

# 画面比例（仅支持竖屏）
ASPECT_RATIO = "9:16"

# ========== self_check 阈值 ==========

# 任一维度低于此值触发重跑（D6 决策）
SELF_CHECK_THRESHOLD = 4

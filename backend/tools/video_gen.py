"""
视频生成工具
封装 Veo 3.1 API 的视频生成能力

模式：首尾帧生成 — 基于首帧 + 尾帧 + prompt 生成视频片段

模型：veo-3.1-generate-preview（Vertex AI 模式，支持首尾帧）

注意：
- 必须使用 Vertex AI 客户端（Developer API 不支持 last_frame）
- Vertex AI 直接返回 video_bytes，无需 files.download
- person_generation 使用 "allow_adult"

用途：VGA 剪辑师用于并行生成视频片段
"""

import os
import asyncio
import logging

from google.genai import types

from backend.config import VIDEO_GEN_MODEL

logger = logging.getLogger(__name__)

# 轮询间隔（秒）
POLL_INTERVAL = 10
# 最大等待时间（秒）
MAX_WAIT_TIME = 300


def _get_vertex_client():
    """获取 Vertex AI 客户端（视频生成必须用 Vertex AI，Developer API 不支持 last_frame）"""
    from backend.config import GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
    from google import genai
    if not GOOGLE_CLOUD_PROJECT:
        raise RuntimeError("视频生成需要 GOOGLE_CLOUD_PROJECT（首尾帧模式仅 Vertex AI 支持）")
    return genai.Client(
        vertexai=True,
        project=GOOGLE_CLOUD_PROJECT,
        location=GOOGLE_CLOUD_LOCATION,
    )


async def generate_video_segment(
    first_frame: bytes,
    last_frame: bytes,
    description: str,
    output_path: str,
    aspect_ratio: str = "9:16",
    duration_seconds: int = 6,
) -> str:
    """
    使用 Veo 3.1 首尾帧模式生成视频片段（Vertex AI）。

    参数:
        first_frame: 首帧图片 bytes
        last_frame: 尾帧图片 bytes
        description: 视频描述（含动作 + 台词，Veo 据此生成语音）
        output_path: 视频输出路径
        aspect_ratio: 画面比例 (9:16 或 16:9)
        duration_seconds: 视频时长（4/6/8），默认 6s

    返回:
        输出视频文件路径
    """
    client = _get_vertex_client()
    logger.info(f"[VideoGen] 首尾帧模式: {description[:60]}...")

    operation = client.models.generate_videos(
        model=VIDEO_GEN_MODEL,
        prompt=description,
        image=types.Image(
            image_bytes=first_frame,
            mime_type="image/png",
        ),
        config=types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            duration_seconds=duration_seconds,
            number_of_videos=1,
            person_generation="allow_adult",
            last_frame=types.Image(
                image_bytes=last_frame,
                mime_type="image/png",
            ),
        ),
    )

    # 异步轮询等待完成
    elapsed = 0
    while not operation.done:
        if elapsed >= MAX_WAIT_TIME:
            raise TimeoutError(f"[VideoGen] 视频生成超时 ({MAX_WAIT_TIME}s)")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        operation = client.operations.get(operation)
        logger.info(f"[VideoGen] 轮询中... 已等待 {elapsed}s")

    # Vertex AI 直接返回 video_bytes，无需 files.download
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    for video in operation.result.generated_videos:
        video_bytes = video.video.video_bytes
        if not video_bytes:
            raise RuntimeError("[VideoGen] Vertex AI 未返回 video_bytes")
        with open(output_path, "wb") as f:
            f.write(video_bytes)
        logger.info(f"[VideoGen] 视频已保存: {output_path} ({len(video_bytes)} bytes)")
        return output_path

    raise RuntimeError("[VideoGen] Veo 未返回视频结果")

"""
视频生成工具
封装 Veo 3.1 API 的首尾帧视频生成能力

模型：veo-3.1-generate-001
特性：首帧 + 尾帧 → 插值视频，支持 generate_audio 语音生成
用途：VGA 剪辑师用于生成每个分段的视频片段
"""

import os
import asyncio
import logging

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY, VIDEO_GEN_MODEL

logger = logging.getLogger(__name__)

# 轮询间隔（秒）
POLL_INTERVAL = 10
# 最大等待时间（秒）
MAX_WAIT_TIME = 300


def _get_client() -> genai.Client:
    """获取 Gemini 客户端"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未配置，请在 .env 中设置")
    return genai.Client(api_key=GEMINI_API_KEY)


async def generate_video_segment(
    first_frame: bytes,
    last_frame: bytes,
    description: str,
    output_path: str,
    aspect_ratio: str = "9:16",
    generate_audio: bool = True,
) -> str:
    """
    使用 Veo 3.1 首尾帧功能生成视频片段。

    参数:
        first_frame: 首帧图片 bytes
        last_frame: 尾帧图片 bytes
        description: 视频描述（含动作 + 台词，Veo 据此生成语音）
        output_path: 视频输出路径
        aspect_ratio: 画面比例 (9:16 或 16:9)
        generate_audio: 是否生成语音

    返回:
        输出视频文件路径
    """
    client = _get_client()
    logger.info(f"[VideoGen] 开始生成视频: {description[:60]}...")

    operation = client.models.generate_videos(
        model=VIDEO_GEN_MODEL,
        prompt=description,
        reference_images=[
            types.RawReferenceImage(
                reference_id=1,
                reference_type="REFERENCE_TYPE_FIRST_FRAME",
                image=types.Image(
                    image_bytes=first_frame,
                    mime_type="image/png",
                ),
            ),
            types.RawReferenceImage(
                reference_id=2,
                reference_type="REFERENCE_TYPE_LAST_FRAME",
                image=types.Image(
                    image_bytes=last_frame,
                    mime_type="image/png",
                ),
            ),
        ],
        config=types.GenerateVideoConfig(
            generate_audio=generate_audio,
            aspect_ratio=aspect_ratio,
            number_of_videos=1,
            person_generation="allow_all",
        ),
    )

    # 异步轮询等待完成
    elapsed = 0
    while not operation.done:
        if elapsed >= MAX_WAIT_TIME:
            raise TimeoutError(f"[VideoGen] 视频生成超时 ({MAX_WAIT_TIME}s)")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        operation = client.operations.get(name=operation.name)
        logger.info(f"[VideoGen] 轮询中... 已等待 {elapsed}s")

    # 下载生成的视频
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    for video in operation.result.generated_videos:
        client.files.download(file=video.video, download_path=output_path)
        logger.info(f"[VideoGen] 视频已保存: {output_path}")
        return output_path

    raise RuntimeError("[VideoGen] Veo 未返回视频结果")


async def generate_video_from_first_frame(
    first_frame: bytes,
    description: str,
    output_path: str,
    aspect_ratio: str = "9:16",
    generate_audio: bool = True,
) -> str:
    """
    仅使用首帧生成视频（无尾帧约束，备用模式）。

    参数:
        first_frame: 首帧图片 bytes
        description: 视频描述
        output_path: 视频输出路径
        aspect_ratio: 画面比例
        generate_audio: 是否生成语音

    返回:
        输出视频文件路径
    """
    client = _get_client()
    logger.info(f"[VideoGen] 首帧模式: {description[:60]}...")

    operation = client.models.generate_videos(
        model=VIDEO_GEN_MODEL,
        prompt=description,
        image=types.Image(
            image_bytes=first_frame,
            mime_type="image/png",
        ),
        config=types.GenerateVideoConfig(
            generate_audio=generate_audio,
            aspect_ratio=aspect_ratio,
            number_of_videos=1,
            person_generation="allow_all",
        ),
    )

    elapsed = 0
    while not operation.done:
        if elapsed >= MAX_WAIT_TIME:
            raise TimeoutError(f"[VideoGen] 视频生成超时 ({MAX_WAIT_TIME}s)")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL
        operation = client.operations.get(name=operation.name)
        logger.info(f"[VideoGen] 轮询中... 已等待 {elapsed}s")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    for video in operation.result.generated_videos:
        client.files.download(file=video.video, download_path=output_path)
        logger.info(f"[VideoGen] 视频已保存: {output_path}")
        return output_path

    raise RuntimeError("[VideoGen] Veo 未返回视频结果")

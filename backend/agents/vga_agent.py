"""
VGA Agent - 剪辑师（Video Generation Agent）
负责：使用 Veo 3.1 的首尾帧功能生成视频片段
v4 架构：每个片段由相邻两张分镜图 + veo_description 生成

工作流：
  视频 N = 帧 N（首帧） + 帧 N+1（尾帧） + 分段 N 的 veo_description
  → Veo 3.1 生成 4~8 秒视频，自带语音
  可并行生成多个片段
"""

import os
import asyncio
import logging

from backend.models import ScriptOutput
from backend.tools.video_gen import generate_video_segment

logger = logging.getLogger(__name__)

# 并行生成的最大数量（避免 API 限流）
MAX_CONCURRENT = 3


async def generate_segments(
    script: ScriptOutput,
    storyboard_paths: list[str],
    output_dir: str,
    aspect_ratio: str = "9:16",
) -> list[str]:
    """
    根据分镜图生成所有视频片段。

    参数:
        script: DA 输出的脚本（含 veo_description）
        storyboard_paths: 分镜图路径列表（N+1 张，由 VA 生成）
        output_dir: 视频片段输出目录
        aspect_ratio: 画面比例

    返回:
        视频片段路径列表（N 段）
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments

    if len(storyboard_paths) != len(segments) + 1:
        raise ValueError(
            f"分镜图数量不匹配: 需要 {len(segments) + 1} 帧, 实际 {len(storyboard_paths)} 帧"
        )

    logger.info(
        f"[VGA] 开始生成视频片段: {len(segments)} 段, "
        f"并行数={MAX_CONCURRENT}, 比例={aspect_ratio}"
    )

    # 准备所有生成任务
    tasks = []
    for i, seg in enumerate(segments):
        first_frame_path = storyboard_paths[i]
        last_frame_path = storyboard_paths[i + 1]
        output_path = os.path.join(output_dir, f"segment_{seg.segment_id:03d}.mp4")

        tasks.append({
            "segment_id": seg.segment_id,
            "first_frame_path": first_frame_path,
            "last_frame_path": last_frame_path,
            "description": seg.veo_description,
            "output_path": output_path,
            "aspect_ratio": aspect_ratio,
        })

    # 使用信号量控制并行度
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)
    segment_paths = [None] * len(tasks)

    async def _generate_one(idx: int, task: dict):
        async with semaphore:
            logger.info(
                f"[VGA] 片段 {task['segment_id']}: 开始生成 "
                f"({task['first_frame_path']} → {task['last_frame_path']})"
            )

            # 读取首尾帧图片
            with open(task["first_frame_path"], "rb") as f:
                first_frame = f.read()
            with open(task["last_frame_path"], "rb") as f:
                last_frame = f.read()

            path = await generate_video_segment(
                first_frame=first_frame,
                last_frame=last_frame,
                description=task["description"],
                output_path=task["output_path"],
                aspect_ratio=task["aspect_ratio"],
            )

            segment_paths[idx] = path
            logger.info(f"[VGA] 片段 {task['segment_id']}: 生成完成 → {path}")

    # 并行执行
    await asyncio.gather(
        *[_generate_one(i, t) for i, t in enumerate(tasks)]
    )

    # 验证所有片段都已生成
    failed = [i + 1 for i, p in enumerate(segment_paths) if p is None]
    if failed:
        raise RuntimeError(f"[VGA] 以下片段生成失败: {failed}")

    logger.info(f"[VGA] 所有视频片段生成完成: {len(segment_paths)} 段")
    return segment_paths

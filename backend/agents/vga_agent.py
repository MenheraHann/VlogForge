"""
VGA Agent - 剪辑师（Video Generation Agent）
负责：使用 Veo 3.1 链式延长生成连贯视频

v5 架构（声音连贯方案）：
  片段1 = 首帧图 + prompt → generate_video_from_first_frame（建立声音基调）
  片段2 = 片段1视频 + prompt → extend_video（声音延续）
  片段3 = 片段2视频 + prompt → extend_video（声音延续）
  ...

串行生成，每段基于上一段延长，保持声音、人物、场景的连贯性。
最终输出的每段视频独立保存，由 FFmpeg 拼接。
"""

import os
import logging
from typing import Callable, Optional

from backend.models import ScriptOutput
from backend.tools.video_gen import generate_video_from_first_frame, extend_video

logger = logging.getLogger(__name__)

# 每段视频的默认时长（秒）
DEFAULT_SEGMENT_DURATION = 8


async def generate_segments(
    script: ScriptOutput,
    storyboard_paths: list[str],
    output_dir: str,
    aspect_ratio: str = "9:16",
    voice_anchor: str = "",
    on_segment_done: Optional[Callable[[int, int], None]] = None,
) -> list[str]:
    """
    链式延长生成所有视频片段。

    参数:
        script: DA 输出的脚本（含 veo_description）
        storyboard_paths: 分镜图路径列表（首帧图用于第一段）
        output_dir: 视频片段输出目录
        aspect_ratio: 画面比例
        voice_anchor: DA 生成的声音锚定描述，会加到每段 prompt 前面
        on_segment_done: 每段完成时的回调 (当前索引, 总数)

    返回:
        视频片段路径列表（N 段）
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments
    segment_paths = []

    logger.info(
        f"[VGA] 开始链式延长生成: {len(segments)} 段, 比例={aspect_ratio}"
    )

    for i, seg in enumerate(segments):
        output_path = os.path.join(output_dir, f"segment_{seg.segment_id:03d}.mp4")

        # 构建 prompt：声音锚定 + 原始 veo_description
        prompt = _build_prompt(seg.veo_description, voice_anchor)

        if i == 0:
            # ===== 首段：使用首帧图片生成 =====
            if not storyboard_paths:
                raise ValueError("[VGA] 分镜图列表为空，无法获取首帧")

            first_frame_path = storyboard_paths[0]
            logger.info(
                f"[VGA] 片段 {seg.segment_id}: 首帧模式 ({first_frame_path})"
            )

            with open(first_frame_path, "rb") as f:
                first_frame = f.read()

            path = await generate_video_from_first_frame(
                first_frame=first_frame,
                description=prompt,
                output_path=output_path,
                aspect_ratio=aspect_ratio,
                duration_seconds=DEFAULT_SEGMENT_DURATION,
            )
        else:
            # ===== 后续段：基于上一段视频延长 =====
            prev_video_path = segment_paths[-1]
            logger.info(
                f"[VGA] 片段 {seg.segment_id}: 延长模式 (基于片段 {segments[i-1].segment_id})"
            )

            path = await extend_video(
                source_video_path=prev_video_path,
                description=prompt,
                output_path=output_path,
                duration_seconds=DEFAULT_SEGMENT_DURATION,
            )

        segment_paths.append(path)
        logger.info(
            f"[VGA] 片段 {seg.segment_id}: 完成 ({i+1}/{len(segments)}) → {path}"
        )

        # 进度回调
        if on_segment_done:
            on_segment_done(i, len(segments))

    logger.info(f"[VGA] 所有视频片段生成完成: {len(segment_paths)} 段")
    return segment_paths


def _build_prompt(veo_description: str, voice_anchor: str) -> str:
    """
    构建完整的 Veo prompt，将声音锚定描述放在最前面。

    声音锚定描述放在 prompt 开头，让 Veo 优先感知声音特征，
    增加跨片段声音一致性的概率。
    """
    if voice_anchor:
        return f"{voice_anchor}\n\n{veo_description}"
    return veo_description

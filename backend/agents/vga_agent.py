"""
VGA Agent - 剪辑师（Video Generation Agent）
负责：使用 Veo 3.1 首尾帧模式生成视频 + 智能裁切

v7 架构（Vertex AI 首尾帧并行 + 智能裁切）：
  所有片段 = 首帧图 + 尾帧图 + prompt → generate_video_segment（可并行）
  每段生成后 → smart_trim_to_target（裁掉尾部漂移）
  最后 → FFmpeg 拼接

注意：首尾帧模式仅 Vertex AI 支持，Developer API 不支持 last_frame。
"""

import os
import asyncio
import logging
from typing import Callable, Optional

from backend.models import ScriptOutput
from backend.tools.video_gen import generate_video_segment
from backend.tools.ffmpeg_tools import smart_trim_to_target

logger = logging.getLogger(__name__)

# 每段视频的时长（秒）—— 6s 缩短漂移，配合 3-4s 旁白
DEFAULT_SEGMENT_DURATION = 6

# 最大并行生成数（避免 API 限流）
MAX_CONCURRENT = 3


async def generate_segments(
    script: ScriptOutput,
    storyboard_paths: list[str],
    output_dir: str,
    aspect_ratio: str = "9:16",
    voice_anchor: str = "",
    on_segment_done: Optional[Callable[[int, int, str], None]] = None,
) -> list[str]:
    """
    首尾帧并行生成所有视频片段 + 智能裁切。

    参数:
        script: DA 输出的脚本（含 veo_description）
        storyboard_paths: 分镜图路径列表（N+1 张，N = 分段数）
        output_dir: 视频片段输出目录
        aspect_ratio: 画面比例
        voice_anchor: DA 生成的声音锚定描述，会加到每段 prompt 前面
        on_segment_done: 每段完成时的回调 (当前索引, 总数, 片段路径)

    返回:
        视频片段路径列表（按顺序排列，已裁切）
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments
    total = len(segments)

    # 校验分镜图数量：需要 N+1 张（每段首帧 + 最后一段尾帧）
    if len(storyboard_paths) < total + 1:
        raise ValueError(
            f"[VGA] 分镜图不足: 需要 {total + 1} 张，实际 {len(storyboard_paths)} 张"
        )

    logger.info(
        f"[VGA] Vertex AI 首尾帧并行模式: {total} 段, 比例={aspect_ratio}, "
        f"并发上限={MAX_CONCURRENT}"
    )

    # 记录完成进度（用于并行场景下的回调）
    done_count = 0
    done_lock = asyncio.Lock()

    async def _generate_one(i: int) -> str:
        """生成单段视频（首尾帧 + 智能裁切）"""
        nonlocal done_count

        seg = segments[i]
        raw_path = os.path.join(output_dir, f"segment_{seg.segment_id:03d}_raw.mp4")
        trimmed_path = os.path.join(output_dir, f"segment_{seg.segment_id:03d}.mp4")

        # 读取首帧和尾帧
        first_frame_path = storyboard_paths[i]
        last_frame_path = storyboard_paths[i + 1]

        with open(first_frame_path, "rb") as f:
            first_frame = f.read()
        with open(last_frame_path, "rb") as f:
            last_frame = f.read()

        # 构建 prompt：声音锚定 + veo_description
        prompt = _build_prompt(seg.veo_description, voice_anchor)

        logger.info(
            f"[VGA] 片段 {seg.segment_id}: 首帧={os.path.basename(first_frame_path)}, "
            f"尾帧={os.path.basename(last_frame_path)}"
        )

        # ① Veo 首尾帧生成（Vertex AI）
        await generate_video_segment(
            first_frame=first_frame,
            last_frame=last_frame,
            description=prompt,
            output_path=raw_path,
            aspect_ratio=aspect_ratio,
            duration_seconds=DEFAULT_SEGMENT_DURATION,
        )

        # ② 智能裁切（对比尾帧图片，截掉漂移部分）
        await smart_trim_to_target(
            video_path=raw_path,
            target_frame_path=last_frame_path,
            output_path=trimmed_path,
        )

        # 清理原始文件（节省空间）
        if os.path.exists(raw_path) and raw_path != trimmed_path:
            os.remove(raw_path)

        # 更新进度
        async with done_lock:
            done_count += 1
            logger.info(
                f"[VGA] 片段 {seg.segment_id}: 完成 ({done_count}/{total})"
            )
            if on_segment_done:
                on_segment_done(done_count - 1, total, trimmed_path)

        return trimmed_path

    # 使用信号量控制并发数，避免 API 限流
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _generate_with_limit(i: int) -> tuple[int, str]:
        async with semaphore:
            path = await _generate_one(i)
            return i, path

    # 并行生成所有片段
    tasks = [_generate_with_limit(i) for i in range(total)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 按原始顺序整理结果
    ordered_paths = [""] * total
    errors = []

    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
            logger.error(f"[VGA] 片段生成失败: {result}")
        else:
            idx, path = result
            ordered_paths[idx] = path

    # 过滤掉失败的片段
    final_paths = [p for p in ordered_paths if p]

    if errors:
        logger.warning(
            f"[VGA] {len(errors)}/{total} 段生成失败: {errors[:3]}"
        )

    if not final_paths:
        raise RuntimeError(f"[VGA] 所有视频片段生成失败: {errors}")

    logger.info(f"[VGA] 视频片段生成完成: {len(final_paths)}/{total} 段成功")
    return final_paths


def _build_prompt(veo_description: str, voice_anchor: str) -> str:
    """
    构建完整的 Veo prompt，将声音锚定描述放在最前面。

    声音锚定描述放在 prompt 开头，让 Veo 优先感知声音特征，
    增加跨片段声音一致性的概率。
    """
    if voice_anchor:
        return f"{voice_anchor}\n\n{veo_description}"
    return veo_description

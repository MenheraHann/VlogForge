"""
Compositor Service — 游戏画面视频合成
创建第 3 段视频：高斯模糊的玩手机背景 + 游戏画面叠加层

流程：
1. ffprobe 获取游戏视频时长和尺寸
2. 根据横竖屏计算游戏画面缩放尺寸和居中位置
3. FFmpeg: 静态图片循环作背景 → 高斯模糊(sigma=30) → 叠加缩放后的游戏画面
4. 输出 H.264 30fps 视频
"""

import asyncio
import json
import os
import logging
import subprocess

logger = logging.getLogger(__name__)


async def compose_gameplay_segment(
    playing_phone_image: str,
    gameplay_video: str,
    orientation: str,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920,
) -> str:
    """
    合成游戏画面段（Segment 3）视频。

    处理流程：
    1. 使用 ffprobe 获取游戏视频的时长和尺寸
    2. 根据游戏画面方向计算缩放尺寸和居中位置：
       - portrait（竖屏）: 居中，高度 = 目标高度的 50%
       - landscape（横屏）: 居中，宽度 ≤ 目标宽度
    3. FFmpeg: 循环静态图片作为背景，施加高斯模糊（sigma=30），
       叠加缩放后的游戏画面居中显示
    4. 输出 H.264 编码、30fps 的视频

    Args:
        playing_phone_image: VA 生成的"人物玩手机"静态图片路径
        gameplay_video: 用户上传的游戏录屏路径
        orientation: "portrait" 或 "landscape"
        output_path: 输出视频文件路径
        target_width: 最终视频宽度（默认 1080，9:16 竖屏）
        target_height: 最终视频高度（默认 1920，9:16 竖屏）

    Returns:
        输出视频文件路径

    Raises:
        FileNotFoundError: 输入文件不存在
        RuntimeError: ffprobe 或 ffmpeg 执行失败
    """
    # ---- 输入文件校验 ----
    if not os.path.isfile(playing_phone_image):
        raise FileNotFoundError(
            f"[Compositor] playing_phone_image not found: {playing_phone_image}"
        )
    if not os.path.isfile(gameplay_video):
        raise FileNotFoundError(
            f"[Compositor] gameplay_video not found: {gameplay_video}"
        )

    # ---- Step 1: ffprobe 获取游戏视频时长 ----
    logger.info(f"[Compositor] Probing gameplay video: {gameplay_video}")
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", gameplay_video,
    ]
    proc = await asyncio.create_subprocess_exec(
        *probe_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode().strip() if stderr else "unknown error"
        raise RuntimeError(f"[Compositor] ffprobe failed (rc={proc.returncode}): {err_msg}")

    probe_data = json.loads(stdout.decode())
    duration = float(probe_data["format"]["duration"])
    logger.info(f"[Compositor] Gameplay video duration: {duration:.2f}s")

    # ---- Step 2: 根据横竖屏计算游戏画面缩放参数 ----
    if orientation == "landscape":
        # 横屏游戏：宽度 = 目标宽度，高度按比例缩放
        scale_filter = (
            f"scale={target_width}:-1:"
            f"force_original_aspect_ratio=decrease,"
            f"pad=ceil(iw/2)*2:ceil(ih/2)*2"
        )
        logger.info(f"[Compositor] Landscape mode: scale width to {target_width}")
    else:
        # 竖屏游戏（默认）：高度 = 目标高度的 50%，宽度按比例缩放
        game_height = target_height // 2
        scale_filter = (
            f"scale=-1:{game_height}:"
            f"force_original_aspect_ratio=decrease,"
            f"pad=ceil(iw/2)*2:ceil(ih/2)*2"
        )
        logger.info(f"[Compositor] Portrait mode: scale height to {game_height}")

    # ---- Step 3: 构建 FFmpeg filter_complex ----
    filter_complex = (
        f"[0:v]scale={target_width}:{target_height},gblur=sigma=30[bg];"
        f"[1:v]{scale_filter}[game];"
        f"[bg][game]overlay=(W-w)/2:(H-h)/2[out]"
    )

    # ---- Step 4: 执行 FFmpeg 合成 ----
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", playing_phone_image,
        "-i", gameplay_video,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-t", str(duration),
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-r", "30", "-pix_fmt", "yuv420p",
        output_path,
    ]

    logger.info(f"[Compositor] Running FFmpeg: output={output_path}")
    logger.debug(f"[Compositor] FFmpeg command: {' '.join(ffmpeg_cmd)}")

    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        err_msg = stderr.decode().strip() if stderr else "unknown error"
        logger.error(f"[Compositor] FFmpeg failed (rc={proc.returncode}): {err_msg}")
        raise RuntimeError(
            f"[Compositor] FFmpeg compositing failed (rc={proc.returncode}): {err_msg}"
        )

    logger.info(f"[Compositor] Compositing complete: {output_path}")
    return output_path

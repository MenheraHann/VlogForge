"""
FFmpeg 视频拼接工具
负责将多个视频片段拼接为最终输出视频

功能：
- 串接多段 .mp4 视频
- 裁掉相邻片段的重复首帧（保证画面不卡顿）
- 输出最终视频文件
"""

import os
import logging
import tempfile
import subprocess

logger = logging.getLogger(__name__)


def _check_ffmpeg():
    """检查 FFmpeg 是否已安装"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("FFmpeg 返回非零状态")
    except FileNotFoundError:
        raise RuntimeError("FFmpeg 未安装，请执行: brew install ffmpeg")


async def stitch_segments(
    segment_paths: list[str],
    output_path: str,
    trim_overlap_frames: bool = True,
) -> str:
    """
    将多个视频片段拼接为一个完整视频。

    参数:
        segment_paths: 视频片段路径列表（按顺序排列）
        output_path: 输出文件路径
        trim_overlap_frames: 是否裁掉相邻片段首尾重复帧

    返回:
        输出视频文件路径
    """
    _check_ffmpeg()

    if not segment_paths:
        raise ValueError("视频片段列表为空")

    if len(segment_paths) == 1:
        _copy_file(segment_paths[0], output_path)
        return output_path

    logger.info(f"[FFmpeg] 开始拼接 {len(segment_paths)} 个片段 → {output_path}")

    if trim_overlap_frames:
        trimmed_paths = await _trim_overlaps(segment_paths)
    else:
        trimmed_paths = segment_paths

    concat_file = _create_concat_file(trimmed_paths)

    try:
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-c", "copy",
            "-movflags", "+faststart",
            output_path,
        ]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            logger.error(f"[FFmpeg] 拼接失败: {result.stderr}")
            raise RuntimeError(f"FFmpeg 拼接失败: {result.stderr}")

        logger.info(f"[FFmpeg] 拼接完成: {output_path}")
        return output_path

    finally:
        os.unlink(concat_file)
        if trim_overlap_frames:
            for p in trimmed_paths:
                if p not in segment_paths and os.path.exists(p):
                    os.unlink(p)


async def _trim_overlaps(segment_paths: list[str]) -> list[str]:
    """
    裁掉第 2 个及之后片段的首帧。
    相邻片段共享一帧：上一段的尾帧 = 下一段的首帧，需要裁掉避免重复。
    """
    trimmed = [segment_paths[0]]

    for i, path in enumerate(segment_paths[1:], start=1):
        trimmed_path = path.replace(".mp4", "_trimmed.mp4")

        cmd = [
            "ffmpeg", "-y",
            "-i", path,
            "-ss", "0.04",
            "-c", "copy",
            trimmed_path,
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.warning(f"[FFmpeg] 裁帧失败，使用原片段: {result.stderr}")
            trimmed.append(path)
        else:
            trimmed.append(trimmed_path)

    return trimmed


def _create_concat_file(paths: list[str]) -> str:
    """创建 FFmpeg concat demuxer 所需的列表文件"""
    fd, concat_path = tempfile.mkstemp(suffix=".txt", prefix="ffmpeg_concat_")
    with os.fdopen(fd, "w") as f:
        for path in paths:
            escaped = path.replace("'", "'\\''")
            f.write(f"file '{escaped}'\n")
    return concat_path


def _copy_file(src: str, dst: str):
    """复制文件"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(src, "rb") as f_in:
        with open(dst, "wb") as f_out:
            f_out.write(f_in.read())


async def get_video_duration(path: str) -> float:
    """获取视频时长（秒）"""
    cmd = [
        "ffprobe",
        "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe 失败: {result.stderr}")
    return float(result.stdout.strip())

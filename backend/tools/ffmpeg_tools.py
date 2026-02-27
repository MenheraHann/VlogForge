"""
FFmpeg 视频处理工具
负责：智能裁切（首尾帧模式） + 视频拼接

功能：
- 智能裁切：提取视频尾部帧，对比目标尾帧图片，在最佳匹配点截断
- 串接多段 .mp4 视频
- 裁掉相邻片段的重复首帧（保证画面不卡顿）
- 输出最终视频文件
"""

import io
import os
import logging
import tempfile
import subprocess

from PIL import Image, ImageChops, ImageStat

logger = logging.getLogger(__name__)

# 智能裁切参数
TRIM_SEARCH_SECONDS = 3.0   # 从视频末尾往前搜索多少秒
TRIM_FRAME_RATE = 12         # 提取帧的采样率（不需要全帧率，12fps 够用）
TRIM_COMPARE_SIZE = 256      # 对比用的缩放尺寸（越小越快）


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
        # 重编码拼接：强制统一帧率/编码，解决 Veo VFR 视频拼接后时长异常的问题
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_file,
            "-r", "30",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            output_path,
        ]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)

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
            "-ss", "0.04",
            "-i", path,
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
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


# ========== 智能裁切（首尾帧模式核心） ==========


def _image_mse(img_a: Image.Image, img_b: Image.Image) -> float:
    """
    计算两张图片的 MSE（均方误差），越低越相似。
    使用 Pillow 内置的 ImageChops + ImageStat，无需 numpy。
    输入图片应已缩放到相同尺寸并转为灰度。
    """
    diff = ImageChops.difference(img_a, img_b)
    stat = ImageStat.Stat(diff)
    # stat.rms 返回每个通道的均方根值，灰度图只有一个通道
    # rms^2 即为 MSE
    return stat.rms[0] ** 2


def _load_and_prepare(image_bytes: bytes) -> Image.Image:
    """加载图片并缩放+灰度化，用于快速对比"""
    img = Image.open(io.BytesIO(image_bytes))
    return img.resize((TRIM_COMPARE_SIZE, TRIM_COMPARE_SIZE)).convert("L")


async def smart_trim_to_target(
    video_path: str,
    target_frame_path: str,
    output_path: str,
) -> str:
    """
    智能裁切：在视频尾部找到最接近目标尾帧的帧，在该时间点截断。

    解决 Veo 首尾帧模式的尾帧漂移问题：
    - Veo 生成 6s 视频时，目标尾帧可能在 ~5s 就出现，之后 ~1s 是 AI 自由发挥
    - 本函数在尾部搜索最匹配的帧，截断多余部分

    参数:
        video_path: 输入视频路径
        target_frame_path: 目标尾帧图片路径（VA 生成的分镜图）
        output_path: 裁切后的视频输出路径

    返回:
        输出视频路径
    """
    _check_ffmpeg()

    # 获取视频总时长
    duration = await get_video_duration(video_path)
    search_start = max(0, duration - TRIM_SEARCH_SECONDS)

    logger.info(
        f"[SmartTrim] 开始: 视频={video_path}, 时长={duration:.1f}s, "
        f"搜索区间={search_start:.1f}s~{duration:.1f}s"
    )

    # 加载目标尾帧
    with open(target_frame_path, "rb") as f:
        target_img = _load_and_prepare(f.read())

    # 用 FFmpeg 提取搜索区间内的帧
    with tempfile.TemporaryDirectory(prefix="smart_trim_") as tmp_dir:
        frame_pattern = os.path.join(tmp_dir, "frame_%04d.png")

        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{search_start:.3f}",
            "-i", video_path,
            "-vf", f"fps={TRIM_FRAME_RATE}",
            "-q:v", "2",
            frame_pattern,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            logger.warning(f"[SmartTrim] 帧提取失败，使用原视频: {result.stderr}")
            _copy_file(video_path, output_path)
            return output_path

        # 收集提取的帧文件
        frame_files = sorted([
            f for f in os.listdir(tmp_dir) if f.startswith("frame_") and f.endswith(".png")
        ])

        if not frame_files:
            logger.warning("[SmartTrim] 未提取到帧，使用原视频")
            _copy_file(video_path, output_path)
            return output_path

        # 逐帧计算 MSE，找最小值
        best_mse = float("inf")
        best_idx = 0

        for idx, fname in enumerate(frame_files):
            fpath = os.path.join(tmp_dir, fname)
            with open(fpath, "rb") as f:
                frame_img = _load_and_prepare(f.read())
            mse = _image_mse(frame_img, target_img)
            if mse < best_mse:
                best_mse = mse
                best_idx = idx

        # 计算最佳匹配帧的时间点
        best_time = search_start + best_idx / TRIM_FRAME_RATE

        logger.info(
            f"[SmartTrim] 最佳匹配: 帧 {best_idx}/{len(frame_files)}, "
            f"时间={best_time:.2f}s, MSE={best_mse:.1f}"
        )

        # 如果最佳帧就在最后 0.2s 内，不需要裁切
        if duration - best_time < 0.2:
            logger.info("[SmartTrim] 尾帧已在视频末尾，无需裁切")
            _copy_file(video_path, output_path)
            return output_path

        # 在最佳帧时间点 +0.04s（多留一帧余量）处截断
        trim_time = best_time + 0.04

        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-t", f"{trim_time:.3f}",
            "-r", "30",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            output_path,
        ]

        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            logger.warning(f"[SmartTrim] 裁切失败，使用原视频: {result.stderr}")
            _copy_file(video_path, output_path)
            return output_path

        trimmed_duration = await get_video_duration(output_path)
        logger.info(
            f"[SmartTrim] 裁切完成: {duration:.1f}s → {trimmed_duration:.1f}s "
            f"(截掉 {duration - trimmed_duration:.1f}s 漂移)"
        )
        return output_path

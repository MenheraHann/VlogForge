"""
FFmpeg 视频处理工具
负责视频片段拼接、重复帧裁剪、音频归一化
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D11 实现
# - stitch_videos(segment_paths, output_path) -> str
#   1. 裁掉相邻片段的重复帧（尾帧N = 首帧N+1）
#   2. 串联所有片段
#   3. 音频归一化
#   4. 输出最终 MP4

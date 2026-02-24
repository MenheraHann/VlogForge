"""
视频生成工具
封装 Veo 3.1 API 调用，支持首尾帧功能和异步轮询
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D9 实现
# - generate_segment(first_frame, last_frame, description, aspect_ratio) -> str (video path)
# - 异步轮询 Veo 生成状态
# - 下载生成的视频文件

"""
VGA Agent - 剪辑师（Video Gen Agent）
负责：使用 Veo 3.1 的首尾帧功能生成视频片段
每个片段由相邻两张分镜图 + 动作/台词描述生成
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D9-D10 实现
# - 调用 Veo 3.1 API，传入首帧图片 + 尾帧图片 + 描述
# - 异步轮询等待生成完成
# - 支持并行生成多个片段
# - 下载生成的视频文件

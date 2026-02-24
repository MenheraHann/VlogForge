"""
DA Agent - 创意总监（Decision Agent）
负责：接收用户输入 → 拆解任务 → 调度 Sub-Agent → 验收 → 拼接输出
是整个流水线的编排核心，对用户的唯一出口
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D3 实现
# - 接收 job_data，提取参数
# - 调用 TA 生成脚本
# - 检查脚本质量
# - 调用 VA 生成分镜图
# - 调用 VGA 生成视频片段
# - 调用 QA 审核
# - 调用 FFmpeg 拼接
# - 更新 job 状态

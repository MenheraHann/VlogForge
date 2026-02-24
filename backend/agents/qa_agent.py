"""
QA Agent - 质控（Review Agent）
负责：审核生成的视频片段质量
检查画面瑕疵、场景一致性、与脚本的匹配度
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D12 实现
# - 提取视频关键帧
# - 用 Gemini 多模态理解分析画面质量
# - 比对生成结果与预期分镜图
# - 输出通过/不通过 + 问题描述

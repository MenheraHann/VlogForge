"""
TA Agent - 脚本策划（Text Agent）
负责：根据用户输入生成 vlog 脚本 + 分镜提示词 + 风格指南
输出结构化 JSON，供 VA 和 VGA 使用
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D2 实现
# - 系统提示词设计
# - 调用 Gemini 文本生成
# - 解析 JSON 输出为 ScriptOutput 模型
# - 确保帧提示词链式衔接（首帧N+1 = 尾帧N）
# - 标记需要产品植入的帧

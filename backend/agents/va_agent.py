"""
VA Agent - 美术指导（Visual Agent）
负责：使用 Gemini 原生图片生成（Nano Banana）生成分镜图
支持产品参考图植入
"""

import logging

logger = logging.getLogger(__name__)

# TODO: D5-D7 实现
# - 调用 Gemini generate_content 的图片生成模式
# - 普通帧：风格指南 + 提示词 → 图片
# - 产品帧：风格指南 + 提示词 + 产品参考图 → 图片
# - 顺序生成，传入前序图片维持风格一致性

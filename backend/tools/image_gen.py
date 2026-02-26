"""
图片生成工具
封装 Gemini 原生图片生成能力
支持：文生图（text2img）+ 图生图（img2img）+ 交错输出

模型：gemini-2.0-flash-preview-image-generation（支持 response_modalities=["IMAGE", "TEXT"]）
用途：ADA 生成素材图 / VA 链式图生图
"""

import os
import logging
from typing import Optional

from google.genai import types

from backend.config import get_genai_client, IMAGE_GEN_MODEL

logger = logging.getLogger(__name__)


def _get_client():
    """获取 Gemini 客户端（图片生成用 global）"""
    return get_genai_client(location="global")


def _extract_image_from_response(response) -> bytes:
    """从 Gemini 响应中提取第一张图片"""
    if not response.candidates:
        raise RuntimeError("Gemini 响应无 candidates（可能被安全过滤拦截）")
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            if part.inline_data.mime_type.startswith("image/"):
                return part.inline_data.data
    raise RuntimeError("Gemini 响应中未包含图片")


def _extract_text_from_response(response) -> str:
    """从 Gemini 响应中提取文本"""
    if not response.candidates:
        return ""
    texts = []
    for part in response.candidates[0].content.parts:
        if hasattr(part, "text") and part.text:
            texts.append(part.text)
    return "\n".join(texts)


def _extract_all_images_from_response(response) -> list[bytes]:
    """从 Gemini 响应中提取所有图片"""
    if not response.candidates:
        return []
    images = []
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data:
            if part.inline_data.mime_type.startswith("image/"):
                images.append(part.inline_data.data)
    return images


async def text_to_image(
    prompt: str,
    system_instruction: str = "",
) -> bytes:
    """
    文本生成图片（text2img）。

    参数:
        prompt: 图片描述提示词
        system_instruction: 系统指令（可选）

    返回:
        图片 bytes（PNG 格式）
    """
    client = _get_client()
    logger.info(f"[ImageGen] text2img: {prompt[:80]}...")

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
    )
    if system_instruction:
        config.system_instruction = system_instruction

    response = await client.aio.models.generate_content(
        model=IMAGE_GEN_MODEL,
        contents=prompt,
        config=config,
    )

    image_data = _extract_image_from_response(response)
    logger.info(f"[ImageGen] text2img 完成，图片大小={len(image_data)} bytes")
    return image_data


async def image_to_image(
    input_images: list[bytes],
    prompt: str,
    system_instruction: str = "",
) -> bytes:
    """
    图生图（img2img），基于输入图片和提示词生成新图片。
    用于 VA 链式图生图：前一帧 + 帧提示词 → 下一帧。

    参数:
        input_images: 输入图片 bytes 列表（可传多张，如素材图组合）
        prompt: 图片修改/生成提示词
        system_instruction: 系统指令（可选）

    返回:
        生成的图片 bytes（PNG 格式）
    """
    client = _get_client()
    logger.info(f"[ImageGen] img2img: {len(input_images)} 张输入图, prompt={prompt[:80]}...")

    # 构建多模态输入：文本 + 图片
    contents = [prompt]
    for img_bytes in input_images:
        contents.append(
            types.Part.from_bytes(data=img_bytes, mime_type="image/png")
        )

    config = types.GenerateContentConfig(
        response_modalities=["IMAGE", "TEXT"],
    )
    if system_instruction:
        config.system_instruction = system_instruction

    response = await client.aio.models.generate_content(
        model=IMAGE_GEN_MODEL,
        contents=contents,
        config=config,
    )

    image_data = _extract_image_from_response(response)
    logger.info(f"[ImageGen] img2img 完成，图片大小={len(image_data)} bytes")
    return image_data


async def generate_with_interleaved_output(
    prompt: str,
    input_images: Optional[list[bytes]] = None,
    system_instruction: str = "",
) -> tuple[str, list[bytes]]:
    """
    交错输出模式：返回文本 + 图片混合结果。
    满足 Creative Storyteller 赛道对 interleaved output 的要求。
    用于 ADA 素材创建（同时输出分析文本和生成图片）。

    参数:
        prompt: 提示词
        input_images: 输入图片（可选）
        system_instruction: 系统指令（可选）

    返回:
        (text, images): 文本描述 + 图片列表
    """
    client = _get_client()
    logger.info(f"[ImageGen] interleaved: prompt={prompt[:80]}...")

    if input_images:
        contents = [prompt]
        for img_bytes in input_images:
            contents.append(
                types.Part.from_bytes(data=img_bytes, mime_type="image/png")
            )
    else:
        contents = prompt

    config = types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
    )
    if system_instruction:
        config.system_instruction = system_instruction

    response = await client.aio.models.generate_content(
        model=IMAGE_GEN_MODEL,
        contents=contents,
        config=config,
    )

    text = _extract_text_from_response(response)
    images = _extract_all_images_from_response(response)
    logger.info(f"[ImageGen] interleaved 完成: 文本长度={len(text)}, 图片数={len(images)}")
    return text, images


def save_image(image_bytes: bytes, path: str) -> str:
    """将图片 bytes 保存到文件"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(image_bytes)
    logger.info(f"[ImageGen] 图片已保存: {path}")
    return path

"""
ADA Agent - 素材设计师（Asset Designer Agent）
负责：通过 asset_type 切换模式，处理物品/人物/场景的分析与生图
v4 架构：合并原 PDA/CDA/SDA 为一个 Agent + 三套 prompt

工作流（三种模式共用）：
1. Gemini 文本分析/拓展 → 结构化 JSON 档案
2. Nano Banana 生成素材图（交错输出模式）
"""

import json
import os
import logging
from typing import Optional

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY, TEXT_MODEL, ASSETS_DIR
from backend.models import AssetType, ItemAsset, ModelAsset, SceneAsset
from backend.tools.image_gen import (
    text_to_image,
    generate_with_interleaved_output,
    save_image,
)
from backend.prompts.ada_prompts import (
    ADA_ITEM_SYSTEM_PROMPT,
    ADA_ITEM_IMAGE_PROMPT,
    ADA_MODEL_SYSTEM_PROMPT,
    ADA_MODEL_IMAGE_PROMPT,
    ADA_SCENE_SYSTEM_PROMPT,
    ADA_SCENE_IMAGE_PROMPT,
    build_item_analysis_prompt,
    build_model_analysis_prompt,
    build_scene_analysis_prompt,
    get_item_response_schema,
    get_model_response_schema,
    get_scene_response_schema,
)

logger = logging.getLogger(__name__)


def _get_client() -> genai.Client:
    """获取 Gemini 客户端"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未配置，请在 .env 中设置")
    return genai.Client(api_key=GEMINI_API_KEY)


async def _text_analysis(
    user_prompt: str,
    system_prompt: str,
    response_schema: dict,
    input_images: Optional[list[bytes]] = None,
) -> dict:
    """
    调用 Gemini 文本模型进行结构化分析。

    参数:
        user_prompt: 用户提示词
        system_prompt: 系统提示词
        response_schema: JSON Schema
        input_images: 输入图片（可选）

    返回:
        解析后的 dict
    """
    client = _get_client()

    if input_images:
        contents = [user_prompt]
        for img_bytes in input_images:
            contents.append(
                types.Part.from_bytes(data=img_bytes, mime_type="image/png")
            )
    else:
        contents = user_prompt

    response = await client.aio.models.generate_content(
        model=TEXT_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=0.7,
            response_mime_type="application/json",
            response_schema=response_schema,
        ),
    )

    raw_text = response.text
    if not raw_text:
        raise ValueError("Gemini 返回了空响应")

    return json.loads(raw_text)


async def create_item_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
) -> ItemAsset:
    """
    创建物品素材。

    参数:
        asset_id: 素材 ID
        description: 用户描述
        images: 用户上传的产品图片

    返回:
        ItemAsset 物品档案
    """
    logger.info(f"[ADA] 物品模式: id={asset_id}, desc={description[:50]}...")

    # 第 1 步：Gemini 文本分析
    user_prompt = build_item_analysis_prompt(description)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_ITEM_SYSTEM_PROMPT,
        response_schema=get_item_response_schema(),
        input_images=images,
    )

    logger.info(f"[ADA] 物品分析完成: {data.get('name')}, 尺寸={data.get('size_category')}")

    # 检查尺寸
    if data.get("size_category") == "large":
        logger.warning(f"[ADA] 大型物品被拒绝: {data.get('name')}")

    # 保存原始图片
    original_paths = []
    if images:
        asset_dir = os.path.join(ASSETS_DIR, asset_id)
        os.makedirs(asset_dir, exist_ok=True)
        for i, img_bytes in enumerate(images):
            path = os.path.join(asset_dir, f"original_{i}.png")
            save_image(img_bytes, path)
            original_paths.append(path)

    # 第 2 步：生成产品说明图（交错输出）
    instruction_image_path = None
    if data.get("size_category") != "large":
        image_prompt = ADA_ITEM_IMAGE_PROMPT.format(
            name=data["name"],
            full_description=data["full_description"],
            selling_point=data["selling_point"],
        )
        img_bytes = await text_to_image(image_prompt)
        instruction_image_path = os.path.join(ASSETS_DIR, asset_id, "instruction.png")
        save_image(img_bytes, instruction_image_path)

    return ItemAsset(
        id=asset_id,
        name=data["name"],
        category=data["category"],
        usage=data["usage"],
        selling_point=data["selling_point"],
        original_images=original_paths,
        instruction_image=instruction_image_path,
        full_description=data["full_description"],
        size_category=data["size_category"],
    )


async def create_model_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
    num_looks: int = 3,
) -> tuple[ModelAsset, list[str]]:
    """
    创建人物素材，生成多套造型供用户选择。

    参数:
        asset_id: 素材 ID
        description: 用户描述
        images: 用户上传的参考图
        num_looks: 生成造型方案数量

    返回:
        (ModelAsset, look_paths): 人设档案 + 造型图路径列表
    """
    logger.info(f"[ADA] 人物模式: id={asset_id}, desc={description[:50]}...")

    # 第 1 步：Gemini 文本拓展人设
    user_prompt = build_model_analysis_prompt(description)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_MODEL_SYSTEM_PROMPT,
        response_schema=get_model_response_schema(),
        input_images=images,
    )

    logger.info(f"[ADA] 人设分析完成: {data.get('name')}")

    # 保存参考图
    ref_paths = []
    asset_dir = os.path.join(ASSETS_DIR, asset_id)
    os.makedirs(asset_dir, exist_ok=True)
    if images:
        for i, img_bytes in enumerate(images):
            path = os.path.join(asset_dir, f"reference_{i}.png")
            save_image(img_bytes, path)
            ref_paths.append(path)

    # 第 2 步：生成多套造型图
    look_paths = []
    for i in range(num_looks):
        image_prompt = ADA_MODEL_IMAGE_PROMPT.format(
            full_description=data["full_description"],
            appearance=data["appearance"],
            outfits=data["outfits"],
        )
        image_prompt += f"\n\n这是造型方案 {chr(65 + i)}，请生成有所区别的穿搭和姿态。"
        img_bytes = await text_to_image(image_prompt)
        path = os.path.join(asset_dir, f"look_{chr(97 + i)}.png")
        save_image(img_bytes, path)
        look_paths.append(path)
        logger.info(f"[ADA] 造型 {chr(65 + i)} 已生成")

    asset = ModelAsset(
        id=asset_id,
        name=data["name"],
        appearance=data["appearance"],
        personality=data["personality"],
        outfits=data["outfits"],
        reference_images=ref_paths,
        selected_look=None,  # 等用户选择后再设置
        full_description=data["full_description"],
    )

    return asset, look_paths


async def create_scene_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
    num_options: int = 3,
) -> tuple[SceneAsset, list[str]]:
    """
    创建场景素材，生成多个方案供用户选择。

    参数:
        asset_id: 素材 ID
        description: 用户描述
        images: 用户上传的参考图
        num_options: 生成方案数量

    返回:
        (SceneAsset, option_paths): 场景档案 + 场景图路径列表
    """
    logger.info(f"[ADA] 场景模式: id={asset_id}, desc={description[:50]}...")

    # 第 1 步：Gemini 文本丰富场景
    user_prompt = build_scene_analysis_prompt(description)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_SCENE_SYSTEM_PROMPT,
        response_schema=get_scene_response_schema(),
        input_images=images,
    )

    logger.info(f"[ADA] 场景分析完成: {data.get('name')}")

    # 保存参考图
    ref_paths = []
    asset_dir = os.path.join(ASSETS_DIR, asset_id)
    os.makedirs(asset_dir, exist_ok=True)
    if images:
        for i, img_bytes in enumerate(images):
            path = os.path.join(asset_dir, f"reference_{i}.png")
            save_image(img_bytes, path)
            ref_paths.append(path)

    # 第 2 步：生成多个场景图
    option_paths = []
    for i in range(num_options):
        image_prompt = ADA_SCENE_IMAGE_PROMPT.format(
            full_description=data["full_description"],
            environment=data["environment"],
            lighting=data["lighting"],
            mood=data["mood"],
        )
        image_prompt += f"\n\n这是场景方案 {chr(65 + i)}，请在保持整体风格的前提下提供不同的布局变化。"
        img_bytes = await text_to_image(image_prompt)
        path = os.path.join(asset_dir, f"scene_{chr(97 + i)}.png")
        save_image(img_bytes, path)
        option_paths.append(path)
        logger.info(f"[ADA] 场景方案 {chr(65 + i)} 已生成")

    asset = SceneAsset(
        id=asset_id,
        name=data["name"],
        environment=data["environment"],
        lighting=data["lighting"],
        mood=data["mood"],
        reference_images=ref_paths,
        selected_scene=None,  # 等用户选择后再设置
        full_description=data["full_description"],
    )

    return asset, option_paths

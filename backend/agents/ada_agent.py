"""
ADA Agent - 素材设计师（Asset Designer Agent）
负责：通过 asset_type 切换模式，处理物品/人物/场景的分析与生图
v5 架构：智能问卷两步流程（analyze → confirm）+ P0/P1/P2 卖点优先级
"""

import json
import os
import logging
from typing import Optional

from google.genai import types

from backend.config import get_genai_client, TEXT_MODEL, ASSETS_DIR
from backend.models import (
    AssetType, AssetStatus, ItemAsset, ModelAsset, SceneAsset,
    QuestionnaireStatus, QuestionnaireField,
)
from backend.tools.image_gen import (
    text_to_image,
    image_to_image,
    save_image,
)
from backend.prompts.ada_prompts import (
    ADA_ITEM_ANALYZE_SYSTEM_PROMPT,
    ADA_ITEM_CONFIRM_SYSTEM_PROMPT,
    ADA_ITEM_THUMBNAIL_PROMPT,
    ADA_ITEM_THREE_VIEW_PROMPT,
    ADA_MODEL_SYSTEM_PROMPT,
    ADA_MODEL_IMAGE_PROMPT,
    ADA_MODEL_AVATAR_PROMPT,
    ADA_MODEL_BODY_THREE_VIEW_PROMPT,
    ADA_SCENE_SYSTEM_PROMPT,
    ADA_SCENE_IMAGE_PROMPT,
    ADA_QUICKSTART_SYSTEM_PROMPT,
    build_item_analyze_prompt,
    build_item_confirm_prompt,
    get_item_analyze_schema,
    get_item_confirm_schema,
    build_model_analysis_prompt,
    build_scene_analysis_prompt,
    get_model_response_schema,
    get_scene_response_schema,
    build_quickstart_prompt,
    get_quickstart_schema,
)

logger = logging.getLogger(__name__)


def _get_client():
    """获取 Gemini 客户端（文本分析用 us-central1）"""
    return get_genai_client(location="us-central1")


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


# ========== 物品：第 1 步 — 分析 + 生成问卷 ==========

async def analyze_item(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
) -> ItemAsset:
    """
    分析物品，生成智能问卷（第 1 步）。

    返回带有 questionnaire_fields 的 ItemAsset，questionnaire_status=pending。
    前端根据 questionnaire_fields 渲染表单给用户确认。
    """
    logger.info(f"[ADA] 物品分析: id={asset_id}, desc={description[:50]}...")

    user_prompt = build_item_analyze_prompt(description)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_ITEM_ANALYZE_SYSTEM_PROMPT,
        response_schema=get_item_analyze_schema(),
        input_images=images,
    )

    logger.info(f"[ADA] 分析完成: {data.get('name')}, 尺寸={data.get('size_category')}")

    # 保存原始图片
    original_paths = []
    if images:
        asset_dir = os.path.join(ASSETS_DIR, asset_id)
        os.makedirs(asset_dir, exist_ok=True)
        for i, img_bytes in enumerate(images):
            path = os.path.join(asset_dir, f"original_{i}.png")
            save_image(img_bytes, path)
            original_paths.append(path)

    # 解析问卷字段（v7：含 option_a / option_b 候选答案）
    questionnaire_fields = []
    for q in data.get("questionnaire", []):
        questionnaire_fields.append(QuestionnaireField(
            key=q["key"],
            label=q["label"],
            option_a=q.get("option_a", ""),
            option_b=q.get("option_b", ""),
            value=q.get("value", ""),
            priority=q.get("priority", "P1"),
            source=q.get("source", "ai"),
            required=q.get("required", True),
        ))

    # 解析卖点
    selling_points = data.get("selling_points", {"P0": [], "P1": [], "P2": []})

    return ItemAsset(
        id=asset_id,
        name=data["name"],
        category=data["category"],
        size_category=data["size_category"],
        selling_points=selling_points,
        questionnaire_status=QuestionnaireStatus.PENDING,
        questionnaire_fields=questionnaire_fields,
        full_description=data.get("full_description", ""),
        original_images=original_paths,
    )


# ========== 物品：第 2 步 — 确认问卷 + 生成最终档案 ==========

async def confirm_item(
    asset: ItemAsset,
    confirmed_fields: list[dict],
) -> tuple[ItemAsset, dict]:
    """
    用户确认问卷后，生成最终产品档案 + 产品说明图（第 2 步）。

    参数:
        asset: 第 1 步返回的 ItemAsset（含问卷）
        confirmed_fields: 用户确认后的字段列表 [{key, label, value, priority}]

    返回:
        (更新后的 ItemAsset, image_results): 资产档案 + 三图生成结果
    """
    logger.info(f"[ADA] 物品确认: id={asset.id}, 字段数={len(confirmed_fields)}")

    # 更新 product_info
    product_info = {}
    for f in confirmed_fields:
        if f.get("value"):
            product_info[f["key"]] = f["value"]
    asset.product_info = product_info

    # 更新 selling_points（用户可能修改了卖点）
    for f in confirmed_fields:
        if f.get("priority") == "P0" and f.get("value"):
            if f["value"] not in asset.selling_points.get("P0", []):
                asset.selling_points.setdefault("P0", []).append(f["value"])

    # 调用 Gemini 生成最终描述
    user_prompt = build_item_confirm_prompt(confirmed_fields, asset.selling_points)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_ITEM_CONFIRM_SYSTEM_PROMPT,
        response_schema=get_item_confirm_schema(),
    )

    asset.usage = data.get("usage", "")
    asset.selling_point = data.get("selling_point", "")
    asset.full_description = data.get("full_description", asset.full_description)
    asset.usage_guide = data.get("usage_guide", "")
    asset.questionnaire_status = QuestionnaireStatus.COMPLETED

    logger.info(f"[ADA] usage_guide 已生成: {asset.usage_guide[:80]}...")

    # v9: 生成两张产品图（img2img，以用户原始产品图为参考）
    image_results = {"thumbnail": False, "three_view": False}

    if asset.size_category != "large":
        asset_dir = os.path.join(ASSETS_DIR, asset.id)
        os.makedirs(asset_dir, exist_ok=True)

        # 读取用户上传的原始产品图片作为 img2img 输入
        ref_images = _load_original_images(asset)
        if not ref_images:
            logger.warning("[ADA] 无原始产品图，降级为 text2img")

        # ① 缩略图（白底电商风，UI 展示）
        try:
            prompt = ADA_ITEM_THUMBNAIL_PROMPT.format(
                name=asset.name, full_description=asset.full_description,
            )
            if ref_images:
                img_bytes = await image_to_image(ref_images, prompt)
            else:
                img_bytes = await text_to_image(prompt)
            path = os.path.join(asset_dir, "thumbnail.png")
            save_image(img_bytes, path)
            asset.thumbnail_image = path
            image_results["thumbnail"] = True
            logger.info(f"[ADA] 缩略图已生成: {path}")
        except Exception as e:
            logger.warning(f"[ADA] 缩略图生成失败: {e}")

        # ② 三视图（纯产品画面，正/侧/背三角度，DA/VA/VGA 参考）
        try:
            prompt = ADA_ITEM_THREE_VIEW_PROMPT.format(
                name=asset.name, full_description=asset.full_description,
            )
            if ref_images:
                img_bytes = await image_to_image(ref_images, prompt)
            else:
                img_bytes = await text_to_image(prompt)
            path = os.path.join(asset_dir, "three_view.png")
            save_image(img_bytes, path)
            asset.three_view_image = path
            image_results["three_view"] = True
            logger.info(f"[ADA] 三视图已生成: {path}")
        except Exception as e:
            logger.warning(f"[ADA] 三视图生成失败: {e}")

    # v9: 状态改为已确认（即使部分图片生成失败，档案信息是完整的）
    asset.status = AssetStatus.CONFIRMED
    success_count = sum(1 for v in image_results.values() if v)
    logger.info(f"[ADA] 物品档案完成: {asset.name}, 图片 {success_count}/2 成功")
    return asset, image_results


def _load_original_images(asset: ItemAsset) -> list[bytes]:
    """
    读取 asset 中保存的原始产品图片，用于 img2img 参考。
    返回图片 bytes 列表，读取失败的跳过。
    """
    images = []
    for path in (asset.original_images or []):
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    images.append(f.read())
            except Exception as e:
                logger.warning(f"[ADA] 读取原始图片失败 ({path}): {e}")
    return images


# ========== 兼容旧版：一步完成的 create_item_asset ==========

async def create_item_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
) -> ItemAsset:
    """
    兼容旧版的一步创建模式。
    内部走 analyze → 自动确认所有 AI 预填字段 → confirm。
    """
    # 第 1 步：分析
    asset = await analyze_item(asset_id, description, images)

    if asset.size_category == "large":
        return asset

    # 自动确认所有字段
    auto_confirmed = []
    for f in asset.questionnaire_fields:
        auto_confirmed.append({
            "key": f.key,
            "label": f.label,
            "value": f.value,
            "priority": f.priority,
        })

    # 第 2 步：确认
    asset, _image_results = await confirm_item(asset, auto_confirmed)
    return asset


# ========== 人物素材 ==========

async def create_model_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
    num_looks: int = 3,
) -> tuple[ModelAsset, list[str]]:
    """
    创建人物素材，生成多套造型供用户选择。

    返回:
        (ModelAsset, look_paths): 人设档案 + 造型图路径列表
    """
    logger.info(f"[ADA] 人物模式: id={asset_id}, desc={description[:50]}...")

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

    # 生成多套造型图
    look_paths = []
    for i in range(num_looks):
        image_prompt = ADA_MODEL_IMAGE_PROMPT.format(
            full_description=data["full_description"],
            appearance=data["appearance"],
            outfits=data["outfits"],
        )
        image_prompt += f"\n\n这是造型方案 {chr(65 + i)}，请生成有所区别的穿搭和姿态。"
        try:
            img_bytes = await text_to_image(image_prompt)
            path = os.path.join(asset_dir, f"look_{chr(97 + i)}.png")
            save_image(img_bytes, path)
            look_paths.append(path)
            logger.info(f"[ADA] 造型 {chr(65 + i)} 已生成")
        except Exception as e:
            logger.warning(f"[ADA] 造型 {chr(65 + i)} 生成失败: {e}")

    asset = ModelAsset(
        id=asset_id,
        name=data["name"],
        appearance=data["appearance"],
        personality=data["personality"],
        outfits=data["outfits"],
        reference_images=ref_paths,
        selected_look=None,
        full_description=data["full_description"],
    )

    return asset, look_paths


# ========== 人物：选择造型后生成头像 + 上半身三视图（v7） ==========

async def generate_model_images(asset: ModelAsset) -> ModelAsset:
    """
    用户选定造型后，生成头像 + 上半身三视图。
    调用后将 status 更新为 confirmed。
    """
    logger.info(f"[ADA] 人物图片生成: id={asset.id}, look={asset.selected_look}")

    asset_dir = os.path.join(ASSETS_DIR, asset.id)
    os.makedirs(asset_dir, exist_ok=True)

    # ① 头像（面部特写，UI 展示）
    try:
        prompt = ADA_MODEL_AVATAR_PROMPT.format(
            full_description=asset.full_description,
            appearance=asset.appearance,
        )
        img_bytes = await text_to_image(prompt)
        path = os.path.join(asset_dir, "avatar.png")
        save_image(img_bytes, path)
        asset.avatar_image = path
        logger.info(f"[ADA] 人物头像已生成: {path}")
    except Exception as e:
        logger.warning(f"[ADA] 人物头像生成失败: {e}")

    # ② 上半身三视图（DA/VA/VGA 参考）
    try:
        prompt = ADA_MODEL_BODY_THREE_VIEW_PROMPT.format(
            full_description=asset.full_description,
            appearance=asset.appearance,
            outfits=asset.outfits,
        )
        img_bytes = await text_to_image(prompt)
        path = os.path.join(asset_dir, "body_three_view.png")
        save_image(img_bytes, path)
        asset.body_three_view_image = path
        logger.info(f"[ADA] 上半身三视图已生成: {path}")
    except Exception as e:
        logger.warning(f"[ADA] 上半身三视图生成失败: {e}")

    asset.status = AssetStatus.CONFIRMED
    logger.info(f"[ADA] 人物素材已确认: {asset.name}")
    return asset


# ========== 场景素材 ==========

async def create_scene_asset(
    asset_id: str,
    description: str,
    images: Optional[list[bytes]] = None,
    num_options: int = 3,
) -> tuple[SceneAsset, list[str]]:
    """
    创建场景素材，生成多个方案供用户选择。

    返回:
        (SceneAsset, option_paths): 场景档案 + 场景图路径列表
    """
    logger.info(f"[ADA] 场景模式: id={asset_id}, desc={description[:50]}...")

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

    # 生成多个场景图
    option_paths = []
    for i in range(num_options):
        image_prompt = ADA_SCENE_IMAGE_PROMPT.format(
            full_description=data["full_description"],
            environment=data["environment"],
            lighting=data["lighting"],
            mood=data["mood"],
        )
        image_prompt += f"\n\n这是场景方案 {chr(65 + i)}，请在保持整体风格的前提下提供不同的布局变化。"
        try:
            img_bytes = await text_to_image(image_prompt)
            path = os.path.join(asset_dir, f"scene_{chr(97 + i)}.png")
            save_image(img_bytes, path)
            option_paths.append(path)
            logger.info(f"[ADA] 场景方案 {chr(65 + i)} 已生成")
        except Exception as e:
            logger.warning(f"[ADA] 场景方案 {chr(65 + i)} 生成失败: {e}")

    asset = SceneAsset(
        id=asset_id,
        name=data["name"],
        environment=data["environment"],
        lighting=data["lighting"],
        mood=data["mood"],
        reference_images=ref_paths,
        selected_scene=None,
        full_description=data["full_description"],
    )

    return asset, option_paths


# ========== 一句话快速开始：拆解一句话为物品+人物+场景描述 ==========

async def quickstart_parse(
    sentence: str,
    images: Optional[list[bytes]] = None,
) -> dict:
    """
    解析一句话描述，拆解为物品/人物/场景三类素材描述。

    返回:
        {"item_description": "...", "model_description": "...", "scene_description": "..."}
    """
    logger.info(f"[ADA] 一句话拆解: {sentence[:80]}...")

    user_prompt = build_quickstart_prompt(sentence)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_QUICKSTART_SYSTEM_PROMPT,
        response_schema=get_quickstart_schema(),
        input_images=images,
    )

    logger.info(
        f"[ADA] 拆解完成: item={data.get('item_description', '')[:30]}, "
        f"model={data.get('model_description', '')[:30]}, "
        f"scene={data.get('scene_description', '')[:30]}"
    )

    return data

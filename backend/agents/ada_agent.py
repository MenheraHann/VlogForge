"""
ADA Agent - 素材设计师（Asset Designer Agent）
负责：通过 asset_type 切换模式，处理物品/人物（含场景）的分析与生图
v10 架构：场景融入人物，人物生成一张 portrait_image（人在场景中的半身近景）
"""

import asyncio
import json
import os
import logging
from typing import Optional

from google.genai import types

from backend.config import get_genai_client, TEXT_MODEL, ASSETS_DIR
from backend.models import (
    AssetType, AssetStatus, ItemAsset, ModelAsset,
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
    ADA_QUICKSTART_SYSTEM_PROMPT,
    build_item_analyze_prompt,
    build_item_confirm_prompt,
    get_item_analyze_schema,
    get_item_confirm_schema,
    build_model_analysis_prompt,
    get_model_response_schema,
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
    max_retries: int = 3,
) -> dict:
    """
    调用 Gemini 文本模型进行结构化分析（含瞬态错误重试）。

    参数:
        user_prompt: 用户提示词
        system_prompt: 系统提示词
        response_schema: JSON Schema
        input_images: 输入图片（可选）
        max_retries: 瞬态错误最大重试次数

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

    delay = 5
    for attempt in range(max_retries + 1):
        try:
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

        except (json.JSONDecodeError, ValueError):
            raise  # 非瞬态错误，直接抛出
        except Exception as exc:
            msg = str(exc)
            is_transient = any(kw in msg for kw in [
                "429", "RESOURCE_EXHAUSTED", "timed out", "Connection",
                "RemoteDisconnected", "TransportError", "UNAVAILABLE",
            ])
            if not is_transient or attempt >= max_retries:
                raise
            logger.warning(
                f"[ADA] 文本分析瞬态错误，第 {attempt + 1}/{max_retries} 次重试，"
                f"等待 {delay}s... 原因: {exc}"
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60)


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

    # v13: 生成两张产品图（img2img，以用户原始产品图为参考）
    #   改进：两图间隔 2 秒防限流 + 失败图片自动重试 + img2img 失败降级 text2img
    image_results = {"thumbnail": False, "three_view": False}

    if asset.size_category != "large":
        asset_dir = os.path.join(ASSETS_DIR, asset.id)
        os.makedirs(asset_dir, exist_ok=True)

        # 读取用户上传的原始产品图片作为 img2img 输入
        ref_images = _load_original_images(asset)
        if not ref_images:
            logger.warning("[ADA] 无原始产品图，降级为 text2img")

        # ===== 第一轮生成 =====

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
            logger.warning(f"[ADA] 缩略图首次生成失败: {e}")

        # 间隔 2 秒，降低连续请求触发 429 限流的风险
        await asyncio.sleep(2)

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
            logger.warning(f"[ADA] 三视图首次生成失败: {e}")

        # ===== 第二轮：对失败的图片重试一次（含 5 秒冷却 + img2img→text2img 降级） =====
        failed_images = [k for k, v in image_results.items() if not v]
        if failed_images:
            logger.info(f"[ADA] 图片重试: {failed_images}，等待 5 秒限流冷却...")
            await asyncio.sleep(5)

            for img_type in failed_images:
                try:
                    if img_type == "thumbnail":
                        prompt = ADA_ITEM_THUMBNAIL_PROMPT.format(
                            name=asset.name, full_description=asset.full_description,
                        )
                        # 优先 img2img，失败则降级 text2img
                        try:
                            if ref_images:
                                img_bytes = await image_to_image(ref_images, prompt)
                            else:
                                img_bytes = await text_to_image(prompt)
                        except Exception:
                            logger.info("[ADA] 缩略图 img2img 重试失败，降级 text2img")
                            img_bytes = await text_to_image(prompt)
                        path = os.path.join(asset_dir, "thumbnail.png")
                        save_image(img_bytes, path)
                        asset.thumbnail_image = path
                        image_results["thumbnail"] = True
                        logger.info(f"[ADA] 缩略图重试成功: {path}")

                    elif img_type == "three_view":
                        prompt = ADA_ITEM_THREE_VIEW_PROMPT.format(
                            name=asset.name, full_description=asset.full_description,
                        )
                        # 优先 img2img，失败则降级 text2img
                        try:
                            if ref_images:
                                img_bytes = await image_to_image(ref_images, prompt)
                            else:
                                img_bytes = await text_to_image(prompt)
                        except Exception:
                            logger.info("[ADA] 三视图 img2img 重试失败，降级 text2img")
                            img_bytes = await text_to_image(prompt)
                        path = os.path.join(asset_dir, "three_view.png")
                        save_image(img_bytes, path)
                        asset.three_view_image = path
                        image_results["three_view"] = True
                        logger.info(f"[ADA] 三视图重试成功: {path}")

                    # 重试成功后等 2 秒再处理下一个（如果还有的话）
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error(f"[ADA] {img_type} 重试仍失败: {e}")

    # 状态改为已确认（文字档案是完整的，图片缺失不影响档案状态）
    asset.status = AssetStatus.CONFIRMED
    success_count = sum(1 for v in image_results.values() if v)
    logger.info(f"[ADA] 物品档案完成: {asset.name}, 图片 {success_count}/2 成功")
    if success_count < 2:
        missing = [k for k, v in image_results.items() if not v]
        logger.warning(
            f"[ADA] 物品 {asset.name} 有 {2 - success_count} 张图片生成失败，"
            f"缺失: {missing}（档案已确认，图片可后续重新生成）"
        )
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
    创建人物素材（v10：含场景），生成多套「人在场景中的半身近景」方案供用户选择。

    返回:
        (ModelAsset, look_paths): 人设档案 + 方案图路径列表
    """
    logger.info(f"[ADA] 人物模式(含场景): id={asset_id}, desc={description[:50]}...")

    user_prompt = build_model_analysis_prompt(description)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_MODEL_SYSTEM_PROMPT,
        response_schema=get_model_response_schema(),
        input_images=images,
    )

    logger.info(f"[ADA] 人设分析完成: {data.get('name')}, 场景={data.get('scene_context', '')[:30]}")

    # 保存参考图
    ref_paths = []
    asset_dir = os.path.join(ASSETS_DIR, asset_id)
    os.makedirs(asset_dir, exist_ok=True)
    if images:
        for i, img_bytes in enumerate(images):
            path = os.path.join(asset_dir, f"reference_{i}.png")
            save_image(img_bytes, path)
            ref_paths.append(path)

    # v10: 生成多套「人在场景中的半身近景」方案图（关键词式提示词）
    scene_context = data.get("scene_context", "客厅，背景是沙发、夜晚自然光、明亮的环境")
    base_image_prompt = data.get("image_prompt", "")
    if not base_image_prompt:
        # 降级：用关键词拼接
        base_image_prompt = f"半身近景、{data['appearance']}、面对镜头、{scene_context}、手机拍摄的真实质感"
    logger.info(f"[ADA] 图片生成提示词: {base_image_prompt[:80]}...")
    look_paths = []
    for i in range(num_looks):
        image_prompt = ADA_MODEL_IMAGE_PROMPT.format(image_prompt=base_image_prompt)
        try:
            img_bytes = await text_to_image(image_prompt)
            path = os.path.join(asset_dir, f"look_{chr(97 + i)}.png")
            save_image(img_bytes, path)
            look_paths.append(path)
            logger.info(f"[ADA] 方案 {chr(65 + i)} 已生成（人在场景中的半身近景）")
        except Exception as e:
            logger.warning(f"[ADA] 方案 {chr(65 + i)} 生成失败: {e}")

    asset = ModelAsset(
        id=asset_id,
        name=data["name"],
        appearance=data["appearance"],
        personality=data["personality"],
        outfits=data["outfits"],
        scene_context=scene_context,
        reference_images=ref_paths,
        look_options=look_paths,
        full_description=data["full_description"],
    )

    return asset, look_paths


# ========== 人物：选择方案后确认 portrait_image（v10） ==========

async def confirm_model_selection(asset: ModelAsset) -> ModelAsset:
    """
    v10: 用户选定方案后，将选中的方案图设为 portrait_image，直接确认。
    选中的图即为 portrait_image（一图多用：UI 缩略图 + 首帧参考 + 分镜参考）。
    不再需要额外生成头像和三视图。
    """
    logger.info(f"[ADA] 人物方案确认: id={asset.id}, selected_look={asset.selected_look}")

    # v10: 选中的方案图就是 portrait_image（一图多用）
    asset.portrait_image = asset.selected_look
    asset.status = AssetStatus.CONFIRMED
    logger.info(f"[ADA] 人物素材已确认: {asset.name}, portrait_image={asset.portrait_image}")
    return asset


# 兼容旧版调用名（main.py 中可能引用 generate_model_images）
async def generate_model_images(asset: ModelAsset) -> ModelAsset:
    """兼容旧版：v10 中直接调用 confirm_model_selection"""
    return await confirm_model_selection(asset)


# ========== 一句话快速开始：拆解一句话为物品+人物（含场景）描述 ==========

async def quickstart_parse(
    sentence: str,
    images: Optional[list[bytes]] = None,
) -> dict:
    """
    v10: 解析一句话描述，拆解为物品和人物（含场景）两类素材描述。
    场景信息已融入 model_description，不再有独立的 scene_description。

    返回:
        {"item_description": "...", "model_description": "..."}
    """
    logger.info(f"[ADA] 一句话拆解(v10): {sentence[:80]}...")

    user_prompt = build_quickstart_prompt(sentence)
    data = await _text_analysis(
        user_prompt=user_prompt,
        system_prompt=ADA_QUICKSTART_SYSTEM_PROMPT,
        response_schema=get_quickstart_schema(),
        input_images=images,
    )

    logger.info(
        f"[ADA] 拆解完成: item={data.get('item_description', '')[:30]}, "
        f"model(含场景)={data.get('model_description', '')[:30]}"
    )

    return data

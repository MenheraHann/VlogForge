"""
VlogForge - AI Vlog 带货视频生成器
FastAPI 入口文件
v4 架构：素材库 + 视频生成两阶段
"""

import os
import uuid
import json
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import PORT, ARTIFACTS_DIR, ASSETS_DIR, PLATFORM_ASPECT_MAP, MIN_SEGMENTS, MAX_SEGMENTS
from backend.models import (
    Platform, JobStatus, AssetType,
    ItemAsset, ModelAsset,
    JobResponse, ProgressResponse,
)
from backend.services.job_manager import JobManager
from backend.services.asset_manager import AssetManager
from backend.agents.da_agent import run_pipeline
from backend.models import AssetStatus
from backend.agents.ada_agent import (
    analyze_item,
    confirm_item,
    create_item_asset,
    create_model_asset,
    quickstart_parse,
    regenerate_item_image,
)
from backend.tools.image_gen import SAFETY_FILTER_ERROR_TAG

# 日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# 管理器（在 lifespan 之前初始化，供路由引用）
job_manager = JobManager()
asset_manager = AssetManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动注入 + 关闭清理"""
    # === 启动 ===
    job_manager.set_pipeline_runner(run_pipeline)
    logger.info("[Startup] 流水线执行函数已注入 JobManager")
    yield
    # === 关闭 ===
    logger.info("[Shutdown] 正在优雅关闭...")
    if job_manager._current_task and not job_manager._current_task.done():
        logger.info("[Shutdown] 取消当前运行的任务...")
        job_manager._current_task.cancel()
        try:
            await asyncio.wait_for(job_manager._current_task, timeout=5)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass
    logger.info("[Shutdown] 关闭完成")


app = FastAPI(
    title="VlogForge",
    description="AI Vlog 带货视频生成器 - Gemini Live Agent Challenge",
    version="0.4.0",
    lifespan=lifespan,
)

# 跨域（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== 健康检查 ==========

@app.get("/health")
async def health_check():
    """健康检查"""
    stats = asset_manager.get_stats()
    return {"status": "ok", "service": "VlogForge", "assets": stats}


# ========== 后台异步任务 ==========

async def _generate_model_looks(
    model_id: str,
    description: str,
    reference_images: Optional[list[bytes]],
    asset_manager: AssetManager,
):
    """
    后台异步生成人物造型方案图。
    调用 create_model_asset 生成完整人设 + 方案图，
    完成后将结果合并到已保存的占位 ModelAsset 上。
    失败时标记 status=FAILED，不会崩溃服务。
    """
    try:
        logger.info(f"[Model] {model_id} 后台生成开始...")
        asset, look_paths = await create_model_asset(
            asset_id=model_id,
            description=description,
            images=reference_images,
        )

        # 用生成结果更新已保存的占位 model
        existing = asset_manager.get_model(model_id)
        if existing:
            existing.name = asset.name
            existing.appearance = asset.appearance
            existing.personality = asset.personality
            existing.outfits = asset.outfits
            existing.scene_context = asset.scene_context
            existing.reference_images = asset.reference_images
            existing.look_options = asset.look_options
            existing.full_description = asset.full_description
            # v15: 自动将 look_options[0] 设为 portrait_image，状态设为 PENDING（待确认）
            if asset.look_options:
                existing.portrait_image = asset.look_options[0]
            existing.status = AssetStatus.PENDING
            asset_manager.save_model(existing)
            logger.info(
                f"[Model] {model_id} 造型生成完成，portrait_image 已自动设置，"
                f"等待用户确认/重新生成/调整"
            )
        else:
            logger.error(f"[Model] {model_id} 占位模型已被删除，生成结果丢弃")

    except Exception as e:
        logger.error(f"[Model] {model_id} 后台生成失败: {e}", exc_info=True)
        existing = asset_manager.get_model(model_id)
        if existing:
            existing.status = AssetStatus.FAILED
            # v16: 存储错误类型 key，前端通过 i18n 翻译显示
            err_msg = str(e)
            if SAFETY_FILTER_ERROR_TAG in err_msg:
                existing.error_message = "safety_filtered"
            elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                existing.error_message = "rate_limited"
            elif "quota" in err_msg.lower():
                existing.error_message = "quota_exhausted"
            else:
                existing.error_message = f"error:{err_msg[:100]}"
            asset_manager.save_model(existing)


# ========== 素材 API ==========

@app.post("/api/assets/item")
async def create_item(
    description: str = Form(..., description="产品描述"),
    images: Optional[list[UploadFile]] = File(None, description="产品图片"),
):
    """创建物品素材"""
    asset_id = asset_manager.generate_id(AssetType.ITEM)
    logger.info(f"[API] 创建物品素材: {asset_id}")

    # 读取上传图片
    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    asset = await create_item_asset(
        asset_id=asset_id,
        description=description,
        images=image_bytes_list if image_bytes_list else None,
    )

    # 检查是否被拒绝（大型物品）
    if asset.size_category == "large":
        return {
            "status": "rejected",
            "reason": "大型物品不支持，仅接受上半身可演示的小型产品",
            "asset": asset.model_dump(),
        }

    asset_manager.save_item(asset)
    return {"status": "ok", "asset": asset.model_dump()}


# ========== 物品智能问卷 API（v5 两步流程） ==========

@app.post("/api/assets/item/analyze")
async def analyze_item_asset(
    description: str = Form(..., description="产品描述"),
    images: Optional[list[UploadFile]] = File(None, description="产品图片"),
):
    """
    物品分析（第 1 步）：ADA 分析产品 → 返回智能问卷。
    前端根据返回的 questionnaire_fields 渲染表单给用户确认。
    """
    asset_id = asset_manager.generate_id(AssetType.ITEM)
    logger.info(f"[API] 物品分析: {asset_id}")

    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    asset = await analyze_item(
        asset_id=asset_id,
        description=description,
        images=image_bytes_list if image_bytes_list else None,
    )

    # 大型物品直接拒绝
    if asset.size_category == "large":
        return {
            "status": "rejected",
            "reason": "大型物品不支持，仅接受上半身可演示的小型产品",
            "asset": asset.model_dump(),
        }

    # 暂存到素材库（generating 状态，前端刷新可恢复占位卡片）
    asset.status = AssetStatus.GENERATING
    asset_manager.save_item(asset)

    return {
        "status": "ok",
        "asset_id": asset.id,
        "asset": asset.model_dump(),
        "questionnaire": [f.model_dump() for f in asset.questionnaire_fields],
        "selling_points": asset.selling_points,
        "message": "请确认或修改以下产品信息",
    }


@app.post("/api/assets/item/{asset_id}/confirm")
async def confirm_item_asset(
    asset_id: str,
    confirmed_fields: str = Form(..., description="确认后的字段 JSON 数组"),
):
    """
    物品确认（第 2 步）：用户确认问卷 → ADA 生成最终档案 + 产品说明图。
    confirmed_fields 格式: [{"key":"...", "label":"...", "value":"...", "priority":"P0/P1/P2"}]
    """
    asset = asset_manager.get_item(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"物品素材 {asset_id} 不存在")

    try:
        fields = json.loads(confirmed_fields)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="confirmed_fields 格式错误，需为 JSON 数组")

    logger.info(f"[API] 物品确认: {asset_id}, 字段数={len(fields)}")

    updated_asset, image_results = await confirm_item(asset, fields)
    asset_manager.save_item(updated_asset)

    success_count = sum(1 for v in image_results.values() if v)
    return {
        "status": "ok",
        "asset": updated_asset.model_dump(),
        "image_results": image_results,
        "images_generated": success_count,
        "message": f"产品档案已完成，{success_count}/2 张图片已生成",
    }


@app.post("/api/assets/model")
async def create_model(
    description: str = Form(..., description="人物描述"),
    images: Optional[list[UploadFile]] = File(None, description="参考图"),
):
    """
    创建人物素材（异步非阻塞）。
    立即返回 generating 状态的占位卡片，后台异步生成造型方案图。
    前端通过轮询 /api/assets 检测生成完成（look_options 非空）。
    """
    asset_id = asset_manager.generate_id(AssetType.MODEL)
    logger.info(f"[API] 创建人物素材(异步): {asset_id}, desc={description[:50]}")

    # 读取上传图片（必须在端点内完成，离开端点后 UploadFile 不可用）
    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    # 1. 立即创建占位 ModelAsset（status=generating），保存到素材库
    model = ModelAsset(
        id=asset_id,
        name=description[:20] or "新人物",
        status=AssetStatus.GENERATING,
        appearance="生成中...",  # 占位值，后台生成完成后会更新
        full_description=description,
    )
    asset_manager.save_model(model)

    # 2. 后台异步生成造型方案图（不阻塞 API 返回）
    asyncio.create_task(
        _generate_model_looks(
            model_id=asset_id,
            description=description,
            reference_images=image_bytes_list if image_bytes_list else None,
            asset_manager=asset_manager,
        )
    )

    # 3. 立即返回，前端可立即显示 generating 占位卡片
    return {
        "status": "ok",
        "asset_id": asset_id,
        "asset": model.model_dump(),
        "status_detail": "generating",
        "message": "人物正在创建中，请稍候",
    }


@app.post("/api/assets/model/{asset_id}/select")
async def select_model_look(asset_id: str):
    """
    v15: 确认人物形象（原 select 简化版）。
    不再需要 look_index 参数，直接将当前 portrait_image 确认为最终形象。
    兼容旧前端：如果传了 look_index 也不会报错（Form 参数变为可选）。
    """
    model = asset_manager.get_model(asset_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")

    # v15: portrait_image 已在生成完成时自动设置，直接确认
    if not model.portrait_image:
        raise HTTPException(status_code=400, detail="尚未生成形象图，无法确认")

    model.status = AssetStatus.CONFIRMED
    asset_manager.save_model(model)
    logger.info(f"[API] 人物形象已确认: {asset_id} → {model.portrait_image}")

    return {
        "status": "ok",
        "portrait_image": model.portrait_image,
        "asset_status": model.status.value,
        "asset": model.model_dump(),
    }


# ========== 素材图片：单张重新生成（v19） ==========

import time as _time

# 轻量级 regen 追踪器：{f"{asset_id}:{image_type}": {"status": "generating"|"done"|"failed", "error"?: str, "ts": float}}
_regen_tracker: dict[str, dict] = {}
_REGEN_TTL = 300  # 5 分钟自动清理


def _regen_key(asset_id: str, image_type: str) -> str:
    return f"{asset_id}:{image_type}"


def _regen_cleanup():
    """清理过期的 regen 追踪条目"""
    now = _time.time()
    expired = [k for k, v in _regen_tracker.items() if now - v.get("ts", 0) > _REGEN_TTL]
    for k in expired:
        del _regen_tracker[k]


def get_regen_status(asset_id: str) -> dict:
    """获取某个素材所有正在进行 / 刚完成的重新生成状态"""
    _regen_cleanup()
    result = {}
    for k, v in _regen_tracker.items():
        if k.startswith(f"{asset_id}:"):
            image_type = k.split(":", 1)[1]
            result[image_type] = v
    return result


async def _regenerate_item_image_task(
    asset_id: str,
    image_type: str,
    asset_manager: AssetManager,
):
    """后台异步重新生成物品的单张图片"""
    key = _regen_key(asset_id, image_type)
    try:
        asset = asset_manager.get_item(asset_id)
        if not asset:
            logger.error(f"[Item] {asset_id} 已被删除，重新生成结果丢弃")
            _regen_tracker[key] = {"status": "failed", "error": "素材已被删除", "ts": _time.time()}
            return

        new_path = await regenerate_item_image(asset, image_type)

        # 更新对应字段
        if image_type == "thumbnail":
            asset.thumbnail_image = new_path
        elif image_type == "three_view":
            asset.three_view_image = new_path

        asset.status = AssetStatus.CONFIRMED
        await asset_manager.save_item_async(asset)
        _regen_tracker[key] = {"status": "done", "ts": _time.time()}
        logger.info(f"[Item] {asset_id} 图片 {image_type} 重新生成完成")

    except Exception as e:
        logger.error(f"[Item] {asset_id} 图片重新生成失败: {e}", exc_info=True)
        _regen_tracker[key] = {"status": "failed", "error": str(e)[:200], "ts": _time.time()}
        asset = asset_manager.get_item(asset_id)
        if asset:
            asset.status = AssetStatus.CONFIRMED
            await asset_manager.save_item_async(asset)


@app.post("/api/assets/{asset_id}/regenerate-image")
async def regenerate_asset_image(
    asset_id: str,
    image_type: str = Form(..., description="要重新生成的图片类型: thumbnail / three_view / portrait"),
):
    """
    v19: 单张图片重新生成。
    物品：thumbnail / three_view（使用原始产品图做 img2img 参考）
    人物：portrait（生成新的 look 选项让用户选择）
    """
    if asset_id.startswith("item_"):
        item = asset_manager.get_item(asset_id)
        if not item:
            raise HTTPException(status_code=404, detail=f"物品素材 {asset_id} 不存在")
        if image_type not in ("thumbnail", "three_view"):
            raise HTTPException(status_code=400, detail=f"物品不支持的图片类型: {image_type}")
        if not item.full_description:
            raise HTTPException(status_code=400, detail="缺少 full_description，无法重新生成")

        # W1: 标记 generating 状态
        _regen_tracker[_regen_key(asset_id, image_type)] = {"status": "generating", "ts": _time.time()}

        asyncio.create_task(
            _regenerate_item_image_task(
                asset_id=asset_id,
                image_type=image_type,
                asset_manager=asset_manager,
            )
        )

        return {
            "status": "ok",
            "asset_id": asset_id,
            "image_type": image_type,
            "message": f"正在重新生成{image_type}，请稍候",
        }

    elif asset_id.startswith("model_"):
        model = asset_manager.get_model(asset_id)
        if not model:
            raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")
        if image_type != "portrait":
            raise HTTPException(status_code=400, detail=f"人物不支持的图片类型: {image_type}")
        if not model.full_description:
            raise HTTPException(status_code=400, detail="缺少 full_description，无法重新生成")

        model.status = AssetStatus.GENERATING
        asset_manager.save_model(model)

        ref_images = _load_model_reference_images(model)
        asyncio.create_task(
            _regenerate_model_task(
                model_id=asset_id,
                description=model.full_description,
                reference_images=ref_images if ref_images else None,
                asset_manager=asset_manager,
            )
        )

        return {
            "status": "ok",
            "asset_id": asset_id,
            "image_type": image_type,
            "message": "正在重新生成人物形象，请稍候",
        }

    else:
        raise HTTPException(status_code=400, detail=f"未知的素材 ID 格式: {asset_id}")


# ========== 人物：重新生成 / 调整意见（v15 新增） ==========

async def _regenerate_model_task(
    model_id: str,
    description: str,
    reference_images: Optional[list[bytes]],
    asset_manager: AssetManager,
):
    """
    后台异步重新生成人物造型图。
    用已保存的 full_description（或追加了用户反馈的版本）重新生成 1 张 look 图，
    生成完后替换旧的 look_options 和 portrait_image，状态恢复为 PENDING。
    """
    try:
        logger.info(f"[Model] {model_id} 重新生成开始...")
        asset, look_paths = await create_model_asset(
            asset_id=model_id,
            description=description,
            images=reference_images,
            num_looks=1,
        )

        existing = asset_manager.get_model(model_id)
        if existing:
            # 更新文本档案（可能因 description 变化而有微调）
            existing.name = asset.name
            existing.appearance = asset.appearance
            existing.personality = asset.personality
            existing.outfits = asset.outfits
            existing.scene_context = asset.scene_context
            existing.look_options = asset.look_options
            existing.full_description = description  # 保留用于下次重新生成
            # 自动将新生成的图设为 portrait_image
            if asset.look_options:
                existing.portrait_image = asset.look_options[0]
            existing.status = AssetStatus.PENDING
            asset_manager.save_model(existing)
            logger.info(f"[Model] {model_id} 重新生成完成，等待用户确认")
        else:
            logger.error(f"[Model] {model_id} 模型已被删除，重新生成结果丢弃")

    except Exception as e:
        logger.error(f"[Model] {model_id} 重新生成失败: {e}", exc_info=True)
        existing = asset_manager.get_model(model_id)
        if existing:
            existing.status = AssetStatus.FAILED
            err_msg = str(e)
            if SAFETY_FILTER_ERROR_TAG in err_msg:
                existing.error_message = "safety_filtered"
            elif "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                existing.error_message = "rate_limited"
            elif "quota" in err_msg.lower():
                existing.error_message = "quota_exhausted"
            else:
                existing.error_message = f"error:{err_msg[:100]}"
            asset_manager.save_model(existing)


@app.post("/api/assets/model/{asset_id}/regenerate")
async def regenerate_model_look(asset_id: str):
    """
    v15: 重新生成人物形象。
    用 model 已保存的 full_description 重新调用 create_model_asset(num_looks=1)，
    生成新图替换旧的 look_options 和 portrait_image。
    异步模式：先设 GENERATING，后台生成，前端轮询。
    """
    model = asset_manager.get_model(asset_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")

    if not model.full_description:
        raise HTTPException(status_code=400, detail="缺少 full_description，无法重新生成")

    # 设为 GENERATING，前端显示 spinner
    model.status = AssetStatus.GENERATING
    asset_manager.save_model(model)

    # 读取参考图（如果有的话）
    ref_images = _load_model_reference_images(model)

    # 后台异步重新生成
    asyncio.create_task(
        _regenerate_model_task(
            model_id=asset_id,
            description=model.full_description,
            reference_images=ref_images if ref_images else None,
            asset_manager=asset_manager,
        )
    )

    logger.info(f"[API] 人物重新生成已启动: {asset_id}")
    return {
        "status": "ok",
        "asset_id": asset_id,
        "asset": model.model_dump(),
        "status_detail": "generating",
        "message": "正在重新生成人物形象，请稍候",
    }


@app.post("/api/assets/model/{asset_id}/adjust")
async def adjust_model_look(
    asset_id: str,
    feedback: str = Form(..., description="用户的调整意见"),
):
    """
    v15: 根据用户反馈调整人物形象。
    将 feedback 追加到 model 的 full_description 后面，
    用合并后的描述重新生成 1 张 look 图。
    异步模式：先设 GENERATING，后台生成，前端轮询。
    """
    model = asset_manager.get_model(asset_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")

    if not model.full_description:
        raise HTTPException(status_code=400, detail="缺少 full_description，无法调整")

    # 将用户反馈追加到描述中
    merged_description = f"{model.full_description}\n\n【用户调整意见】{feedback}"
    logger.info(f"[API] 人物调整: {asset_id}, feedback={feedback[:50]}...")

    # 设为 GENERATING，前端显示 spinner
    model.status = AssetStatus.GENERATING
    # 立即更新 full_description（保存合并后的版本，后续重新生成也会包含反馈）
    model.full_description = merged_description
    asset_manager.save_model(model)

    # 读取参考图（如果有的话）
    ref_images = _load_model_reference_images(model)

    # 后台异步重新生成（用合并后的描述）
    asyncio.create_task(
        _regenerate_model_task(
            model_id=asset_id,
            description=merged_description,
            reference_images=ref_images if ref_images else None,
            asset_manager=asset_manager,
        )
    )

    return {
        "status": "ok",
        "asset_id": asset_id,
        "asset": model.model_dump(),
        "status_detail": "generating",
        "message": "正在根据您的意见调整人物形象，请稍候",
    }


def _load_model_reference_images(model: ModelAsset) -> list[bytes]:
    """读取人物素材的参考图片，用于重新生成时传入"""
    images = []
    for path in (model.reference_images or []):
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    images.append(f.read())
            except Exception as e:
                logger.warning(f"[Model] 读取参考图失败 ({path}): {e}")
    return images


@app.get("/api/assets")
async def list_assets():
    """列出所有素材"""
    return {
        "items": [a.model_dump() for a in asset_manager.list_items()],
        "models": [a.model_dump() for a in asset_manager.list_models()],
        "stats": asset_manager.get_stats(),
    }


@app.get("/api/assets/{asset_id}")
async def get_asset(asset_id: str):
    """获取单个素材详情"""
    asset = asset_manager.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"素材 {asset_id} 不存在")
    resp = {"status": "ok", "asset": asset.model_dump()}
    # v19: 注入图片重新生成进度
    regen = get_regen_status(asset_id)
    if regen:
        resp["image_regen_status"] = regen
    return resp


@app.put("/api/assets/{asset_id}")
async def update_asset(asset_id: str, updates: str = Form(..., description="更新字段 JSON")):
    """更新素材详情（v7：详情页分区编辑 tag 后保存）"""
    asset = asset_manager.get_asset(asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail=f"素材 {asset_id} 不存在")

    try:
        data = json.loads(updates)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="updates 格式错误，需为 JSON")

    # 按类型更新允许的字段
    for key, value in data.items():
        if hasattr(asset, key) and key not in ("id", "status"):
            setattr(asset, key, value)

    # 重新保存
    if asset_id.startswith("item_"):
        asset_manager.save_item(asset)
    elif asset_id.startswith("model_"):
        asset_manager.save_model(asset)

    logger.info(f"[API] 素材更新: {asset_id}, 字段={list(data.keys())}")
    return {"status": "ok", "asset": asset.model_dump()}


@app.delete("/api/assets/{asset_id}")
async def delete_asset(asset_id: str):
    """删除素材"""
    if asset_id.startswith("item_"):
        ok = asset_manager.delete_item(asset_id)
    elif asset_id.startswith("model_"):
        ok = asset_manager.delete_model(asset_id)
    else:
        raise HTTPException(status_code=400, detail="无效的素材 ID 格式")

    if not ok:
        raise HTTPException(status_code=404, detail=f"素材 {asset_id} 不存在")
    return {"status": "ok", "message": f"素材 {asset_id} 已删除"}


# ========== 一句话快速开始 API ==========

@app.post("/api/quickstart/parse")
async def quickstart_parse_api(
    sentence: str = Form(..., description="一句话描述，如「帮我拍一个亚洲女生在浴室推荐氨基酸洗面奶」"),
    images: Optional[list[UploadFile]] = File(None, description="产品图片（可选）"),
):
    """
    一句话快速开始（第 1 步）：ADA 拆解一句话为物品 + 人物（含场景）两类描述。
    前端拿到拆解结果后，依次创建两类素材。
    """
    logger.info(f"[API] 一句话快速开始: {sentence[:80]}")

    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    result = await quickstart_parse(
        sentence=sentence,
        images=image_bytes_list if image_bytes_list else None,
    )

    return {
        "status": "ok",
        "item_description": result["item_description"],
        "model_description": result["model_description"],
        "message": "拆解完成，请依次确认两类素材",
    }


@app.post("/api/quickstart/create")
async def quickstart_create_all(
    sentence: str = Form(..., description="一句话描述"),
    images: Optional[list[UploadFile]] = File(None, description="产品图片"),
):
    """
    一句话快速开始（一步到位）：拆解 + 创建两类素材。
    物品走 analyze 返回问卷（用户仍需确认），人物返回方案供选择。
    """
    logger.info(f"[API] 一句话快速创建: {sentence[:80]}")

    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    # 第 1 步：拆解
    parsed = await quickstart_parse(
        sentence=sentence,
        images=image_bytes_list if image_bytes_list else None,
    )

    result = {
        "item": None,
        "model": None,
    }

    # 第 2 步：创建物品素材（走问卷流程，返回待确认状态）
    item_id = asset_manager.generate_id(AssetType.ITEM)
    item_asset = await analyze_item(
        asset_id=item_id,
        description=parsed["item_description"],
        images=image_bytes_list if image_bytes_list else None,
    )
    if item_asset.size_category != "large":
        # quickstart 路径也设为 generating 状态，保持前端刷新可恢复
        item_asset.status = AssetStatus.GENERATING
        asset_manager.save_item(item_asset)
        result["item"] = {
            "asset": item_asset.model_dump(),
            "questionnaire": [f.model_dump() for f in item_asset.questionnaire_fields],
            "selling_points": item_asset.selling_points,
        }
    else:
        result["item"] = {"status": "rejected", "reason": "大型物品不支持"}

    # 第 3 步：创建人物素材（异步非阻塞，立即返回占位卡片）
    model_id = asset_manager.generate_id(AssetType.MODEL)
    model_desc = parsed["model_description"]
    model_placeholder = ModelAsset(
        id=model_id,
        name=model_desc[:20] or "新人物",
        status=AssetStatus.GENERATING,
        appearance="生成中...",
        full_description=model_desc,
    )
    asset_manager.save_model(model_placeholder)

    # 后台异步生成造型方案图（不阻塞 quickstart 返回）
    asyncio.create_task(
        _generate_model_looks(
            model_id=model_id,
            description=model_desc,
            reference_images=None,  # quickstart 路径不传人物参考图
            asset_manager=asset_manager,
        )
    )

    result["model"] = {
        "asset": model_placeholder.model_dump(),
        "status_detail": "generating",
    }

    return {
        "status": "ok",
        "parsed": parsed,
        "assets": result,
        "message": "物品问卷已返回，人物正在后台生成中，请先确认物品信息",
    }


# ========== 视频生成 API（旧版兼容） ==========

@app.post("/api/generate", response_model=JobResponse)
async def generate_video(
    product_type: str = Form(..., description="产品类型"),
    product_usage: str = Form(..., description="产品使用方式描述"),
    platform: Platform = Form(..., description="目标平台"),
    segment_count: int = Form(..., description="视频分段数（3~10）"),
    selling_point: str = Form(..., description="核心卖点"),
    product_images: list[UploadFile] = File(..., description="产品参考图"),
):
    """
    创建视频生成任务（旧版接口，直接传产品信息）
    后续将切换到 /api/generate/v2（基于素材库）
    """
    segment_count = max(MIN_SEGMENTS, min(MAX_SEGMENTS, segment_count))
    job_id = str(uuid.uuid4())[:8]
    logger.info(f"[Job {job_id}] 收到生成请求: 产品={product_type}, 平台={platform}, 分段={segment_count}")

    # 保存上传的产品图片
    job_dir = os.path.join(ARTIFACTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    image_paths = []
    for i, img in enumerate(product_images):
        ext = os.path.splitext(img.filename or "img.jpg")[1] or ".jpg"
        path = os.path.join(job_dir, f"product_{i}{ext}")
        content = await img.read()
        with open(path, "wb") as f:
            f.write(content)
        image_paths.append(path)
        logger.info(f"[Job {job_id}] 产品图片已保存: {path}")

    # 计算衍生参数
    aspect_ratio = PLATFORM_ASPECT_MAP[platform.value]

    # 创建任务
    job_data = {
        "job_id": job_id,
        "task_name": f"{product_type} {segment_count * 6}s",
        "product_type": product_type,
        "product_usage": product_usage,
        "platform": platform.value,
        "duration": f"{segment_count * 6}s",
        "selling_point": selling_point,
        "product_images": image_paths,
        "segment_count": segment_count,
        "frame_count": segment_count + 1,
        "aspect_ratio": aspect_ratio,
    }
    job_manager.create_job(job_id, job_data)

    # v14：加入队列，由 JobManager 串行调度执行
    job_manager.enqueue_job(job_id)
    logger.info(f"[Job {job_id}] 已加入渲染队列")

    return JobResponse(job_id=job_id, status=JobStatus.QUEUED, message="任务已加入队列")


# ========== 视频生成 API（v2：基于素材库） ==========

@app.post("/api/generate/v2", response_model=JobResponse)
async def generate_video_v2(
    item_id: str = Form(..., description="物品素材 ID"),
    model_id: str = Form(..., description="人物素材 ID"),
    platform: Platform = Form(..., description="目标平台"),
    segment_count: int = Form(..., description="视频分段数（3~10）"),
    extra_requirements: str = Form("", description="额外要求"),
):
    """
    创建视频生成任务（v2：基于素材库选择）
    用户从素材库选择 1 物品 + 1 人物，组合生成视频
    """
    segment_count = max(MIN_SEGMENTS, min(MAX_SEGMENTS, segment_count))

    # 验证素材存在
    item = asset_manager.get_item(item_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"物品素材 {item_id} 不存在")

    model = asset_manager.get_model(model_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"人物素材 {model_id} 不存在")

    job_id = str(uuid.uuid4())[:8]
    logger.info(
        f"[Job {job_id}] v2 生成请求: "
        f"物品={item.name}, 人物={model.name}, 分段={segment_count}"
    )

    aspect_ratio = PLATFORM_ASPECT_MAP[platform.value]

    # 创建任务
    task_name = f"{item.name} {segment_count * 6}s"
    job_data = {
        "job_id": job_id,
        "task_name": task_name,
        "mode": "v2_assets",
        "item": item.model_dump(),
        "model": model.model_dump(),
        "platform": platform.value,
        "duration": f"{segment_count * 6}s",
        "extra_requirements": extra_requirements,
        "segment_count": segment_count,
        "frame_count": segment_count + 1,
        "aspect_ratio": aspect_ratio,
    }
    job_manager.create_job(job_id, job_data)

    # v14：加入队列，由 JobManager 串行调度执行
    job_manager.enqueue_job(job_id)
    logger.info(f"[Job {job_id}] v2 已加入渲染队列")

    return JobResponse(job_id=job_id, status=JobStatus.QUEUED, message="任务已加入队列")


# ========== 队列管理 API（v14 新增） ==========

@app.get("/api/jobs")
async def list_jobs():
    """
    返回所有任务列表，按创建时间降序排列。
    每个 job 包含：job_id, status, progress, message, task_name, platform, duration, created_at。
    供前端队列面板渲染。
    """
    jobs = job_manager.get_all_jobs()
    queue_info = job_manager.get_queue_info()
    return {
        "status": "ok",
        "jobs": jobs,
        "queue": queue_info,
    }


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """
    取消指定任务。
    - 排队中的任务：直接标记 CANCELLED 并从队列移除
    - 运行中的任务：设置取消信号，流水线在下一个检查点中止
    """
    result = job_manager.cancel_job(job_id)
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result


# ========== 任务查询 API ==========

@app.get("/api/status/{job_id}", response_model=ProgressResponse)
async def get_status(job_id: str):
    """查询任务进度"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")
    return job_manager.get_progress(job_id)


@app.get("/api/stream/{job_id}")
async def stream_progress(job_id: str):
    """SSE 实时进度推送（v14：新增 QUEUED/CANCELLED 终态判断）"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            progress = job_manager.get_progress(job_id)
            data = json.dumps(progress.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"
            # COMPLETED / FAILED / CANCELLED 都是终态，停止推送
            if progress.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                break
            await asyncio.sleep(2)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/download/{job_id}")
async def download_video(job_id: str):
    """下载最终视频"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    video_path = job.get("final_video")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="视频尚未生成完成")

    return FileResponse(
        video_path,
        media_type="video/mp4",
        filename=f"vlogforge_{job_id}.mp4",
    )


# 挂载素材静态文件（供前端加载素材图片）
if os.path.exists(ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")

# 挂载产物静态文件（供前端加载视频等）
if os.path.exists(ARTIFACTS_DIR):
    app.mount("/artifacts", StaticFiles(directory=ARTIFACTS_DIR), name="artifacts")

# 挂载前端静态文件（放最后，避免拦截 API 路由）
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT, reload=True)

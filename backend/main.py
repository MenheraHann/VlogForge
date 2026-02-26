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
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import PORT, ARTIFACTS_DIR, ASSETS_DIR, DURATION_SEGMENT_MAP, PLATFORM_ASPECT_MAP
from backend.models import (
    Platform, Duration, JobStatus, AssetType,
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
)

# 日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VlogForge",
    description="AI Vlog 带货视频生成器 - Gemini Live Agent Challenge",
    version="0.4.0",
)

# 跨域（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 管理器
job_manager = JobManager()
asset_manager = AssetManager()


# ========== 健康检查 ==========

@app.get("/health")
async def health_check():
    """健康检查"""
    stats = asset_manager.get_stats()
    return {"status": "ok", "service": "VlogForge", "assets": stats}


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

    # 暂存到素材库（pending 状态）
    asset_manager.save_item(asset)

    return {
        "status": "ok",
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
    """创建人物素材（返回多套造型供选择）"""
    asset_id = asset_manager.generate_id(AssetType.MODEL)
    logger.info(f"[API] 创建人物素材: {asset_id}")

    image_bytes_list = []
    if images:
        for img in images:
            image_bytes_list.append(await img.read())

    asset, look_paths = await create_model_asset(
        asset_id=asset_id,
        description=description,
        images=image_bytes_list if image_bytes_list else None,
    )

    asset_manager.save_model(asset)
    return {
        "status": "ok",
        "asset": asset.model_dump(),
        "look_options": look_paths,
        "message": "请选择一个造型方案",
    }


@app.post("/api/assets/model/{asset_id}/select")
async def select_model_look(asset_id: str, look_index: int = Form(...)):
    """选择人物方案 → 设为 portrait_image 并确认（v10：一图多用）"""
    model = asset_manager.get_model(asset_id)
    if not model:
        raise HTTPException(status_code=404, detail=f"人物素材 {asset_id} 不存在")

    # look_index 对应 look_a.png, look_b.png, ...
    portrait_path = os.path.join("assets", asset_id, f"look_{chr(97 + look_index)}.png")
    logger.info(f"[API] 人物方案已选: {asset_id} → {portrait_path}")

    # v10: 选中的方案图直接设为 portrait_image（一图多用），标记 confirmed
    model.portrait_image = portrait_path
    model.status = AssetStatus.CONFIRMED
    asset_manager.save_model(model)
    asset_manager.update_model_portrait(asset_id, portrait_path)

    return {
        "status": "ok",
        "portrait_image": portrait_path,
        "asset_status": model.status.value,
    }


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
    return {"status": "ok", "asset": asset.model_dump()}


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
        asset_manager.save_item(item_asset)
        result["item"] = {
            "asset": item_asset.model_dump(),
            "questionnaire": [f.model_dump() for f in item_asset.questionnaire_fields],
            "selling_points": item_asset.selling_points,
        }
    else:
        result["item"] = {"status": "rejected", "reason": "大型物品不支持"}

    # 第 3 步：创建人物素材（返回造型方案供选择，v10 含场景信息）
    model_id = asset_manager.generate_id(AssetType.MODEL)
    model_asset, look_paths = await create_model_asset(
        asset_id=model_id,
        description=parsed["model_description"],
    )
    asset_manager.save_model(model_asset)
    result["model"] = {
        "asset": model_asset.model_dump(),
        "look_options": look_paths,
    }

    return {
        "status": "ok",
        "parsed": parsed,
        "assets": result,
        "message": "两类素材已创建，请确认物品问卷并选择人物方案",
    }


# ========== 视频生成 API（旧版兼容） ==========

@app.post("/api/generate", response_model=JobResponse)
async def generate_video(
    product_type: str = Form(..., description="产品类型"),
    product_usage: str = Form(..., description="产品使用方式描述"),
    platform: Platform = Form(..., description="目标平台"),
    duration: Duration = Form(..., description="视频时长"),
    selling_point: str = Form(..., description="核心卖点"),
    product_images: list[UploadFile] = File(..., description="产品参考图"),
):
    """
    创建视频生成任务（旧版接口，直接传产品信息）
    后续将切换到 /api/generate/v2（基于素材库）
    """
    job_id = str(uuid.uuid4())[:8]
    logger.info(f"[Job {job_id}] 收到生成请求: 产品={product_type}, 平台={platform}, 时长={duration}")

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
    segment_info = DURATION_SEGMENT_MAP[duration.value]
    aspect_ratio = PLATFORM_ASPECT_MAP[platform.value]

    # 创建任务
    job_data = {
        "job_id": job_id,
        "product_type": product_type,
        "product_usage": product_usage,
        "platform": platform.value,
        "duration": duration.value,
        "selling_point": selling_point,
        "product_images": image_paths,
        "segment_count": segment_info["segments"],
        "frame_count": segment_info["frames"],
        "aspect_ratio": aspect_ratio,
    }
    job_manager.create_job(job_id, job_data)

    # 启动 DA Agent 流水线（后台异步执行，不阻塞响应）
    asyncio.create_task(run_pipeline(job_id, job_manager))
    logger.info(f"[Job {job_id}] DA 流水线已启动")

    return JobResponse(job_id=job_id, status=JobStatus.PENDING, message="任务已创建，正在生成脚本...")


# ========== 视频生成 API（v2：基于素材库） ==========

@app.post("/api/generate/v2", response_model=JobResponse)
async def generate_video_v2(
    item_id: str = Form(..., description="物品素材 ID"),
    model_id: str = Form(..., description="人物素材 ID"),
    platform: Platform = Form(..., description="目标平台"),
    duration: Duration = Form(..., description="视频时长"),
    extra_requirements: str = Form("", description="额外要求"),
):
    """
    创建视频生成任务（v2：基于素材库选择）
    用户从素材库选择 1 物品 + 1 人物，组合生成视频
    v10：场景信息已融入人物素材（scene_context + portrait_image）
    """
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
        f"物品={item.name}, 人物={model.name}"
    )

    segment_info = DURATION_SEGMENT_MAP[duration.value]
    aspect_ratio = PLATFORM_ASPECT_MAP[platform.value]

    # 创建任务（包含素材档案信息，场景信息从 model 中获取）
    job_data = {
        "job_id": job_id,
        "mode": "v2_assets",
        "item": item.model_dump(),
        "model": model.model_dump(),
        "platform": platform.value,
        "duration": duration.value,
        "extra_requirements": extra_requirements,
        "segment_count": segment_info["segments"],
        "frame_count": segment_info["frames"],
        "aspect_ratio": aspect_ratio,
    }
    job_manager.create_job(job_id, job_data)

    asyncio.create_task(run_pipeline(job_id, job_manager))
    logger.info(f"[Job {job_id}] DA v2 流水线已启动")

    return JobResponse(job_id=job_id, status=JobStatus.PENDING, message="任务已创建，正在生成脚本...")


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
    """SSE 实时进度推送"""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"任务 {job_id} 不存在")

    async def event_generator() -> AsyncGenerator[str, None]:
        while True:
            progress = job_manager.get_progress(job_id)
            data = json.dumps(progress.model_dump(), ensure_ascii=False)
            yield f"data: {data}\n\n"
            if progress.status in (JobStatus.COMPLETED, JobStatus.FAILED):
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

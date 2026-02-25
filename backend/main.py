"""
VlogForge - AI Vlog 带货视频生成器
FastAPI 入口文件
"""

import os
import uuid
import json
import logging
from typing import AsyncGenerator

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from backend.config import PORT, ARTIFACTS_DIR, DURATION_SEGMENT_MAP, PLATFORM_ASPECT_MAP
from backend.models import (
    Platform, Duration, JobStatus,
    GenerateRequest, JobResponse, ProgressResponse,
)
from backend.services.job_manager import JobManager
from backend.agents.da_agent import run_pipeline

# 日志配置
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="VlogForge",
    description="AI Vlog 带货视频生成器 - Gemini Live Agent Challenge",
    version="0.1.0",
)

# 跨域（开发阶段允许所有来源）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 任务管理器
job_manager = JobManager()


# ========== API 端点 ==========

@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok", "service": "VlogForge"}


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
    创建视频生成任务
    接收用户 6 项输入，启动 Agent 流水线
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
    import asyncio
    asyncio.create_task(run_pipeline(job_id, job_manager))
    logger.info(f"[Job {job_id}] DA 流水线已启动")

    return JobResponse(job_id=job_id, status=JobStatus.PENDING, message="任务已创建，正在生成脚本...")


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
            import asyncio
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


# 挂载前端静态文件
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")


# ========== 启动入口 ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend.main:app", host="0.0.0.0", port=PORT, reload=True)

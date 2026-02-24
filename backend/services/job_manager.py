"""
任务管理器
负责任务的创建、状态追踪、进度查询
开发阶段使用内存存储，部署后可切换到 Redis / Firestore
"""

import logging
from typing import Optional

from backend.models import JobStatus, ProgressResponse

logger = logging.getLogger(__name__)


class JobManager:
    """内存任务管理器"""

    def __init__(self):
        # job_id -> job_data (dict)
        self._jobs: dict[str, dict] = {}

    def create_job(self, job_id: str, data: dict) -> None:
        """创建新任务"""
        data["status"] = JobStatus.PENDING
        data["progress"] = 0.0
        data["message"] = "任务已创建"
        data["script"] = None
        data["storyboard_urls"] = []
        data["segment_urls"] = []
        data["final_video"] = None
        self._jobs[job_id] = data
        logger.info(f"[Job {job_id}] 任务已创建: 产品={data.get('product_type')}")

    def get_job(self, job_id: str) -> Optional[dict]:
        """获取任务数据"""
        return self._jobs.get(job_id)

    def update_job(self, job_id: str, **kwargs) -> None:
        """更新任务字段"""
        job = self._jobs.get(job_id)
        if not job:
            logger.warning(f"[Job {job_id}] 尝试更新不存在的任务")
            return
        job.update(kwargs)
        logger.info(f"[Job {job_id}] 状态更新: {kwargs.get('status', '')} {kwargs.get('message', '')}")

    def get_progress(self, job_id: str) -> ProgressResponse:
        """获取任务进度"""
        job = self._jobs.get(job_id)
        if not job:
            return ProgressResponse(
                job_id=job_id,
                status=JobStatus.FAILED,
                message="任务不存在",
            )
        return ProgressResponse(
            job_id=job_id,
            status=job["status"],
            progress=job["progress"],
            message=job["message"],
            script=job.get("script"),
            storyboard_urls=job.get("storyboard_urls", []),
            segment_urls=job.get("segment_urls", []),
            final_video_url=f"/api/download/{job_id}" if job.get("final_video") else None,
        )

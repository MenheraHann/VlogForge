"""
任务管理器
负责任务的创建、状态追踪、进度查询、FIFO 队列管理
v14：新增串行队列 + 取消功能
开发阶段使用内存存储，部署后可切换到 Redis / Firestore
"""

import asyncio
import logging
import time
from typing import Optional, Callable, Coroutine, Any

from backend.models import JobStatus, ProgressResponse

logger = logging.getLogger(__name__)


class JobManager:
    """内存任务管理器（v14：含 FIFO 队列 + 取消支持）"""

    def __init__(self):
        # job_id -> job_data (dict)，存储所有任务的元数据
        self._jobs: dict[str, dict] = {}
        # FIFO 任务队列，存储排队中的 job_id
        self._queue: list[str] = []
        # 当前正在运行的 asyncio.Task（同一时刻只有一个任务在跑）
        self._current_task: Optional[asyncio.Task] = None
        # 当前正在运行的 job_id（方便判断取消目标）
        self._current_job_id: Optional[str] = None
        # 每个 job 的取消信号（asyncio.Event，set() 表示取消）
        self._cancel_events: dict[str, asyncio.Event] = {}
        # 流水线启动回调，由 main.py 注入（避免循环导入）
        self._pipeline_runner: Optional[Callable[..., Coroutine[Any, Any, None]]] = None

    def set_pipeline_runner(self, runner: Callable[..., Coroutine[Any, Any, None]]) -> None:
        """
        注入流水线执行函数。
        main.py 在启动时调用，传入 run_pipeline 的引用，避免 job_manager 直接导入 da_agent。
        """
        self._pipeline_runner = runner
        logger.info("[JobManager] 流水线执行函数已注入")

    def create_job(self, job_id: str, data: dict) -> None:
        """
        创建新任务（初始状态为 QUEUED，等待入队调度）。
        创建后需调用 enqueue_job() 才会进入队列。
        """
        data["job_id"] = job_id
        data["status"] = JobStatus.QUEUED
        data["progress"] = 0.0
        data["message"] = "排队中，等待前面的任务完成"
        data["script"] = None
        data["storyboard_urls"] = []
        data["segment_urls"] = []
        data["final_video"] = None
        data["created_at"] = time.time()  # 创建时间戳，用于排序
        self._jobs[job_id] = data

        # 为该 job 创建取消信号
        self._cancel_events[job_id] = asyncio.Event()

        logger.info(f"[Job {job_id}] 任务已创建（QUEUED）: 名称={data.get('task_name', '未命名')}")

    def enqueue_job(self, job_id: str) -> None:
        """
        将 job 加入 FIFO 队列尾部，然后尝试启动下一个任务。
        如果当前没有任务在运行，会立即启动该任务。
        """
        job = self._jobs.get(job_id)
        if not job:
            logger.warning(f"[Job {job_id}] enqueue 失败：任务不存在")
            return

        self._queue.append(job_id)
        queue_position = len(self._queue)
        logger.info(f"[Job {job_id}] 已加入队列（位置 #{queue_position}），队列长度={queue_position}")

        # 更新消息，告知用户排队位置
        if queue_position > 1:
            job["message"] = f"排队中（第 {queue_position} 位），等待前面的任务完成"

        # 尝试启动下一个任务
        self._try_start_next()

    def _try_start_next(self) -> None:
        """
        检查是否可以启动下一个任务。
        条件：当前没有任务在运行 + 队列不为空。
        """
        if self._current_task is not None:
            logger.debug("[JobManager] 已有任务在运行，跳过启动")
            return

        if not self._queue:
            logger.info("[JobManager] 队列为空，无任务可启动")
            return

        if self._pipeline_runner is None:
            logger.error("[JobManager] 流水线执行函数未注入，无法启动任务")
            return

        # 从队列头部取出下一个 job
        next_job_id = self._queue.pop(0)
        job = self._jobs.get(next_job_id)

        if not job:
            logger.warning(f"[Job {next_job_id}] 出队时任务不存在，跳过")
            self._try_start_next()  # 递归尝试下一个
            return

        # 如果该任务已被取消（在排队期间被取消），跳过
        if job["status"] == JobStatus.CANCELLED:
            logger.info(f"[Job {next_job_id}] 已取消，跳过")
            self._try_start_next()
            return

        # 更新状态为 PENDING（即将开始执行）
        self._current_job_id = next_job_id
        job["status"] = JobStatus.PENDING
        job["message"] = "任务即将开始执行..."
        logger.info(f"[Job {next_job_id}] 出队，开始执行流水线")

        # 更新队列中剩余任务的排队位置消息
        for i, queued_id in enumerate(self._queue):
            queued_job = self._jobs.get(queued_id)
            if queued_job and queued_job["status"] == JobStatus.QUEUED:
                queued_job["message"] = f"排队中（第 {i + 1} 位），等待前面的任务完成"

        # 获取取消信号
        cancel_event = self._cancel_events.get(next_job_id)

        # 启动异步任务
        self._current_task = asyncio.create_task(
            self._pipeline_runner(next_job_id, self, cancel_event)
        )
        # 添加完成回调，确保清理 + 启动下一个
        self._current_task.add_done_callback(
            lambda t: asyncio.get_event_loop().call_soon(self._on_task_done, next_job_id, t)
        )

    def _on_task_done(self, job_id: str, task: asyncio.Task) -> None:
        """
        asyncio.Task 完成回调（无论成功、失败、取消）。
        清理 _current_task，尝试启动队列中的下一个任务。
        """
        self._current_task = None
        self._current_job_id = None

        # 检查任务是否因异常而结束（非正常取消/完成）
        if task.cancelled():
            logger.info(f"[Job {job_id}] asyncio.Task 已取消")
        elif task.exception():
            logger.error(f"[Job {job_id}] asyncio.Task 异常退出: {task.exception()}")

        logger.info(f"[Job {job_id}] 任务结束，检查队列中的下一个任务...")
        self._try_start_next()

    def on_job_finished(self, job_id: str) -> None:
        """
        任务完成/失败/取消的回调（由 run_pipeline 的 finally 块调用）。
        主要用于日志和清理，实际的队列调度由 _on_task_done 处理。
        """
        job = self._jobs.get(job_id)
        status = job["status"] if job else "unknown"
        logger.info(f"[Job {job_id}] on_job_finished 被调用，最终状态={status}")

        # 清理取消信号（可选，节省内存）
        self._cancel_events.pop(job_id, None)

    def cancel_job(self, job_id: str) -> dict:
        """
        取消指定任务。
        - 如果是排队中的任务：直接标记 CANCELLED，从队列中移除
        - 如果是当前运行的任务：设置取消信号 + cancel asyncio.Task
        - 如果已完成/已失败：返回错误

        返回操作结果 dict。
        """
        job = self._jobs.get(job_id)
        if not job:
            return {"status": "error", "message": f"任务 {job_id} 不存在"}

        current_status = job["status"]

        # 已经是终态，不能取消
        if current_status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
            return {
                "status": "error",
                "message": f"任务 {job_id} 已经是 {current_status.value} 状态，无法取消",
            }

        # 排队中的任务：直接标记取消，从队列移除
        if current_status == JobStatus.QUEUED:
            job["status"] = JobStatus.CANCELLED
            job["message"] = "用户取消了任务"
            if job_id in self._queue:
                self._queue.remove(job_id)
                logger.info(f"[Job {job_id}] 排队中的任务已取消并移出队列")

                # 更新队列中剩余任务的排队位置消息
                for i, queued_id in enumerate(self._queue):
                    queued_job = self._jobs.get(queued_id)
                    if queued_job and queued_job["status"] == JobStatus.QUEUED:
                        queued_job["message"] = f"排队中（第 {i + 1} 位），等待前面的任务完成"

            self._cancel_events.pop(job_id, None)
            return {"status": "ok", "message": f"排队中的任务 {job_id} 已取消"}

        # 正在运行的任务：设置取消信号 + cancel asyncio.Task
        cancel_event = self._cancel_events.get(job_id)
        if cancel_event:
            cancel_event.set()
            logger.info(f"[Job {job_id}] 取消信号已设置")

        if self._current_job_id == job_id and self._current_task:
            self._current_task.cancel()
            logger.info(f"[Job {job_id}] asyncio.Task 已发送 cancel")

        return {"status": "ok", "message": f"正在取消任务 {job_id}..."}

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

    def get_all_jobs(self) -> list[dict]:
        """
        返回所有任务列表，按创建时间排序（最新的在前）。
        每个 job 返回精简信息，供前端队列面板渲染。
        """
        jobs = []
        for job_id, job in self._jobs.items():
            jobs.append({
                "job_id": job_id,
                "status": job["status"].value if isinstance(job["status"], JobStatus) else job["status"],
                "progress": job.get("progress", 0.0),
                "message": job.get("message", ""),
                "task_name": job.get("task_name", "未命名任务"),
                "platform": job.get("platform", ""),
                "duration": job.get("duration", ""),
                "created_at": job.get("created_at", 0),
            })
        # 按创建时间降序排列（最新的在前）
        jobs.sort(key=lambda x: x["created_at"], reverse=True)
        return jobs

    def get_queue_info(self) -> dict:
        """
        获取队列概况，用于调试和状态展示。
        """
        return {
            "queue_length": len(self._queue),
            "queued_jobs": list(self._queue),
            "current_job": self._current_job_id,
            "total_jobs": len(self._jobs),
        }

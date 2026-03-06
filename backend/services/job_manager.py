"""
任务管理器
负责任务的创建、状态追踪、进度查询、FIFO 队列管理
v14：新增串行队列 + 取消功能
开发阶段使用内存存储，部署后可切换到 Redis / Firestore
"""

import asyncio
import json
import logging
import os
import time
from typing import Optional, Callable, Coroutine, Any

from backend.config import ARTIFACTS_DIR
from backend.models import JobStatus, ProgressResponse

logger = logging.getLogger(__name__)

# 持久化文件路径
JOBS_PERSIST_FILE = os.path.join(ARTIFACTS_DIR, "_jobs_data.json")

# 非终态状态集合（重启后需标记为 FAILED）
_NON_TERMINAL_STATUSES = {
    JobStatus.QUEUED, JobStatus.PENDING,
    JobStatus.SCRIPT_GENERATING, JobStatus.IMAGES_GENERATING,
    JobStatus.VIDEOS_GENERATING, JobStatus.STITCHING,
}


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

        # 启动时从磁盘恢复任务数据
        self._load_from_disk()

    # ========== 持久化 ==========

    def _load_from_disk(self) -> None:
        """启动时恢复任务数据。GCS 模式优先从 GCS 读取，本地模式读本地文件。非终态任务标记为 FAILED"""
        raw_jobs = None

        # GCS 模式：优先从 GCS 读取
        from backend.config import USE_GCS
        if USE_GCS:
            try:
                from backend.services.gcs_client import download_blob
                blob_data = download_blob("artifacts/_jobs_data.json")
                if blob_data:
                    raw_jobs = json.loads(blob_data.decode("utf-8"))
                    logger.info("[JobManager] 从 GCS 加载任务数据成功")
            except Exception as e:
                logger.warning(f"[JobManager] GCS 读取失败，降级到本地: {e}")

        # 本地读取
        if raw_jobs is None:
            if not os.path.exists(JOBS_PERSIST_FILE):
                logger.info("[JobManager] 无历史任务数据文件，跳过恢复")
                return
            try:
                with open(JOBS_PERSIST_FILE, "r", encoding="utf-8") as f:
                    raw_jobs = json.load(f)
            except Exception as e:
                logger.error(f"[JobManager] 恢复任务数据失败: {e}")
                return
        try:
            recovered = 0
            for job_id, job_data in raw_jobs.items():
                # 将字符串状态恢复为 JobStatus 枚举
                status_str = job_data.get("status", "")
                try:
                    job_data["status"] = JobStatus(status_str)
                except ValueError:
                    job_data["status"] = JobStatus.FAILED
                # 非终态任务标记为 FAILED（重启后实际任务已丢失）
                if job_data["status"] in _NON_TERMINAL_STATUSES:
                    old_status = job_data["status"].value
                    job_data["status"] = JobStatus.FAILED
                    job_data["message"] = f"服务重启，任务未能完成（重启前状态: {old_status}）"
                    logger.warning(f"[Job {job_id}] 重启恢复: {old_status} → failed")
                    recovered += 1
                self._jobs[job_id] = job_data
            logger.info(f"[JobManager] 从磁盘恢复 {len(raw_jobs)} 个任务，{recovered} 个标记为 failed")
            if recovered > 0:
                self._save_to_disk()
        except Exception as e:
            logger.error(f"[JobManager] 恢复任务数据失败: {e}")

    def _save_to_disk(self) -> None:
        """将任务数据原子写入磁盘（tmp + os.replace），GCS 模式下同时上传"""
        try:
            # 序列化：将 JobStatus 枚举转为字符串
            serializable = {}
            for job_id, job_data in self._jobs.items():
                entry = {}
                for k, v in job_data.items():
                    if isinstance(v, JobStatus):
                        entry[k] = v.value
                    else:
                        entry[k] = v
                serializable[job_id] = entry
            json_str = json.dumps(serializable, ensure_ascii=False, indent=2, default=str)
            tmp_path = JOBS_PERSIST_FILE + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(json_str)
            os.replace(tmp_path, JOBS_PERSIST_FILE)

        except Exception as e:
            logger.error(f"[JobManager] 持久化任务数据失败: {e}")
            return

        # GCS 双写（独立 try/except，不影响本地持久化结果）
        from backend.config import USE_GCS
        if USE_GCS:
            try:
                from backend.services.gcs_client import upload_blob
                upload_blob("artifacts/_jobs_data.json", json_str.encode("utf-8"), "application/json")
            except Exception as e:
                logger.warning(f"[JobManager] GCS 上传任务数据失败（本地已保存）: {e}")

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
        self._save_to_disk()

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

        self._save_to_disk()
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
        self._save_to_disk()

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
        self._save_to_disk()

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
            self._save_to_disk()
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
        self._save_to_disk()

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

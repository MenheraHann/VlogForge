"""
DA Agent - 创意总监（Decision Agent）
负责：接收用户输入 → 拆解任务 → 调度 Sub-Agent → 验收 → 拼接输出
是整个流水线的编排核心，对用户的唯一出口

当前实现：D3 骨架，只接通 TA，VA/VGA/QA/FFmpeg 为占位
"""

import logging
import traceback

from backend.models import JobStatus, ScriptOutput
from backend.services.job_manager import JobManager
from backend.agents.ta_agent import generate_script
from backend.config import DURATION_SEGMENT_MAP, PLATFORM_ASPECT_MAP

logger = logging.getLogger(__name__)


async def run_pipeline(job_id: str, job_manager: JobManager) -> None:
    """
    执行完整的视频生成流水线。
    由 main.py 在后台异步调用，通过 job_manager 更新进度。

    流水线：TA → VA → VGA → QA → FFmpeg
    当前 D3 只实现 TA 阶段，其余为占位。
    """
    job = job_manager.get_job(job_id)
    if not job:
        logger.error(f"[DA][Job {job_id}] 任务不存在，无法启动流水线")
        return

    try:
        # ========== 阶段 1：TA 生成脚本 ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.05,
            message="正在生成脚本...",
        )

        script = await generate_script(
            product_type=job["product_type"],
            product_usage=job["product_usage"],
            platform=job["platform"],
            duration=job["duration"],
            selling_point=job["selling_point"],
            segment_count=job["segment_count"],
            aspect_ratio=job["aspect_ratio"],
        )

        # 保存脚本到 job
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.15,
            message=f"脚本生成完成：「{script.title}」，共 {len(script.segments)} 段",
            script=script,
        )
        logger.info(f"[DA][Job {job_id}] TA 完成：「{script.title}」")

        # ========== 阶段 2：VA 生成分镜图（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.IMAGES_GENERATING,
            progress=0.20,
            message="分镜图生成待实现（VA Agent）...",
        )
        logger.info(f"[DA][Job {job_id}] VA 占位 — 分镜图生成待实现")

        # TODO: D5-D7 实现
        # storyboard_urls = await va_agent.generate_storyboard(script, job)
        # job_manager.update_job(job_id, storyboard_urls=storyboard_urls, ...)

        # ========== 阶段 3：VGA 生成视频片段（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.VIDEOS_GENERATING,
            progress=0.40,
            message="视频片段生成待实现（VGA Agent）...",
        )
        logger.info(f"[DA][Job {job_id}] VGA 占位 — 视频片段生成待实现")

        # TODO: D9-D10 实现
        # segment_urls = await vga_agent.generate_segments(storyboard_urls, script, job)
        # job_manager.update_job(job_id, segment_urls=segment_urls, ...)

        # ========== 阶段 4：QA 审核（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.QA_REVIEWING,
            progress=0.70,
            message="质量审核待实现（QA Agent）...",
        )
        logger.info(f"[DA][Job {job_id}] QA 占位 — 质量审核待实现")

        # TODO: D12 实现
        # qa_result = await qa_agent.review(segment_urls, script)

        # ========== 阶段 5：FFmpeg 拼接（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.STITCHING,
            progress=0.85,
            message="视频拼接待实现（FFmpeg）...",
        )
        logger.info(f"[DA][Job {job_id}] FFmpeg 占位 — 视频拼接待实现")

        # TODO: D11 实现
        # final_path = await ffmpeg_tools.stitch(segment_urls, job)
        # job_manager.update_job(job_id, final_video=final_path, ...)

        # ========== 当前阶段：标记完成（仅脚本） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            message="脚本生成完成（VA/VGA/QA/FFmpeg 待实现）",
        )
        logger.info(f"[DA][Job {job_id}] 流水线完成（D3 骨架）")

    except Exception as e:
        logger.error(f"[DA][Job {job_id}] 流水线失败: {e}\n{traceback.format_exc()}")
        job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0.0,
            message=f"生成失败：{str(e)}",
        )

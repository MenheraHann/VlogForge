"""
存储工具
开发阶段使用本地文件系统，GCS 模式下同时上传到 Cloud Storage
"""

import os
import logging

from backend.config import ARTIFACTS_DIR, USE_GCS

logger = logging.getLogger(__name__)


def save_artifact(job_id: str, filename: str, data: bytes) -> str:
    """
    保存中间产物（图片/视频）到本地，GCS 模式下同时上传
    返回文件路径
    """
    job_dir = os.path.join(ARTIFACTS_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    path = os.path.join(job_dir, filename)
    with open(path, "wb") as f:
        f.write(data)
    logger.info(f"[Job {job_id}] 产物已保存: {filename}")

    # GCS 双写
    if USE_GCS:
        try:
            from backend.services.gcs_client import upload_blob
            relative = f"artifacts/{job_id}/{filename}"
            import mimetypes
            ct, _ = mimetypes.guess_type(filename)
            upload_blob(relative, data, ct or "application/octet-stream")
        except Exception as e:
            logger.warning(f"[Job {job_id}] GCS 上传失败（不影响本地文件）: {e}")

    return path


def get_artifact_path(job_id: str, filename: str) -> str:
    """获取产物的文件路径"""
    return os.path.join(ARTIFACTS_DIR, job_id, filename)


def list_artifacts(job_id: str) -> list[str]:
    """列出任务的所有产物文件"""
    job_dir = os.path.join(ARTIFACTS_DIR, job_id)
    if not os.path.exists(job_dir):
        return []
    return os.listdir(job_dir)

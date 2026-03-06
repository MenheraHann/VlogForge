"""
Google Cloud Storage 客户端封装
延迟初始化，GCS_BUCKET_NAME 为空时所有操作 gracefully 返回 None
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 延迟初始化的单例
_client = None
_bucket = None


def _ensure_client():
    """延迟初始化 GCS Client 单例"""
    global _client, _bucket
    if _client is not None:
        return

    from backend.config import GCS_BUCKET_NAME
    if not GCS_BUCKET_NAME:
        raise RuntimeError("GCS_BUCKET_NAME 未配置，无法初始化 GCS 客户端")

    from google.cloud import storage
    _client = storage.Client()
    _bucket = _client.bucket(GCS_BUCKET_NAME)
    logger.info(f"[GCS] 客户端已初始化: bucket={GCS_BUCKET_NAME}")


def upload_blob(blob_path: str, data: bytes, content_type: str = "application/octet-stream") -> Optional[str]:
    """
    上传数据到 GCS
    返回 gs:// 路径，失败返回 None
    """
    try:
        _ensure_client()
        blob = _bucket.blob(blob_path)
        blob.upload_from_string(data, content_type=content_type)
        logger.info(f"[GCS] 已上传: {blob_path} ({len(data)} bytes)")
        return f"gs://{_bucket.name}/{blob_path}"
    except Exception as e:
        logger.error(f"[GCS] 上传失败 {blob_path}: {e}")
        return None


def download_blob(blob_path: str) -> Optional[bytes]:
    """
    从 GCS 下载数据
    失败返回 None
    """
    try:
        _ensure_client()
        blob = _bucket.blob(blob_path)
        return blob.download_as_bytes()
    except Exception as e:
        logger.error(f"[GCS] 下载失败 {blob_path}: {e}")
        return None


def blob_exists(blob_path: str) -> bool:
    """检查 GCS 对象是否存在"""
    try:
        _ensure_client()
        blob = _bucket.blob(blob_path)
        return blob.exists()
    except Exception as e:
        logger.error(f"[GCS] 检查存在失败 {blob_path}: {e}")
        return False

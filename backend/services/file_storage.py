"""
统一文件存储服务
检测 GCS_BUCKET_NAME 环境变量：有则双写（本地 + GCS），无则仅本地
FFmpeg 等工具始终通过 save_local() 写本地文件
"""

import os
import logging
import mimetypes
from typing import Optional

from backend.config import USE_GCS, ARTIFACTS_DIR, ASSETS_DIR

logger = logging.getLogger(__name__)


class FileStorage:
    """统一文件存储：本地 + 可选 GCS"""

    def __init__(self):
        self._use_gcs = USE_GCS

    def _local_path(self, relative_path: str) -> str:
        """根据路径前缀推断本地绝对路径"""
        if relative_path.startswith("artifacts/"):
            return os.path.join(ARTIFACTS_DIR, relative_path[len("artifacts/"):])
        elif relative_path.startswith("assets/"):
            return os.path.join(ASSETS_DIR, relative_path[len("assets/"):])
        # 默认放 artifacts
        return os.path.join(ARTIFACTS_DIR, relative_path)

    def _guess_content_type(self, path: str) -> str:
        """根据扩展名猜测 MIME 类型"""
        ct, _ = mimetypes.guess_type(path)
        return ct or "application/octet-stream"

    def save(self, relative_path: str, data: bytes, content_type: str = "") -> str:
        """
        保存文件：写本地 + 如果启用了 GCS 则同时上传
        relative_path 格式: "assets/item_001/thumbnail.png" 或 "artifacts/job_123/final.mp4"
        返回本地文件路径
        """
        # 始终写本地
        local_path = self.save_local(relative_path, data)

        # GCS 双写
        if self._use_gcs:
            from backend.services.gcs_client import upload_blob
            ct = content_type or self._guess_content_type(relative_path)
            upload_blob(relative_path, data, ct)

        return local_path

    def save_local(self, relative_path: str, data: bytes) -> str:
        """
        始终写本地文件（FFmpeg 等工具需要本地路径）
        返回本地绝对路径
        """
        local_path = self._local_path(relative_path)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        with open(local_path, "wb") as f:
            f.write(data)
        return local_path

    def read(self, relative_path: str) -> Optional[bytes]:
        """
        读取文件：优先本地，本地没有时尝试 GCS
        """
        local_path = self._local_path(relative_path)

        # 先尝试本地
        if os.path.exists(local_path):
            with open(local_path, "rb") as f:
                return f.read()

        # 本地没有，尝试 GCS
        if self._use_gcs:
            from backend.services.gcs_client import download_blob
            data = download_blob(relative_path)
            if data is not None:
                # 缓存到本地
                os.makedirs(os.path.dirname(local_path), exist_ok=True)
                with open(local_path, "wb") as f:
                    f.write(data)
                return data

        return None

    def exists(self, relative_path: str) -> bool:
        """检查文件是否存在（本地或 GCS）"""
        local_path = self._local_path(relative_path)
        if os.path.exists(local_path):
            return True
        if self._use_gcs:
            from backend.services.gcs_client import blob_exists
            return blob_exists(relative_path)
        return False


# 全局单例
file_storage = FileStorage()

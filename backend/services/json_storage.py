"""
JSON 文件存储后端
将素材数据以 JSON 文件形式持久化到磁盘，服务重启后可自动恢复
采用 tmp + rename 原子写入策略，避免写到一半崩溃导致文件损坏
"""

import json
import logging
import os

from backend.config import ASSETS_DIR
from backend.models import AssetType, ItemAsset, ModelAsset
from backend.services.storage_backend import StorageBackend

logger = logging.getLogger(__name__)

# 持久化文件路径（存放在 assets 目录下，以 _ 开头避免与素材文件夹混淆）
PERSIST_FILE = os.path.join(ASSETS_DIR, "_assets_data.json")


class JsonStorageBackend(StorageBackend):
    """基于本地 JSON 文件的存储后端实现"""

    def load_all(self) -> tuple[dict[str, ItemAsset], dict[str, ModelAsset], dict[AssetType, int]]:
        """
        加载所有素材数据。
        GCS 模式：优先从 GCS 读取，失败则读本地。
        本地模式：直接读本地文件。
        """
        data = None

        # GCS 模式：优先从 GCS 读取
        from backend.config import USE_GCS
        if USE_GCS:
            try:
                from backend.services.gcs_client import download_blob
                blob_data = download_blob("assets/_assets_data.json")
                if blob_data:
                    data = json.loads(blob_data.decode("utf-8"))
                    logger.info("[JsonStorage] 从 GCS 加载素材数据成功")
            except Exception as e:
                logger.warning(f"[JsonStorage] GCS 读取失败，降级到本地: {e}")

        # 本地读取
        if data is None:
            if not os.path.exists(PERSIST_FILE):
                logger.info(f"[JsonStorage] 持久化文件不存在，首次启动: {PERSIST_FILE}")
                return {}, {}, {AssetType.ITEM: 0, AssetType.MODEL: 0}
            try:
                with open(PERSIST_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"[JsonStorage] 读取持久化文件失败: {e}，将使用空数据启动")
                return {}, {}, {AssetType.ITEM: 0, AssetType.MODEL: 0}

        # 反序列化物品素材
        items: dict[str, ItemAsset] = {}
        for k, v in data.get("items", {}).items():
            try:
                items[k] = ItemAsset(**v)
            except Exception as e:
                logger.warning(f"[JsonStorage] 物品 {k} 反序列化失败，跳过: {e}")

        # 反序列化人物素材
        models: dict[str, ModelAsset] = {}
        for k, v in data.get("models", {}).items():
            try:
                models[k] = ModelAsset(**v)
            except Exception as e:
                logger.warning(f"[JsonStorage] 人物 {k} 反序列化失败，跳过: {e}")

        # 恢复自增 ID 计数器
        raw_counters = data.get("counters", {})
        counters = {
            AssetType.ITEM: raw_counters.get("item", 0),
            AssetType.MODEL: raw_counters.get("model", 0),
        }

        logger.info(
            f"[JsonStorage] 数据加载完成: {len(items)} 个物品, {len(models)} 个人物, "
            f"计数器 item={counters[AssetType.ITEM]} model={counters[AssetType.MODEL]}"
        )
        return items, models, counters

    def save_all(
        self,
        items: dict[str, ItemAsset],
        models: dict[str, ModelAsset],
        counters: dict[AssetType, int],
    ) -> None:
        """
        将所有素材数据序列化为 JSON 并写入磁盘。
        使用 tmp + os.replace 原子操作，确保数据完整性。
        GCS 模式下同时上传到 Cloud Storage。
        """
        data = {
            "items": {k: v.model_dump(mode="json") for k, v in items.items()},
            "models": {k: v.model_dump(mode="json") for k, v in models.items()},
            "counters": {k.value: v for k, v in counters.items()},
        }

        # 确保目录存在
        os.makedirs(os.path.dirname(PERSIST_FILE), exist_ok=True)

        # 先写临时文件，再原子替换，避免写到一半崩溃导致文件损坏
        tmp_file = PERSIST_FILE + ".tmp"
        try:
            json_str = json.dumps(data, ensure_ascii=False, indent=2)
            with open(tmp_file, "w", encoding="utf-8") as f:
                f.write(json_str)
            os.replace(tmp_file, PERSIST_FILE)
            logger.debug(
                f"[JsonStorage] 数据已持久化: {len(items)} 个物品, {len(models)} 个人物"
            )

        except IOError as e:
            logger.error(f"[JsonStorage] 写入持久化文件失败: {e}")
            # 清理可能残留的临时文件
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass
            return

        # GCS 双写（独立 try/except，不影响本地持久化结果）
        from backend.config import USE_GCS
        if USE_GCS:
            try:
                from backend.services.gcs_client import upload_blob
                upload_blob("assets/_assets_data.json", json_str.encode("utf-8"), "application/json")
            except Exception as e:
                logger.warning(f"[JsonStorage] GCS 上传数据失败（本地已保存）: {e}")

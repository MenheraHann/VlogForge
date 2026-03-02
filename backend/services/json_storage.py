"""
JSON 文件存储后端
将素材数据以 JSON 文件形式持久化到磁盘，服务重启后可自动恢复
采用 tmp + rename 原子写入策略，避免写到一半崩溃导致文件损坏
"""

import json
import logging
import os

from backend.config import ASSETS_DIR
from backend.models import AssetType, GameAsset, ItemAsset, ModelAsset
from backend.services.storage_backend import StorageBackend

logger = logging.getLogger(__name__)

# 持久化文件路径（存放在 assets 目录下，以 _ 开头避免与素材文件夹混淆）
PERSIST_FILE = os.path.join(ASSETS_DIR, "_assets_data.json")


class JsonStorageBackend(StorageBackend):
    """基于本地 JSON 文件的存储后端实现"""

    def load_all(self) -> tuple[dict[str, ItemAsset], dict[str, ModelAsset], dict[str, GameAsset], dict[AssetType, int]]:
        """
        从磁盘 JSON 文件加载所有素材数据。
        文件不存在时返回空数据（首次启动）。
        """
        empty_counters = {AssetType.ITEM: 0, AssetType.MODEL: 0, AssetType.GAME: 0}

        if not os.path.exists(PERSIST_FILE):
            logger.info(f"[JsonStorage] 持久化文件不存在，首次启动: {PERSIST_FILE}")
            return {}, {}, {}, empty_counters

        try:
            with open(PERSIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"[JsonStorage] 读取持久化文件失败: {e}，将使用空数据启动")
            return {}, {}, {}, empty_counters

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

        # 反序列化游戏素材
        games: dict[str, GameAsset] = {}
        for k, v in data.get("games", {}).items():
            try:
                games[k] = GameAsset(**v)
            except Exception as e:
                logger.warning(f"[JsonStorage] 游戏 {k} 反序列化失败，跳过: {e}")

        # 恢复自增 ID 计数器
        raw_counters = data.get("counters", {})
        counters = {
            AssetType.ITEM: raw_counters.get("item", 0),
            AssetType.MODEL: raw_counters.get("model", 0),
            AssetType.GAME: raw_counters.get("game", 0),
        }

        logger.info(
            f"[JsonStorage] 数据加载完成: {len(items)} 个物品, {len(models)} 个人物, {len(games)} 个游戏, "
            f"计数器 item={counters[AssetType.ITEM]} model={counters[AssetType.MODEL]} game={counters[AssetType.GAME]}"
        )
        return items, models, games, counters

    def save_all(
        self,
        items: dict[str, ItemAsset],
        models: dict[str, ModelAsset],
        games: dict[str, GameAsset],
        counters: dict[AssetType, int],
    ) -> None:
        """
        将所有素材数据序列化为 JSON 并写入磁盘。
        使用 tmp + os.replace 原子操作，确保数据完整性。
        """
        data = {
            "items": {k: v.model_dump(mode="json") for k, v in items.items()},
            "models": {k: v.model_dump(mode="json") for k, v in models.items()},
            "games": {k: v.model_dump(mode="json") for k, v in games.items()},
            "counters": {k.value: v for k, v in counters.items()},
        }

        # 确保目录存在
        os.makedirs(os.path.dirname(PERSIST_FILE), exist_ok=True)

        # 先写临时文件，再原子替换，避免写到一半崩溃导致文件损坏
        tmp_file = PERSIST_FILE + ".tmp"
        try:
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_file, PERSIST_FILE)
            logger.debug(
                f"[JsonStorage] 数据已持久化: {len(items)} 个物品, {len(models)} 个人物, {len(games)} 个游戏"
            )
        except IOError as e:
            logger.error(f"[JsonStorage] 写入持久化文件失败: {e}")
            # 清理可能残留的临时文件
            if os.path.exists(tmp_file):
                try:
                    os.remove(tmp_file)
                except OSError:
                    pass

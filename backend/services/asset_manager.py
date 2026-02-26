"""
素材库管理器
负责素材的创建、存储、检索、更新
开发阶段使用内存存储，部署后可切换到 Firestore / GCS
"""

import logging
from typing import Optional, Union

from backend.models import AssetType, ItemAsset, ModelAsset

logger = logging.getLogger(__name__)

AssetUnion = Union[ItemAsset, ModelAsset]


class AssetManager:
    """内存素材管理器"""

    def __init__(self):
        # asset_id -> asset_data
        self._items: dict[str, ItemAsset] = {}
        self._models: dict[str, ModelAsset] = {}
        # 自增 ID 计数器
        self._counters = {
            AssetType.ITEM: 0,
            AssetType.MODEL: 0,
        }

    def generate_id(self, asset_type: AssetType) -> str:
        """生成自增素材 ID"""
        self._counters[asset_type] += 1
        prefix = {
            AssetType.ITEM: "item",
            AssetType.MODEL: "model",
        }[asset_type]
        return f"{prefix}_{self._counters[asset_type]:03d}"

    # ========== 物品 ==========

    def save_item(self, asset: ItemAsset) -> None:
        """保存物品素材"""
        self._items[asset.id] = asset
        logger.info(f"[AssetManager] 物品已保存: {asset.id} ({asset.name})")

    def get_item(self, asset_id: str) -> Optional[ItemAsset]:
        """获取物品素材"""
        return self._items.get(asset_id)

    def list_items(self) -> list[ItemAsset]:
        """列出所有物品素材"""
        return list(self._items.values())

    def delete_item(self, asset_id: str) -> bool:
        """删除物品素材"""
        if asset_id in self._items:
            del self._items[asset_id]
            logger.info(f"[AssetManager] 物品已删除: {asset_id}")
            return True
        return False

    # ========== 人物 ==========

    def save_model(self, asset: ModelAsset) -> None:
        """保存人物素材"""
        self._models[asset.id] = asset
        logger.info(f"[AssetManager] 人物已保存: {asset.id} ({asset.name})")

    def get_model(self, asset_id: str) -> Optional[ModelAsset]:
        """获取人物素材"""
        return self._models.get(asset_id)

    def list_models(self) -> list[ModelAsset]:
        """列出所有人物素材"""
        return list(self._models.values())

    def delete_model(self, asset_id: str) -> bool:
        """删除人物素材"""
        if asset_id in self._models:
            del self._models[asset_id]
            logger.info(f"[AssetManager] 人物已删除: {asset_id}")
            return True
        return False

    def update_model_portrait(self, asset_id: str, portrait_image: str) -> bool:
        """更新人物的半身近景照（v10：一图多用）"""
        model = self._models.get(asset_id)
        if model:
            model.portrait_image = portrait_image
            logger.info(f"[AssetManager] 人物 {asset_id} 半身近景照已更新: {portrait_image}")
            return True
        return False

    # ========== 通用 ==========

    def get_asset(self, asset_id: str) -> Optional[AssetUnion]:
        """根据 ID 前缀自动判断类型并获取素材"""
        if asset_id.startswith("item_"):
            return self.get_item(asset_id)
        elif asset_id.startswith("model_"):
            return self.get_model(asset_id)
        return None

    def get_stats(self) -> dict:
        """获取素材库统计"""
        return {
            "items": len(self._items),
            "models": len(self._models),
            "total": len(self._items) + len(self._models),
        }

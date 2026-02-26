"""
存储后端抽象接口
定义数据加载/保存的统一契约，便于未来从本地 JSON 切换到 GCS / Firestore
"""

from abc import ABC, abstractmethod
from typing import Any

from backend.models import AssetType, ItemAsset, ModelAsset


class StorageBackend(ABC):
    """存储后端抽象接口，便于切换本地 JSON / GCS / Firestore"""

    @abstractmethod
    def load_all(self) -> tuple[dict[str, ItemAsset], dict[str, ModelAsset], dict[AssetType, int]]:
        """
        启动时加载所有持久化数据。

        返回:
            (items_dict, models_dict, counters_dict)
            - items_dict:   asset_id -> ItemAsset
            - models_dict:  asset_id -> ModelAsset
            - counters_dict: AssetType -> int（自增 ID 计数器）
        """
        ...

    @abstractmethod
    def save_all(
        self,
        items: dict[str, ItemAsset],
        models: dict[str, ModelAsset],
        counters: dict[AssetType, int],
    ) -> None:
        """
        保存所有数据到持久层。

        参数:
            items:    当前所有物品素材
            models:   当前所有人物素材
            counters: 自增 ID 计数器
        """
        ...

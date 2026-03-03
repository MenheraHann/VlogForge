"""
素材库管理器
负责素材的创建、存储、检索、更新
通过 StorageBackend 接口实现数据持久化，默认使用 JSON 文件存储
"""

import logging
import os
from typing import Optional, Union

from backend.models import AssetStatus, AssetType, GameAsset, ItemAsset, ModelAsset
from backend.services.storage_backend import StorageBackend

logger = logging.getLogger(__name__)

AssetUnion = Union[ItemAsset, ModelAsset, GameAsset]


class AssetManager:
    """素材管理器（支持可插拔的持久化后端）"""

    def __init__(self, storage_backend: Optional[StorageBackend] = None):
        """
        初始化素材管理器。

        参数:
            storage_backend: 持久化后端实例。
                             未指定时默认使用 JsonStorageBackend（本地 JSON 文件）。
        """
        # 延迟导入，避免循环引用，同时让默认后端在未传参时才实例化
        if storage_backend is None:
            from backend.services.json_storage import JsonStorageBackend
            storage_backend = JsonStorageBackend()

        self._storage: StorageBackend = storage_backend

        # 从持久层恢复数据（首次启动时为空）
        self._items, self._models, self._games, self._counters = self._storage.load_all()

        logger.info(
            f"[AssetManager] 初始化完成，已恢复: "
            f"{len(self._items)} 个物品, {len(self._models)} 个人物, {len(self._games)} 个游戏"
        )

        # 启动时修复残留的 generating 状态素材
        self._recover_generating_assets()

    # ========== 启动恢复 ==========

    def _recover_generating_assets(self) -> None:
        """
        启动时检查所有 generating 状态的素材，尝试自动修复：
        - 物品：如果磁盘上 thumbnail_image 和 three_view_image 文件都存在，
                说明之前生成成功但状态未更新，自动改为 confirmed
        - 人物：如果有 look_options 但没有 portrait_image，说明需要用户选择，
                保持 generating 不自动修复，仅打日志提醒
        """
        recovered_count = 0

        # 修复物品
        for asset_id, item in self._items.items():
            if item.status != AssetStatus.GENERATING:
                continue

            thumb_exists = item.thumbnail_image and os.path.isfile(item.thumbnail_image)
            three_view_exists = item.three_view_image and os.path.isfile(item.three_view_image)

            if thumb_exists and three_view_exists:
                item.status = AssetStatus.CONFIRMED
                recovered_count += 1
                logger.info(
                    f"[AssetManager] 物品 {asset_id} ({item.name}) "
                    f"generating → confirmed（图片文件已存在，自动恢复）"
                )
            else:
                # 图片文件不全，可能生成中途崩溃，保持 generating 状态
                missing = []
                if not thumb_exists:
                    missing.append("thumbnail_image")
                if not three_view_exists:
                    missing.append("three_view_image")
                logger.warning(
                    f"[AssetManager] 物品 {asset_id} ({item.name}) "
                    f"仍为 generating 状态，缺少: {', '.join(missing)}"
                )

        # 修复人物
        for asset_id, model in self._models.items():
            if model.status != AssetStatus.GENERATING:
                continue

            if model.portrait_image and os.path.isfile(model.portrait_image):
                # 已有选定的半身近景照，直接确认
                model.status = AssetStatus.CONFIRMED
                recovered_count += 1
                logger.info(
                    f"[AssetManager] 人物 {asset_id} ({model.name}) "
                    f"generating → confirmed（portrait_image 已存在，自动恢复）"
                )
                continue

            # 磁盘扫描：look_options 为空但目录里有 look_*.png，自动填充
            if not model.look_options:
                import glob
                model_dir = os.path.join("assets", asset_id)
                look_files = sorted(glob.glob(os.path.join(model_dir, "look_*.png")))
                if look_files:
                    model.look_options = look_files
                    logger.info(
                        f"[AssetManager] 人物 {asset_id} ({model.name}) "
                        f"从磁盘恢复 {len(look_files)} 个方案图: {look_files}"
                    )

            if model.look_options:
                # 有方案图但没选 → pending，等用户在前端选择
                model.status = AssetStatus.PENDING
                recovered_count += 1
                logger.info(
                    f"[AssetManager] 人物 {asset_id} ({model.name}) "
                    f"generating → pending（{len(model.look_options)} 个方案图待选择）"
                )
            else:
                logger.warning(
                    f"[AssetManager] 人物 {asset_id} ({model.name}) "
                    f"仍为 generating 状态，无方案图，可能生成中途崩溃"
                )

        # 修复游戏
        for asset_id, game in self._games.items():
            if game.status != AssetStatus.GENERATING:
                continue

            screenshot_exists = game.screenshot_path and os.path.isfile(game.screenshot_path)
            video_exists = game.gameplay_video_path and os.path.isfile(game.gameplay_video_path)

            if screenshot_exists and video_exists:
                # 截图和录屏都在磁盘上 → 根据问卷状态决定恢复目标
                if game.questionnaire_status == QuestionnaireStatus.COMPLETED:
                    game.status = AssetStatus.CONFIRMED
                    target = "confirmed"
                else:
                    game.status = AssetStatus.PENDING
                    target = "pending"
                recovered_count += 1
                logger.info(
                    f"[AssetManager] 游戏 {asset_id} ({game.name}) "
                    f"generating -> {target}（截图+录屏文件已存在，自动恢复）"
                )
            else:
                missing = []
                if not screenshot_exists:
                    missing.append("screenshot_path")
                if not video_exists:
                    missing.append("gameplay_video_path")
                logger.warning(
                    f"[AssetManager] 游戏 {asset_id} ({game.name}) "
                    f"仍为 generating 状态，缺少: {', '.join(missing)}"
                )

        if recovered_count > 0:
            logger.info(f"[AssetManager] 启动恢复完成，共修复 {recovered_count} 个素材")
            # 修复后立即持久化
            self._persist()

    # ========== 持久化 ==========

    def _persist(self) -> None:
        """将当前内存数据同步写入持久层"""
        try:
            self._storage.save_all(self._items, self._models, self._games, self._counters)
        except Exception as e:
            logger.error(f"[AssetManager] 持久化失败: {e}")

    # ========== ID 生成 ==========

    def generate_id(self, asset_type: AssetType) -> str:
        """生成自增素材 ID"""
        self._counters[asset_type] += 1
        prefix = {
            AssetType.ITEM: "item",
            AssetType.GAME: "game",
            AssetType.MODEL: "model",
        }[asset_type]
        return f"{prefix}_{self._counters[asset_type]:03d}"

    # ========== 物品 ==========

    def save_item(self, asset: ItemAsset) -> None:
        """保存物品素材"""
        self._items[asset.id] = asset
        logger.info(f"[AssetManager] 物品已保存: {asset.id} ({asset.name})")
        self._persist()

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
            self._persist()
            return True
        return False

    # ========== 人物 ==========

    def save_model(self, asset: ModelAsset) -> None:
        """保存人物素材"""
        self._models[asset.id] = asset
        logger.info(f"[AssetManager] 人物已保存: {asset.id} ({asset.name})")
        self._persist()

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
            self._persist()
            return True
        return False

    def update_model_portrait(self, asset_id: str, portrait_image: str) -> bool:
        """更新人物的半身近景照（v10：一图多用）"""
        model = self._models.get(asset_id)
        if model:
            model.portrait_image = portrait_image
            logger.info(f"[AssetManager] 人物 {asset_id} 半身近景照已更新: {portrait_image}")
            self._persist()
            return True
        return False

    # ========== 游戏 ==========

    def save_game(self, asset: GameAsset) -> None:
        """保存游戏素材"""
        self._games[asset.id] = asset
        logger.info(f"[AssetManager] 游戏已保存: {asset.id} ({asset.name})")
        self._persist()

    def get_game(self, asset_id: str) -> Optional[GameAsset]:
        """获取游戏素材"""
        return self._games.get(asset_id)

    def list_games(self) -> list[GameAsset]:
        """列出所有游戏素材"""
        return list(self._games.values())

    def delete_game(self, asset_id: str) -> bool:
        """删除游戏素材"""
        if asset_id in self._games:
            del self._games[asset_id]
            logger.info(f"[AssetManager] 游戏已删除: {asset_id}")
            self._persist()
            return True
        return False

    # ========== 通用 ==========

    def get_asset(self, asset_id: str) -> Optional[AssetUnion]:
        """根据 ID 前缀自动判断类型并获取素材"""
        if asset_id.startswith("item_"):
            return self.get_item(asset_id)
        elif asset_id.startswith("game_"):
            return self.get_game(asset_id)
        elif asset_id.startswith("model_"):
            return self.get_model(asset_id)
        return None

    def get_stats(self) -> dict:
        """获取素材库统计"""
        return {
            "items": len(self._items),
            "games": len(self._games),
            "models": len(self._models),
            "total": len(self._items) + len(self._games) + len(self._models),
        }

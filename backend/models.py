"""
数据模型定义
所有请求/响应的 Pydantic 模型
v4 架构：4 Agent（ADA/DA/VA/VGA）
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


# ========== 枚举 ==========

class Platform(str, Enum):
    """目标平台"""
    DOUYIN = "douyin"           # 抖音 9:16
    XIAOHONGSHU = "xiaohongshu" # 小红书 9:16
    YOUTUBE = "youtube"         # YouTube 16:9


class Duration(str, Enum):
    """视频时长"""
    SHORT = "15s"   # 15 秒
    MEDIUM = "30s"  # 30 秒
    LONG = "60s"    # 60 秒


class JobStatus(str, Enum):
    """任务状态（v4：已移除 QA 环节）"""
    PENDING = "pending"             # 等待开始
    SCRIPT_GENERATING = "script"    # DA 正在生成脚本
    IMAGES_GENERATING = "images"    # VA 正在生成分镜图
    VIDEOS_GENERATING = "videos"    # VGA 正在生成视频片段
    STITCHING = "stitching"         # FFmpeg 拼接视频中
    COMPLETED = "completed"         # 完成
    FAILED = "failed"               # 失败


class AssetType(str, Enum):
    """素材类型"""
    ITEM = "item"       # 物品
    MODEL = "model"     # 人物
    SCENE = "scene"     # 场景


# ========== 素材模型 ==========

class QuestionnaireStatus(str, Enum):
    """问卷状态"""
    PENDING = "pending"           # 等待用户填写
    IN_PROGRESS = "in_progress"   # 用户正在填写
    COMPLETED = "completed"       # 已完成


class QuestionnaireField(BaseModel):
    """问卷中的一个字段"""
    key: str = Field(..., description="字段标识，如 selling_point")
    label: str = Field(..., description="显示标签，如 核心卖点")
    value: str = Field("", description="当前值（AI 预填或用户填写）")
    priority: str = Field("P1", description="优先级: P0/P1/P2")
    source: str = Field("ai", description="来源: ai=AI预填, user=待用户填写")
    required: bool = Field(True, description="是否必填")


class ItemAsset(BaseModel):
    """物品素材档案（v5：支持智能问卷 + P0/P1/P2 卖点）"""
    id: str = Field(..., description="素材 ID，如 item_001")
    name: str = Field(..., description="物品名称")
    category: str = Field(..., description="物品类别，如面部护肤")
    size_category: str = Field("small", description="尺寸分类: small 允许, large 拒绝")

    # v5: 动态产品信息（ADA 问卷收集，字段不固定）
    product_info: dict = Field(default_factory=dict, description="动态产品信息，key 由 ADA 按品类决定")

    # v5: 卖点优先级
    selling_points: dict = Field(
        default_factory=lambda: {"P0": [], "P1": [], "P2": []},
        description="按优先级分组的卖点列表",
    )

    # v5: 问卷状态
    questionnaire_status: QuestionnaireStatus = Field(
        QuestionnaireStatus.PENDING, description="问卷收集进度"
    )
    questionnaire_fields: list[QuestionnaireField] = Field(
        default_factory=list, description="问卷字段列表（analyze 返回，confirm 时回收）"
    )

    # 兼容旧字段
    selling_point: str = Field("", description="核心卖点（兼容旧版，取 P0 第一条）")
    usage: str = Field("", description="使用方式描述")

    original_images: list[str] = Field(default_factory=list, description="用户上传的原始图片路径")
    instruction_image: Optional[str] = Field(None, description="ADA 生成的产品说明图路径")
    full_description: str = Field("", description="ADA 生成的完整产品描述")


class ModelAsset(BaseModel):
    """人物素材档案"""
    id: str = Field(..., description="素材 ID，如 model_001")
    name: str = Field(..., description="人物名称/标签")
    appearance: str = Field(..., description="外貌描述")
    personality: str = Field("", description="气质/性格描述")
    outfits: str = Field("", description="穿搭描述")
    reference_images: list[str] = Field(default_factory=list, description="用户上传的参考图")
    selected_look: Optional[str] = Field(None, description="用户选中的造型图路径")
    full_description: str = Field("", description="ADA 生成的完整人设描述")


class SceneAsset(BaseModel):
    """场景素材档案"""
    id: str = Field(..., description="素材 ID，如 scene_001")
    name: str = Field(..., description="场景名称")
    environment: str = Field(..., description="环境描述")
    lighting: str = Field("", description="光线描述")
    mood: str = Field("", description="氛围描述")
    reference_images: list[str] = Field(default_factory=list, description="用户上传的参考图")
    selected_scene: Optional[str] = Field(None, description="用户选中的场景图路径")
    full_description: str = Field("", description="ADA 生成的完整场景描述")


# ========== 请求模型 ==========

class VideoGenerateRequest(BaseModel):
    """视频生成请求（v4：基于素材库选择）"""
    item_id: str = Field(..., description="选中的物品素材 ID")
    model_id: str = Field(..., description="选中的人物素材 ID")
    scene_id: str = Field(..., description="选中的场景素材 ID")
    platform: Platform = Field(..., description="目标平台")
    duration: Duration = Field(..., description="视频时长")
    extra_requirements: str = Field("", description="用户额外要求（可选）")


class GenerateRequest(BaseModel):
    """用户提交的生成请求（旧版兼容，后续切换到 VideoGenerateRequest）"""
    product_type: str = Field(..., description="产品类型，如：洗面奶、面膜、手机App")
    product_usage: str = Field(..., description="产品使用方式描述")
    platform: Platform = Field(..., description="目标平台")
    duration: Duration = Field(..., description="视频时长")
    selling_point: str = Field(..., description="核心卖点，一句话")


# ========== 脚本相关模型 ==========

class ScriptSegment(BaseModel):
    """脚本中的一个分段"""
    segment_id: int = Field(..., description="分段序号，从 1 开始")
    narration: str = Field(..., description="旁白台词")
    action_description: str = Field(..., description="动作描述")
    frame_start_prompt: str = Field(..., description="首帧图片生成提示词")
    frame_end_prompt: str = Field(..., description="尾帧图片生成提示词")
    needs_product: bool = Field(False, description="该分段是否需要植入产品")
    veo_description: str = Field(..., description="Veo 视频生成描述词（动作 + 台词）")


class StyleGuide(BaseModel):
    """风格指南，确保画面一致性"""
    person_description: str = Field(..., description="人物外貌统一描述")
    scene_description: str = Field(..., description="场景统一描述")
    visual_style: str = Field(..., description="整体视觉风格")
    lighting: str = Field(..., description="光线描述")


class SelfCheck(BaseModel):
    """DA 脚本自检评分（D6 决策）"""
    person_match: int = Field(..., ge=1, le=5, description="人物匹配度 1-5")
    product_accuracy: int = Field(..., ge=1, le=5, description="产品准确度 1-5")
    scene_consistency: int = Field(..., ge=1, le=5, description="场景一致性 1-5")
    overall_quality: int = Field(..., ge=1, le=5, description="整体质量 1-5")
    issues: str = Field("", description="发现的问题（为空表示无问题）")


class ScriptOutput(BaseModel):
    """DA 输出的完整脚本（v5：含声音锚定 + 自检评分）"""
    title: str = Field(..., description="视频标题")
    voice_anchor: str = Field("", description="声音锚定描述（英文），用于所有视频片段保持声音一致")
    style_guide: StyleGuide
    segments: list[ScriptSegment]
    self_check: SelfCheck = Field(..., description="DA 自检评分")


# ========== 响应模型 ==========

class JobResponse(BaseModel):
    """任务创建响应"""
    job_id: str
    status: JobStatus = JobStatus.PENDING
    message: str = "任务已创建"


class ProgressResponse(BaseModel):
    """任务进度响应"""
    job_id: str
    status: JobStatus
    progress: float = Field(0.0, ge=0.0, le=1.0, description="进度百分比 0~1")
    message: str = ""
    script: Optional[ScriptOutput] = None
    storyboard_urls: list[str] = Field(default_factory=list, description="分镜图 URL 列表")
    segment_urls: list[str] = Field(default_factory=list, description="视频片段 URL 列表")
    final_video_url: Optional[str] = None

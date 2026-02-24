"""
数据模型定义
所有请求/响应的 Pydantic 模型
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
    """任务状态"""
    PENDING = "pending"             # 等待开始
    SCRIPT_GENERATING = "script"    # 正在生成脚本
    IMAGES_GENERATING = "images"    # 正在生成分镜图
    VIDEOS_GENERATING = "videos"    # 正在生成视频片段
    QA_REVIEWING = "qa"             # 质控审核中
    STITCHING = "stitching"         # 拼接视频中
    COMPLETED = "completed"         # 完成
    FAILED = "failed"               # 失败


# ========== 请求模型 ==========

class GenerateRequest(BaseModel):
    """用户提交的生成请求（6 项输入）"""
    product_type: str = Field(..., description="产品类型，如：洗面奶、面膜、手机App")
    product_usage: str = Field(..., description="产品使用方式描述")
    platform: Platform = Field(..., description="目标平台")
    duration: Duration = Field(..., description="视频时长")
    selling_point: str = Field(..., description="核心卖点，一句话")
    # 产品参考图通过文件上传单独处理，不在 JSON body 中


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


class ScriptOutput(BaseModel):
    """TA 输出的完整脚本"""
    title: str = Field(..., description="视频标题")
    style_guide: StyleGuide
    segments: list[ScriptSegment]


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

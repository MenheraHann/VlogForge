"""
DA Agent 系统提示词
定义 DA（创意总监）的脚本生成角色、任务、输出格式和约束
v4 架构：DA 直接生成脚本（原 TA 功能合入），含 self_check 自检
"""

DA_SCRIPT_SYSTEM_PROMPT = """你是 VlogForge 的创意总监（DA），负责为带货短视频撰写 vlog 风格的脚本。

## 你的任务

根据提供的素材信息（物品、人物、场景）和用户要求，生成一份完整的 vlog 带货视频脚本，包括：
1. 视频标题（吸引点击，口语化）
2. 风格指南（人物、场景、视觉风格、光线的统一描述）
3. 分段脚本（每段包含旁白、动作、首尾帧提示词、Veo 描述词）
4. 自检评分（对自己的输出质量打分）

## 核心规则

### 帧链条连贯性（最重要）
- 分段 N 的 frame_end_prompt **必须和** 分段 N+1 的 frame_start_prompt **完全相同**
- 这是因为相邻视频片段共享一张图片：上一段的结尾帧 = 下一段的开头帧
- 第 1 段的 frame_start_prompt 是整个视频的第一帧
- 最后一段的 frame_end_prompt 是整个视频的最后一帧

### 帧提示词要求
- 每个帧提示词都是独立的图片生成提示词，必须自包含（不能写"同上"或"同前"）
- 包含：人物外貌、穿着、表情、动作、场景、光线、画面构图
- 风格指南中的人物/场景描述必须融入每个帧提示词中，保证画面一致
- 标记 needs_product=true 的分段，帧提示词中要自然融入产品描述

### Veo 描述词要求
- veo_description 用于 Veo 视频生成，描述从首帧到尾帧之间的动态过程
- 包含：镜头运动、人物动作、表情变化、对话内容
- 旁白内容要写进 veo_description，因为 Veo 会根据它生成语音

### 内容风格
- vlog 真人出镜风格，像是用手机自拍的感觉
- 旁白口语化、有网感，像在和闺蜜聊天
- 开场要抓人（提问/痛点/共鸣），结尾要有行动号召
- 产品植入自然不突兀，像真实使用记录

### 自检评分（self_check）
- person_match：脚本中人物描述与素材信息的匹配程度（1-5）
- product_accuracy：产品信息、使用方式、卖点的表达准确度（1-5）
- scene_consistency：场景描述在各分段中的一致性（1-5）
- overall_quality：整体脚本质量（创意、自然度、完整性）（1-5）
- issues：如果有任何问题，写在这里；没有问题留空字符串

## 输出格式

严格按照 JSON Schema 输出，不要添加任何额外文字。
"""


def build_da_script_prompt(
    item_name: str,
    item_usage: str,
    item_selling_point: str,
    item_description: str,
    model_appearance: str,
    model_personality: str,
    model_outfits: str,
    scene_environment: str,
    scene_lighting: str,
    scene_mood: str,
    platform: str,
    duration: str,
    segment_count: int,
    aspect_ratio: str,
    extra_requirements: str = "",
) -> str:
    """构建 DA 脚本生成的用户提示词（基于素材档案，v4 标准路径）"""

    platform_names = {
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "youtube": "YouTube",
    }
    platform_name = platform_names.get(platform, platform)

    extra_block = ""
    if extra_requirements:
        extra_block = f"\n【用户额外要求】\n{extra_requirements}\n"

    return f"""请根据以下素材信息生成 vlog 带货脚本：

【物品素材】
- 名称：{item_name}
- 使用方式：{item_usage}
- 核心卖点：{item_selling_point}
- 详细描述：{item_description}

【人物素材】
- 外貌：{model_appearance}
- 气质：{model_personality}
- 穿搭：{model_outfits}

【场景素材】
- 环境：{scene_environment}
- 光线：{scene_lighting}
- 氛围：{scene_mood}

【视频参数】
- 目标平台：{platform_name}
- 画面比例：{aspect_ratio}
- 视频时长：{duration}
- 分段数量：{segment_count} 段（请严格生成 {segment_count} 个 segment）
{extra_block}
【提醒】
- segment_id 从 1 到 {segment_count}
- 至少有 2 个分段标记 needs_product=true（开场展示 + 产品使用场景）
- 帧链条：分段 N 的 frame_end_prompt 必须和分段 N+1 的 frame_start_prompt 完全一致
- 人物描述必须严格匹配人物素材的外貌和穿搭
- 场景描述必须严格匹配场景素材的环境和光线
- 最后填写 self_check 自检评分，诚实评估自己的输出质量
"""


def build_da_script_prompt_legacy(
    product_type: str,
    product_usage: str,
    platform: str,
    duration: str,
    selling_point: str,
    segment_count: int,
    aspect_ratio: str,
) -> str:
    """构建 DA 脚本生成的用户提示词（兼容旧版，直接接收产品信息）"""

    platform_names = {
        "douyin": "抖音",
        "xiaohongshu": "小红书",
        "youtube": "YouTube",
    }
    platform_name = platform_names.get(platform, platform)

    return f"""请为以下产品生成 vlog 带货脚本：

【产品信息】
- 产品类型：{product_type}
- 使用方式：{product_usage}
- 核心卖点：{selling_point}

【视频参数】
- 目标平台：{platform_name}
- 画面比例：{aspect_ratio}
- 视频时长：{duration}
- 分段数量：{segment_count} 段（请严格生成 {segment_count} 个 segment）

【提醒】
- segment_id 从 1 到 {segment_count}
- 至少有 2 个分段标记 needs_product=true（开场展示 + 产品使用场景）
- 帧链条：分段 N 的 frame_end_prompt 必须和分段 N+1 的 frame_start_prompt 完全一致
- 最后填写 self_check 自检评分，诚实评估自己的输出质量
"""

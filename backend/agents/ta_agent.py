"""
TA Agent - 脚本策划（Text Agent）
负责：根据用户输入生成 vlog 脚本 + 分镜提示词 + 风格指南
输出结构化 JSON，供 VA 和 VGA 使用

实现方案：单次调用 + JSON Schema 模式（方案 A）
"""

import json
import logging

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY
from backend.models import ScriptOutput, ScriptSegment, StyleGuide
from backend.prompts.ta_system import TA_SYSTEM_PROMPT, build_ta_user_prompt

logger = logging.getLogger(__name__)

# TA 使用的模型（文本生成，不需要图片能力）
TA_MODEL = "gemini-2.5-flash"


def _get_client() -> genai.Client:
    """获取 Gemini 客户端（懒加载，避免启动时无 Key 报错）"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未配置，请在 .env 中设置")
    return genai.Client(api_key=GEMINI_API_KEY)


def _build_response_schema() -> dict:
    """
    构建 ScriptOutput 的 JSON Schema，供 Gemini JSON 模式使用。
    手动构建而非用 Pydantic 的 model_json_schema()，
    因为 Gemini 的 response_schema 对格式有特定要求。
    """
    return {
        "type": "OBJECT",
        "properties": {
            "title": {
                "type": "STRING",
                "description": "视频标题，吸引点击，口语化",
            },
            "style_guide": {
                "type": "OBJECT",
                "properties": {
                    "person_description": {
                        "type": "STRING",
                        "description": "人物外貌统一描述（年龄、性别、发型、穿着）",
                    },
                    "scene_description": {
                        "type": "STRING",
                        "description": "场景统一描述（地点、环境、背景元素）",
                    },
                    "visual_style": {
                        "type": "STRING",
                        "description": "整体视觉风格（写实/清新/复古等 + 色调）",
                    },
                    "lighting": {
                        "type": "STRING",
                        "description": "光线描述（自然光/暖光/柔光等）",
                    },
                },
                "required": [
                    "person_description",
                    "scene_description",
                    "visual_style",
                    "lighting",
                ],
            },
            "segments": {
                "type": "ARRAY",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "segment_id": {
                            "type": "INTEGER",
                            "description": "分段序号，从 1 开始",
                        },
                        "narration": {
                            "type": "STRING",
                            "description": "旁白台词",
                        },
                        "action_description": {
                            "type": "STRING",
                            "description": "动作描述",
                        },
                        "frame_start_prompt": {
                            "type": "STRING",
                            "description": "首帧图片生成提示词（自包含，包含人物/场景/动作/光线）",
                        },
                        "frame_end_prompt": {
                            "type": "STRING",
                            "description": "尾帧图片生成提示词（自包含，下一段的首帧必须与此完全相同）",
                        },
                        "needs_product": {
                            "type": "BOOLEAN",
                            "description": "该分段是否需要植入产品",
                        },
                        "veo_description": {
                            "type": "STRING",
                            "description": "Veo 视频生成描述词（动作过程 + 台词 + 镜头运动）",
                        },
                    },
                    "required": [
                        "segment_id",
                        "narration",
                        "action_description",
                        "frame_start_prompt",
                        "frame_end_prompt",
                        "needs_product",
                        "veo_description",
                    ],
                },
            },
        },
        "required": ["title", "style_guide", "segments"],
    }


def _validate_frame_chain(script: ScriptOutput) -> list[str]:
    """
    验证帧链条连贯性：分段 N 的 frame_end_prompt 必须等于分段 N+1 的 frame_start_prompt。
    返回问题列表，空列表表示全部通过。
    """
    issues = []
    for i in range(len(script.segments) - 1):
        current = script.segments[i]
        next_seg = script.segments[i + 1]
        if current.frame_end_prompt != next_seg.frame_start_prompt:
            issues.append(
                f"帧链断裂：分段 {current.segment_id} 尾帧 != 分段 {next_seg.segment_id} 首帧"
            )
    return issues


async def generate_script(
    product_type: str,
    product_usage: str,
    platform: str,
    duration: str,
    selling_point: str,
    segment_count: int,
    aspect_ratio: str,
    max_retries: int = 2,
) -> ScriptOutput:
    """
    调用 Gemini 生成 vlog 带货脚本。

    参数:
        product_type: 产品类型
        product_usage: 产品使用方式
        platform: 目标平台 (douyin/xiaohongshu/youtube)
        duration: 视频时长 (15s/30s/60s)
        selling_point: 核心卖点
        segment_count: 分段数量
        aspect_ratio: 画面比例 (9:16/16:9)
        max_retries: 最大重试次数

    返回:
        ScriptOutput 结构化脚本
    """
    client = _get_client()

    # 构建用户提示词
    user_prompt = build_ta_user_prompt(
        product_type=product_type,
        product_usage=product_usage,
        platform=platform,
        duration=duration,
        selling_point=selling_point,
        segment_count=segment_count,
        aspect_ratio=aspect_ratio,
    )

    logger.info(f"[TA] 开始生成脚本: 产品={product_type}, 分段数={segment_count}")

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            # 调用 Gemini，使用 JSON Schema 模式
            response = await client.aio.models.generate_content(
                model=TA_MODEL,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=TA_SYSTEM_PROMPT,
                    temperature=0.8,
                    response_mime_type="application/json",
                    response_schema=_build_response_schema(),
                ),
            )

            # 解析 JSON 响应
            raw_text = response.text
            if not raw_text:
                raise ValueError("Gemini 返回了空响应")

            logger.info(f"[TA] 第 {attempt} 次调用成功，解析 JSON 中...")

            raw_data = json.loads(raw_text)

            # 转为 Pydantic 模型（自动做类型校验）
            script = ScriptOutput(**raw_data)

            # 验证分段数量
            if len(script.segments) != segment_count:
                logger.warning(
                    f"[TA] 分段数不匹配: 期望 {segment_count}, 实际 {len(script.segments)}"
                )

            # 验证帧链条
            chain_issues = _validate_frame_chain(script)
            if chain_issues:
                for issue in chain_issues:
                    logger.warning(f"[TA] {issue}")
                # 帧链不完美不阻断流程，后续 VA 生成时用实际帧提示词即可
                logger.info("[TA] 帧链有断裂，但不阻断流程（后续 VA 会逐帧生成）")

            logger.info(
                f"[TA] 脚本生成完成: 标题=「{script.title}」, "
                f"分段数={len(script.segments)}, "
                f"需要产品的分段={sum(1 for s in script.segments if s.needs_product)}"
            )

            return script

        except json.JSONDecodeError as e:
            last_error = e
            logger.error(f"[TA] 第 {attempt} 次调用: JSON 解析失败 - {e}")
        except Exception as e:
            last_error = e
            logger.error(f"[TA] 第 {attempt} 次调用失败: {type(e).__name__} - {e}")

    # 全部重试失败
    raise RuntimeError(
        f"[TA] 脚本生成失败（已重试 {max_retries} 次）: {last_error}"
    )

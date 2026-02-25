"""
DA Agent - 创意总监（Director Agent）
负责：脚本生成 + 自检校验 + 编排 VA/VGA/FFmpeg
v4 架构：DA 直接生成脚本（原 TA 合入），QA 已移除

当前实现：脚本生成 + self_check 自检，VA/VGA/FFmpeg 为占位
"""

import json
import logging
import traceback

from google import genai
from google.genai import types

from backend.config import GEMINI_API_KEY, TEXT_MODEL, SELF_CHECK_THRESHOLD
from backend.models import JobStatus, ScriptOutput, SelfCheck
from backend.services.job_manager import JobManager
from backend.prompts.da_prompts import (
    DA_SCRIPT_SYSTEM_PROMPT,
    build_da_script_prompt,
    build_da_script_prompt_legacy,
)

logger = logging.getLogger(__name__)

# DA 使用的模型（从 config 统一管理）
DA_MODEL = TEXT_MODEL


def _get_client() -> genai.Client:
    """获取 Gemini 客户端（懒加载，避免启动时无 Key 报错）"""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 未配置，请在 .env 中设置")
    return genai.Client(api_key=GEMINI_API_KEY)


def _build_response_schema() -> dict:
    """
    构建 ScriptOutput + SelfCheck 的 JSON Schema，供 Gemini JSON 模式使用。
    手动构建，因为 Gemini 的 response_schema 对格式有特定要求。
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
            "self_check": {
                "type": "OBJECT",
                "description": "DA 自检评分",
                "properties": {
                    "person_match": {
                        "type": "INTEGER",
                        "description": "人物匹配度 1-5",
                    },
                    "product_accuracy": {
                        "type": "INTEGER",
                        "description": "产品准确度 1-5",
                    },
                    "scene_consistency": {
                        "type": "INTEGER",
                        "description": "场景一致性 1-5",
                    },
                    "overall_quality": {
                        "type": "INTEGER",
                        "description": "整体质量 1-5",
                    },
                    "issues": {
                        "type": "STRING",
                        "description": "发现的问题，没有问题留空字符串",
                    },
                },
                "required": [
                    "person_match",
                    "product_accuracy",
                    "scene_consistency",
                    "overall_quality",
                    "issues",
                ],
            },
        },
        "required": ["title", "style_guide", "segments", "self_check"],
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


def _check_self_check(self_check: SelfCheck) -> tuple[bool, str]:
    """
    检查 self_check 分数是否达标。
    返回 (是否通过, 反馈信息)。
    """
    scores = {
        "person_match（人物匹配度）": self_check.person_match,
        "product_accuracy（产品准确度）": self_check.product_accuracy,
        "scene_consistency（场景一致性）": self_check.scene_consistency,
        "overall_quality（整体质量）": self_check.overall_quality,
    }

    low_items = [k for k, v in scores.items() if v < SELF_CHECK_THRESHOLD]

    if not low_items:
        return True, ""

    feedback_parts = []
    for item in low_items:
        feedback_parts.append(f"- {item} 评分为 {scores[item]}，低于阈值 {SELF_CHECK_THRESHOLD}")

    if self_check.issues:
        feedback_parts.append(f"- 自检发现的问题：{self_check.issues}")

    feedback = "以下指标不达标，请针对性改进：\n" + "\n".join(feedback_parts)
    return False, feedback


async def generate_script(
    user_prompt: str,
    segment_count: int,
    max_retries: int = 2,
    retry_feedback: str = "",
) -> ScriptOutput:
    """
    调用 Gemini 生成 vlog 带货脚本（DA 直接生成，原 TA 逻辑合入）。

    参数:
        user_prompt: 完整的用户提示词（由 build_da_script_prompt 或 legacy 版本构建）
        segment_count: 期望的分段数量
        max_retries: JSON 解析失败时的最大重试次数
        retry_feedback: self_check 不达标时的重跑反馈
    """
    client = _get_client()

    # 如果有重跑反馈，附加到用户提示词
    prompt = user_prompt
    if retry_feedback:
        prompt += f"\n\n【重跑反馈】\n{retry_feedback}\n请针对以上问题改进脚本。"

    logger.info(f"[DA] 开始生成脚本: 分段数={segment_count}")

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=DA_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=DA_SCRIPT_SYSTEM_PROMPT,
                    temperature=0.8,
                    response_mime_type="application/json",
                    response_schema=_build_response_schema(),
                ),
            )

            raw_text = response.text
            if not raw_text:
                raise ValueError("Gemini 返回了空响应")

            logger.info(f"[DA] 第 {attempt} 次调用成功，解析 JSON 中...")

            raw_data = json.loads(raw_text)
            script = ScriptOutput(**raw_data)

            # 验证分段数量
            if len(script.segments) != segment_count:
                logger.warning(
                    f"[DA] 分段数不匹配: 期望 {segment_count}, 实际 {len(script.segments)}"
                )

            # 验证帧链条
            chain_issues = _validate_frame_chain(script)
            if chain_issues:
                for issue in chain_issues:
                    logger.warning(f"[DA] {issue}")
                logger.info("[DA] 帧链有断裂，但不阻断流程（VA 会逐帧生成）")

            logger.info(
                f"[DA] 脚本生成完成: 标题=「{script.title}」, "
                f"分段数={len(script.segments)}, "
                f"自检={script.self_check.overall_quality}/5"
            )

            return script

        except json.JSONDecodeError as e:
            last_error = e
            logger.error(f"[DA] 第 {attempt} 次调用: JSON 解析失败 - {e}")
        except Exception as e:
            last_error = e
            logger.error(f"[DA] 第 {attempt} 次调用失败: {type(e).__name__} - {e}")

    raise RuntimeError(
        f"[DA] 脚本生成失败（已重试 {max_retries} 次）: {last_error}"
    )


async def run_pipeline(job_id: str, job_manager: JobManager) -> None:
    """
    执行完整的视频生成流水线。
    由 main.py 在后台异步调用，通过 job_manager 更新进度。

    流水线：DA(脚本+自检) → VA(链式图生图) → VGA(首尾帧视频) → FFmpeg(拼接)
    """
    job = job_manager.get_job(job_id)
    if not job:
        logger.error(f"[DA][Job {job_id}] 任务不存在，无法启动流水线")
        return

    try:
        # ========== 阶段 1：DA 生成脚本 ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.05,
            message="DA 正在生成脚本...",
        )

        # 构建用户提示词（根据任务模式选择）
        if job.get("mode") == "v2_assets":
            # v2 模式：基于素材档案
            item = job["item"]
            model = job["model"]
            scene = job["scene"]
            user_prompt = build_da_script_prompt(
                item_name=item["name"],
                item_usage=item["usage"],
                item_selling_point=item["selling_point"],
                item_description=item["full_description"],
                model_appearance=model["appearance"],
                model_personality=model["personality"],
                model_outfits=model["outfits"],
                scene_environment=scene["environment"],
                scene_lighting=scene["lighting"],
                scene_mood=scene["mood"],
                platform=job["platform"],
                duration=job["duration"],
                segment_count=job["segment_count"],
                aspect_ratio=job["aspect_ratio"],
                extra_requirements=job.get("extra_requirements", ""),
            )
        else:
            # 旧版模式：直接传产品信息
            user_prompt = build_da_script_prompt_legacy(
                product_type=job["product_type"],
                product_usage=job["product_usage"],
                platform=job["platform"],
                duration=job["duration"],
                selling_point=job["selling_point"],
                segment_count=job["segment_count"],
                aspect_ratio=job["aspect_ratio"],
            )

        script = await generate_script(
            user_prompt=user_prompt,
            segment_count=job["segment_count"],
        )

        # ---- self_check 校验（D6 决策）----
        passed, feedback = _check_self_check(script.self_check)
        if not passed:
            logger.warning(f"[DA][Job {job_id}] 自检不达标，带反馈重跑一次")
            job_manager.update_job(
                job_id,
                progress=0.08,
                message="脚本自检不达标，正在改进...",
            )
            script = await generate_script(
                user_prompt=user_prompt,
                segment_count=job["segment_count"],
                retry_feedback=feedback,
            )
            logger.info(
                f"[DA][Job {job_id}] 重跑完成，自检={script.self_check.overall_quality}/5"
            )

        # 保存脚本到 job
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.15,
            message=f"脚本生成完成：「{script.title}」，共 {len(script.segments)} 段",
            script=script,
        )
        logger.info(f"[DA][Job {job_id}] 脚本完成：「{script.title}」")

        # ========== 阶段 2：VA 链式图生图（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.IMAGES_GENERATING,
            progress=0.20,
            message="分镜图生成待实现（VA Agent — 链式图生图）...",
        )
        logger.info(f"[DA][Job {job_id}] VA 占位 — 链式图生图待实现")

        # TODO: 接入 VA Agent
        # storyboard_urls = await va_agent.generate_storyboard(script, job)
        # job_manager.update_job(job_id, storyboard_urls=storyboard_urls, ...)

        # ========== 阶段 3：VGA 生成视频片段（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.VIDEOS_GENERATING,
            progress=0.40,
            message="视频片段生成待实现（VGA Agent — 首尾帧视频）...",
        )
        logger.info(f"[DA][Job {job_id}] VGA 占位 — 首尾帧视频待实现")

        # TODO: 接入 VGA Agent
        # segment_urls = await vga_agent.generate_segments(storyboard_urls, script, job)
        # job_manager.update_job(job_id, segment_urls=segment_urls, ...)

        # ========== 阶段 4：FFmpeg 拼接（占位） ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.STITCHING,
            progress=0.85,
            message="视频拼接待实现（FFmpeg）...",
        )
        logger.info(f"[DA][Job {job_id}] FFmpeg 占位 — 视频拼接待实现")

        # TODO: 接入 FFmpeg
        # final_path = await ffmpeg_tools.stitch(segment_urls, job)
        # job_manager.update_job(job_id, final_video=final_path, ...)

        # ========== 标记完成 ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            message="脚本生成完成（VA/VGA/FFmpeg 待实现）",
        )
        logger.info(f"[DA][Job {job_id}] 流水线完成")

    except Exception as e:
        logger.error(f"[DA][Job {job_id}] 流水线失败: {e}\n{traceback.format_exc()}")
        job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0.0,
            message=f"生成失败：{str(e)}",
        )

"""
DA Agent - Creative Director (Director Agent)
Responsibilities: Script generation + self-check validation + orchestrating VA/VGA/FFmpeg
v6 architecture: DA directly generates scripts, VGA start/end frame parallel generation + smart cropping
v14: Added cancel signal checking + on_job_finished callback

Pipeline: DA(script+self-check) -> VA(chained img2img) -> VGA(start/end frame parallel+smart crop) -> FFmpeg(stitching)
"""

import asyncio
import json
import os
import re
import logging
import traceback
from typing import Optional

from google.genai import types

from backend.config import get_genai_client, TEXT_MODEL, SELF_CHECK_THRESHOLD, ARTIFACTS_DIR
from backend.models import JobStatus, ScriptOutput, SelfCheck
from backend.services.job_manager import JobManager
from backend.agents import va_agent, vga_agent
from backend.tools import ffmpeg_tools
from backend.prompts.da_prompts import (
    DA_SCRIPT_SYSTEM_PROMPT,
    build_da_script_prompt,
    build_da_script_prompt_legacy,
)
from backend.tools.image_gen import SAFETY_FILTER_ERROR_TAG
from backend.utils.age_guard import enforce_minimum_age

logger = logging.getLogger(__name__)

# DA model (managed centrally via config)
DA_MODEL = TEXT_MODEL


def _get_client():
    """Get Gemini client (us-central1 for text generation)"""
    return get_genai_client(location="us-central1")


def _build_response_schema() -> dict:
    """
    Build the JSON Schema for ScriptOutput + SelfCheck, used by Gemini's JSON mode.
    Manually constructed because Gemini's response_schema has specific format requirements.
    """
    return {
        "type": "OBJECT",
        "properties": {
            "title": {
                "type": "STRING",
                "description": "Video title (English only), click-worthy, conversational tone",
            },
            "voice_anchor": {
                "type": "STRING",
                "description": "Voice anchor description (entirely in English; spoken language must be English), detailed voice characteristics: gender, age, language, tone, speaking pace, speaking style. Used to maintain consistent voice across all video segments.",
            },
            "style_guide": {
                "type": "OBJECT",
                "properties": {
                    "person_description": {
                        "type": "STRING",
                        "description": "Unified model/talent appearance description (age, gender, hairstyle, outfit)",
                    },
                    "scene_context": {
                        "type": "STRING",
                        "description": "Unified scene description (based on scene_context from model/talent assets, including location, environment, background elements)",
                    },
                    "visual_style": {
                        "type": "STRING",
                        "description": "Overall visual style (realistic/fresh/vintage etc. + color palette)",
                    },
                    "lighting": {
                        "type": "STRING",
                        "description": "Lighting description (natural light/warm light/soft light etc.)",
                    },
                },
                "required": [
                    "person_description",
                    "scene_context",
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
                            "description": "Segment sequence number, starting from 1",
                        },
                        "narration": {
                            "type": "STRING",
                            "description": "Dialogue lines — MUST be written in English only (no Chinese/Japanese/Korean/etc.), regardless of the person's profile language.",
                        },
                        "action_description": {
                            "type": "STRING",
                            "description": "Action description",
                        },
                        "frame_start_prompt": {
                            "type": "STRING",
                            "description": "Start frame image generation prompt (self-contained, includes person/scene/action/lighting)",
                        },
                        "frame_end_prompt": {
                            "type": "STRING",
                            "description": "End frame image generation prompt (self-contained, next segment's start frame must be exactly identical to this)",
                        },
                        "needs_product": {
                            "type": "BOOLEAN",
                            "description": "Whether this segment needs product placement",
                        },
                        "veo_description": {
                            "type": "STRING",
                            "description": "Veo video generation description: written in English, with spoken dialogue portions also in English (wrapped in quotes). Include opening state, micro-actions, emotional direction, and anti-pattern negatives.",
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
                "description": "DA self-check score",
                "properties": {
                    "person_match": {
                        "type": "INTEGER",
                        "description": "Person match score 1-5",
                    },
                    "product_accuracy": {
                        "type": "INTEGER",
                        "description": "Product accuracy score 1-5",
                    },
                    "scene_context_match": {
                        "type": "INTEGER",
                        "description": "Scene consistency with model/talent asset scene info 1-5",
                    },
                    "overall_quality": {
                        "type": "INTEGER",
                        "description": "Overall quality score 1-5",
                    },
                    "issues": {
                        "type": "STRING",
                        "description": "Issues found; leave as empty string if no issues",
                    },
                },
                "required": [
                    "person_match",
                    "product_accuracy",
                    "scene_context_match",
                    "overall_quality",
                    "issues",
                ],
            },
        },
        "required": ["title", "voice_anchor", "style_guide", "segments", "self_check"],
    }


def _validate_frame_chain(script: ScriptOutput) -> list[str]:
    """
    Validate frame chain continuity: Segment N's frame_end_prompt must equal Segment N+1's frame_start_prompt.
    Also validate key frame uniqueness: N+1 key frames must have no duplicates.
    Returns a list of issues; an empty list means all checks passed.
    """
    issues = []
    # 1. Frame chain continuity
    for i in range(len(script.segments) - 1):
        current = script.segments[i]
        next_seg = script.segments[i + 1]
        if current.frame_end_prompt != next_seg.frame_start_prompt:
            issues.append(
                f"Frame chain break: Segment {current.segment_id} end frame != Segment {next_seg.segment_id} start frame"
            )

    # 2. Key frame uniqueness (first segment's start frame + each segment's end frame = N+1 frames)
    keyframes = [script.segments[0].frame_start_prompt]
    for seg in script.segments:
        keyframes.append(seg.frame_end_prompt)
    seen = {}
    for i, prompt in enumerate(keyframes):
        if prompt in seen:
            issues.append(
                f"Key frame duplicate: Frame {i + 1} has identical prompt to Frame {seen[prompt] + 1}"
            )
        else:
            seen[prompt] = i

    return issues


def _check_self_check(self_check: SelfCheck) -> tuple[bool, str]:
    """
    Check whether self_check scores meet the threshold.
    Returns (passed, feedback_message).
    """
    scores = {
        "person_match (person match)": self_check.person_match,
        "product_accuracy (product accuracy)": self_check.product_accuracy,
        "scene_context_match (scene consistency)": self_check.scene_context_match,
        "overall_quality (overall quality)": self_check.overall_quality,
    }

    low_items = [k for k, v in scores.items() if v < SELF_CHECK_THRESHOLD]

    if not low_items:
        return True, ""

    feedback_parts = []
    for item in low_items:
        feedback_parts.append(f"- {item} scored {scores[item]}, below threshold {SELF_CHECK_THRESHOLD}")

    if self_check.issues:
        feedback_parts.append(f"- Issues found in self-check: {self_check.issues}")

    feedback = "The following metrics are below threshold. Please improve accordingly:\n" + "\n".join(feedback_parts)
    return False, feedback


_CJK_CHAR_RE = re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")


def _validate_english_only(script: ScriptOutput) -> list[str]:
    """
    Ensure DA output uses English-only title + dialogue.
    Veo Chinese/Japanese/Korean speech quality is currently unreliable, so we retry if CJK characters are detected.
    """
    issues: list[str] = []

    if script.title and _CJK_CHAR_RE.search(script.title):
        issues.append("Title contains CJK characters (English-only required)")

    for seg in script.segments:
        if seg.narration and _CJK_CHAR_RE.search(seg.narration):
            issues.append(f"Segment {seg.segment_id} narration contains CJK characters (English-only required)")

    return issues


async def generate_script(
    user_prompt: str,
    segment_count: int,
    max_retries: int = 2,
    retry_feedback: str = "",
) -> ScriptOutput:
    """
    Call Gemini to generate a vlog product promotion script (DA direct generation, former TA logic merged in).

    Args:
        user_prompt: Complete user prompt (built by build_da_script_prompt or legacy version)
        segment_count: Expected number of segments
        max_retries: Max retry count on JSON parse failure
        retry_feedback: Feedback from self_check failure for re-generation
    """
    client = _get_client()

    # If retry feedback exists, append it to the user prompt
    prompt = user_prompt
    if retry_feedback:
        prompt += f"\n\n[Retry Feedback]\n{retry_feedback}\nPlease improve the script based on the issues above."

    logger.info(f"[DA] Starting script generation: segment_count={segment_count}")

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await asyncio.wait_for(
                client.aio.models.generate_content(
                    model=DA_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=DA_SCRIPT_SYSTEM_PROMPT,
                        temperature=0.55,
                        response_mime_type="application/json",
                        response_schema=_build_response_schema(),
                    ),
                ),
                timeout=120,
            )

            raw_text = response.text
            if not raw_text:
                raise ValueError("Gemini returned an empty response")

            logger.info(f"[DA] Attempt {attempt} succeeded, parsing JSON...")

            raw_data = json.loads(raw_text)
            script = ScriptOutput(**raw_data)

            # Validate segment count
            if len(script.segments) != segment_count:
                logger.warning(
                    f"[DA] Segment count mismatch: expected {segment_count}, got {len(script.segments)}"
                )

            # Validate frame chain + frame uniqueness (hard validation, retry on failure)
            chain_issues = _validate_frame_chain(script)
            if chain_issues:
                for issue in chain_issues:
                    logger.warning(f"[DA] {issue}")
                raise ValueError(
                    f"[DA] Script frame validation failed ({len(chain_issues)} issue(s)), triggering retry"
                )

            # Validate English-only output (hard validation, retry on failure)
            language_issues = _validate_english_only(script)
            if language_issues:
                for issue in language_issues:
                    logger.warning(f"[DA] {issue}")
                raise ValueError(
                    f"[DA] Script language validation failed ({len(language_issues)} issue(s)), triggering retry"
                )

            logger.info(
                f"[DA] Script generation complete: title=\"{script.title}\", "
                f"segments={len(script.segments)}, "
                f"self_check={script.self_check.overall_quality}/5"
            )

            return script

        except json.JSONDecodeError as e:
            last_error = e
            logger.error(f"[DA] Attempt {attempt}: JSON parse failed - {e}")
        except Exception as e:
            last_error = e
            logger.error(f"[DA] Attempt {attempt} failed: {type(e).__name__} - {e}")

    raise RuntimeError(
        f"[DA] Script generation failed (retried {max_retries} times): {last_error}"
    )


async def run_pipeline(
    job_id: str,
    job_manager: JobManager,
    cancel_event: asyncio.Event = None,
) -> None:
    """
    Execute the full video generation pipeline.
    Launched by JobManager, updates progress via job_manager.
    v14: Supports cancel_event signal checking between each major stage.

    Pipeline: DA(script+self-check) -> VA(chained img2img) -> VGA(start/end frame video) -> FFmpeg(stitching)

    Args:
        job_id: Job ID
        job_manager: JobManager instance
        cancel_event: Cancel signal (asyncio.Event), set() indicates user cancellation
    """
    job = job_manager.get_job(job_id)
    if not job:
        logger.error(f"[DA][Job {job_id}] Job not found, cannot start pipeline")
        return

    def _is_cancelled() -> bool:
        """Check whether the cancel signal has been set"""
        return cancel_event is not None and cancel_event.is_set()

    try:
        # ========== Stage 1: DA script generation ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.05,
            message="DA is generating the script...",
        )

        # Build user prompt (select based on job mode)
        if job.get("mode") == "v2_assets":
            # v2 mode: based on asset profiles (v10: scene sourced from model/talent assets)
            item = job["item"]
            model = job["model"]
            scene_context = model.get("scene_context", "")
            # v17: 从人物素材中获取 ADA 判定的语言（供 DA 生成 voice_anchor 时使用）
            model_language = model.get("language", "")
            # v18: 年龄保护 — 确保人物描述中的年龄不低于 18 岁
            safe_appearance = enforce_minimum_age(model["appearance"])
            user_prompt = build_da_script_prompt(
                item_name=item["name"],
                item_usage=item["usage"],
                item_selling_point=item["selling_point"],
                item_description=item["full_description"],
                model_appearance=safe_appearance,
                model_personality=model["personality"],
                model_outfits=model["outfits"],
                scene_context=scene_context,
                platform=job["platform"],
                duration=job["duration"],
                segment_count=job["segment_count"],
                aspect_ratio=job["aspect_ratio"],
                extra_requirements=job.get("extra_requirements", ""),
                model_language=model_language,
                usage_guide=item.get("usage_guide", ""),
            )
        else:
            # Legacy mode: pass product info directly
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

        # ---- self_check validation (D6 decision) ----
        passed, feedback = _check_self_check(script.self_check)
        if not passed:
            logger.warning(f"[DA][Job {job_id}] Self-check below threshold, re-running with feedback")
            job_manager.update_job(
                job_id,
                progress=0.08,
                message="Script self-check below threshold, improving...",
            )
            script = await generate_script(
                user_prompt=user_prompt,
                segment_count=job["segment_count"],
                retry_feedback=feedback,
            )
            logger.info(
                f"[DA][Job {job_id}] Re-run complete, self_check={script.self_check.overall_quality}/5"
            )

        # Save script to job
        job_manager.update_job(
            job_id,
            status=JobStatus.SCRIPT_GENERATING,
            progress=0.15,
            message=f"Script generated: \"{script.title}\", {len(script.segments)} segments",
            script=script,
        )
        logger.info(f"[DA][Job {job_id}] Script complete: \"{script.title}\"")

        # ---- Cancel checkpoint 1: After DA script generation ----
        if _is_cancelled():
            logger.info(f"[DA][Job {job_id}] Cancel signal detected after script generation")
            job_manager.update_job(
                job_id,
                status=JobStatus.CANCELLED,
                progress=0.0,
                message="User cancelled the job (after script generation)",
            )
            return

        # ========== Stage 2: VA fully parallel img2img ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.IMAGES_GENERATING,
            progress=0.20,
            message="VA is generating storyboard frames in parallel...",
        )
        logger.info(f"[DA][Job {job_id}] Starting VA fully parallel img2img")

        # Load asset images from job data (v10: person image changed to portrait_image, includes scene)
        person_image = _load_asset_image(job, "model", "portrait_image")
        product_image = _load_first_product_image(job)

        storyboard_dir = os.path.join(ARTIFACTS_DIR, job_id, "storyboard")

        # Save DA script to disk (for debugging frame prompts)
        script_path = os.path.join(ARTIFACTS_DIR, job_id, "script.json")
        os.makedirs(os.path.dirname(script_path), exist_ok=True)
        with open(script_path, "w", encoding="utf-8") as f:
            import json as _json
            _json.dump(script.model_dump(mode="json"), f, ensure_ascii=False, indent=2)

        # Incrementally push storyboard URLs to frontend
        storyboard_urls_so_far = []

        def _on_frame_done(frame_idx: int, total: int, frame_path: str):
            url = f"/artifacts/{job_id}/storyboard/{os.path.basename(frame_path)}"
            storyboard_urls_so_far.append(url)
            job_manager.update_job(
                job_id,
                progress=0.20 + 0.15 * len(storyboard_urls_so_far) / total,
                message=f"Generating storyboard ({len(storyboard_urls_so_far)}/{total})...",
                storyboard_urls=list(storyboard_urls_so_far),
            )

        storyboard_paths = await va_agent.generate_storyboard(
            script=script,
            output_dir=storyboard_dir,
            person_image=person_image,
            product_image=product_image,
            on_frame_done=_on_frame_done,
            aspect_ratio=job["aspect_ratio"],
        )

        # Convert to URLs for frontend display
        storyboard_urls = [
            f"/artifacts/{job_id}/storyboard/{os.path.basename(p)}"
            for p in storyboard_paths
        ]
        job_manager.update_job(
            job_id,
            progress=0.35,
            message=f"Storyboard complete: {len(storyboard_paths)} frames",
            storyboard_urls=storyboard_urls,
        )
        logger.info(f"[DA][Job {job_id}] VA complete: {len(storyboard_paths)} frames")

        # ---- Cancel checkpoint 2: After VA storyboard generation ----
        if _is_cancelled():
            logger.info(f"[DA][Job {job_id}] Cancel signal detected after storyboard generation")
            job_manager.update_job(
                job_id,
                status=JobStatus.CANCELLED,
                progress=0.0,
                message="User cancelled the job (after storyboard generation)",
            )
            return

        # ---- DA-side frame count validation: VA must return exactly segment_count + 1 frames ----
        expected_frame_count = job["segment_count"] + 1
        if len(storyboard_paths) != expected_frame_count:
            # 检查是否是安全过滤器导致的帧缺失（VA 日志中会记录安全过滤错误）
            missing_count = expected_frame_count - len(storyboard_paths)
            error_msg = (
                f"{SAFETY_FILTER_ERROR_TAG} 分镜图帧数不匹配: "
                f"期望 {expected_frame_count} 帧 ({job['segment_count']} 段 + 1), "
                f"实际 {len(storyboard_paths)} 帧, 缺失 {missing_count} 帧。"
                f"部分帧可能被安全过滤器拦截，请调整人物设定后重试。"
            )
            logger.error(f"[DA][Job {job_id}] {error_msg}")
            raise RuntimeError(error_msg)

        # ========== Stage 3: VGA start/end frame parallel video segment generation ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.VIDEOS_GENERATING,
            progress=0.40,
            message="VGA is generating video segments with start/end frames in parallel...",
        )
        logger.info(f"[DA][Job {job_id}] Starting VGA start/end frame parallel video generation")

        segment_dir = os.path.join(ARTIFACTS_DIR, job_id, "segments")

        # Incrementally push video segment URLs to frontend
        segment_urls_so_far = []

        def _on_segment_done(i: int, total: int, segment_path: str = ""):
            """Update progress and incrementally push URLs when each VGA segment completes"""
            if segment_path:
                url = f"/artifacts/{job_id}/segments/{os.path.basename(segment_path)}"
                segment_urls_so_far.append(url)
            job_manager.update_job(
                job_id,
                progress=0.40 + 0.40 * (i + 1) / total,
                message=f"Generating video segments ({i + 1}/{total})...",
                segment_urls=list(segment_urls_so_far),
            )

        segment_paths = await vga_agent.generate_segments(
            script=script,
            storyboard_paths=storyboard_paths,
            output_dir=segment_dir,
            aspect_ratio=job["aspect_ratio"],
            voice_anchor=script.voice_anchor,
            on_segment_done=_on_segment_done,
        )

        segment_urls = [
            f"/artifacts/{job_id}/segments/{os.path.basename(p)}"
            for p in segment_paths
        ]
        job_manager.update_job(
            job_id,
            progress=0.82,
            message=f"All video segments complete: {len(segment_paths)} segments",
            segment_urls=segment_urls,
        )
        logger.info(f"[DA][Job {job_id}] VGA complete: {len(segment_paths)} segments")

        # ---- Cancel checkpoint 3: After VGA video generation ----
        if _is_cancelled():
            logger.info(f"[DA][Job {job_id}] Cancel signal detected after video generation")
            job_manager.update_job(
                job_id,
                status=JobStatus.CANCELLED,
                progress=0.0,
                message="User cancelled the job (after video generation)",
            )
            return

        # ========== Stage 4: FFmpeg stitching ==========
        job_manager.update_job(
            job_id,
            status=JobStatus.STITCHING,
            progress=0.85,
            message="FFmpeg is stitching the final video...",
        )
        logger.info(f"[DA][Job {job_id}] Starting FFmpeg stitching")

        final_dir = os.path.join(ARTIFACTS_DIR, job_id)
        final_path = os.path.join(final_dir, "final.mp4")

        # Start/end frame mode: adjacent segments share one frame (prev end frame = next start frame), need to trim overlap
        await ffmpeg_tools.stitch_segments(
            segment_paths=segment_paths,
            output_path=final_path,
            trim_overlap_frames=True,
        )

        logger.info(f"[DA][Job {job_id}] FFmpeg stitching complete: {final_path}")

        # ========== Mark as completed ==========
        # final_video stores file path, get_progress will auto-generate the download URL
        job_manager.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=1.0,
            message=f"Video generation complete: \"{script.title}\"",
            final_video=final_path,
        )
        logger.info(f"[DA][Job {job_id}] Pipeline complete: {final_path}")

    except asyncio.CancelledError:
        # Triggered when asyncio.Task is cancel()'d
        logger.info(f"[DA][Job {job_id}] Pipeline interrupted by asyncio.CancelledError")
        job_manager.update_job(
            job_id,
            status=JobStatus.CANCELLED,
            progress=0.0,
            message="User cancelled the job",
        )

    except Exception as e:
        logger.error(f"[DA][Job {job_id}] Pipeline failed: {e}\n{traceback.format_exc()}")
        # 检测安全过滤器错误，设置特定错误类型 key 供前端 i18n 翻译
        err_str = str(e)
        if SAFETY_FILTER_ERROR_TAG in err_str:
            error_message = "safety_filtered"
        else:
            error_message = f"Generation failed: {err_str}"
        job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            progress=0.0,
            message=error_message,
        )

    finally:
        # v14: Regardless of success/failure/cancel, notify JobManager that job is finished to trigger next queued job
        job_manager.on_job_finished(job_id)
        logger.info(f"[DA][Job {job_id}] run_pipeline finally block executed")


def _load_asset_image(job: dict, asset_key: str, image_field: str) -> Optional[bytes]:
    """
    Load an asset image from job data.

    Args:
        job: Job data dict
        asset_key: Asset key (e.g., "model")
        image_field: Image field name (e.g., "portrait_image")

    Returns:
        Image bytes, or None if file does not exist
    """
    asset = job.get(asset_key)
    if not asset:
        return None

    path = asset.get(image_field)
    if not path or not os.path.exists(path):
        return None

    try:
        with open(path, "rb") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"[DA] Failed to load asset image ({asset_key}/{image_field}): {e}")
        return None


def _load_first_product_image(job: dict) -> Optional[bytes]:
    """
    Load product image for VA storyboard generation.
    Priority: three_view_image (ADA标准产品图) → thumbnail_image (ADA缩略图) → original_images[0] (用户原图)
    """
    item = job.get("item")
    if not item:
        return None

    # 优先使用 ADA 生成的三视图（标准产品图，供 DA/VA/VGA 使用）
    three_view = item.get("three_view_image")
    if three_view and os.path.exists(three_view):
        try:
            with open(three_view, "rb") as f:
                logger.info(f"[DA] 产品图加载: three_view_image = {three_view}")
                return f.read()
        except Exception:
            pass

    # 其次使用 ADA 生成的缩略图（白底电商风）
    thumbnail = item.get("thumbnail_image")
    if thumbnail and os.path.exists(thumbnail):
        try:
            with open(thumbnail, "rb") as f:
                logger.info(f"[DA] 产品图加载: thumbnail_image = {thumbnail}")
                return f.read()
        except Exception:
            pass

    # 最后退回到用户上传的原始图片
    originals = item.get("original_images", [])
    for path in originals:
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    logger.info(f"[DA] 产品图加载: original_images = {path}")
                    return f.read()
            except Exception:
                continue

    logger.warning("[DA] 未找到任何可用的产品图片")
    return None

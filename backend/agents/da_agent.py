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
    DA_GAME_SCRIPT_SYSTEM_PROMPT,
    build_da_script_prompt,
    build_da_script_prompt_legacy,
    build_da_game_script_prompt,
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
                "description": "Video title, click-worthy, conversational tone",
            },
            "voice_anchor": {
                "type": "STRING",
                "description": "Voice anchor description (entirely in English), detailed voice characteristics: gender, age, language, tone, speaking pace, speaking style. Used to maintain consistent voice across all video segments.",
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
                            "description": "Dialogue lines — MUST be written in the character's spoken language (determined by the 'language' field from person material). If language is English, write English dialogue; if Mandarin Chinese, write Chinese dialogue; if Japanese, write Japanese dialogue. Do NOT default to Chinese.",
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
                            "description": "Veo video generation description: written in English, with spoken dialogue portions in the character's language (wrapped in quotes). Include opening state, micro-actions, emotional direction, and anti-pattern negatives.",
                        },
                        "is_compositor_segment": {
                            "type": "BOOLEAN",
                            "description": "Whether this segment is a compositor segment (gameplay footage composited by FFmpeg, not AI-generated). Only Segment 3 in game mode should be true.",
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
                        "is_compositor_segment",
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


async def generate_script(
    user_prompt: str,
    segment_count: int,
    max_retries: int = 2,
    retry_feedback: str = "",
    mode: str = "default",
) -> ScriptOutput:
    """
    Call Gemini to generate a vlog product promotion script (DA direct generation, former TA logic merged in).

    Args:
        user_prompt: Complete user prompt (built by build_da_script_prompt, build_da_game_script_prompt, or legacy version)
        segment_count: Expected number of segments
        max_retries: Max retry count on JSON parse failure
        retry_feedback: Feedback from self_check failure for re-generation
        mode: Generation mode — "default" for product promotion, "game" for game promotion (uses DA_GAME_SCRIPT_SYSTEM_PROMPT)
    """
    client = _get_client()

    # 根据模式选择系统提示词
    system_prompt = DA_GAME_SCRIPT_SYSTEM_PROMPT if mode == "game" else DA_SCRIPT_SYSTEM_PROMPT

    # 游戏模式强制 4 段
    if mode == "game":
        segment_count = 4

    # If retry feedback exists, append it to the user prompt
    prompt = user_prompt
    if retry_feedback:
        prompt += f"\n\n[Retry Feedback]\n{retry_feedback}\nPlease improve the script based on the issues above."

    logger.info(f"[DA] Starting script generation: segment_count={segment_count}, mode={mode}")

    last_error = None

    for attempt in range(1, max_retries + 1):
        try:
            response = await client.aio.models.generate_content(
                model=DA_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.8,
                    response_mime_type="application/json",
                    response_schema=_build_response_schema(),
                ),
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

            # 游戏模式额外校验：必须恰好 4 段，且第 3 段是合成器分段
            if mode == "game":
                if len(script.segments) != 4:
                    raise ValueError(
                        f"[DA] Game mode requires exactly 4 segments, got {len(script.segments)}"
                    )
                # 确保第 3 段（index 2）标记为合成器分段
                seg3 = script.segments[2]
                if not seg3.is_compositor_segment:
                    logger.warning(
                        "[DA] Game mode: Segment 3 missing is_compositor_segment=true, forcing it"
                    )
                    seg3.is_compositor_segment = True

            # Validate frame chain + frame uniqueness (hard validation, retry on failure)
            chain_issues = _validate_frame_chain(script)
            if chain_issues:
                for issue in chain_issues:
                    logger.warning(f"[DA] {issue}")
                raise ValueError(
                    f"[DA] Script frame validation failed ({len(chain_issues)} issue(s)), triggering retry"
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
        job_mode = job.get("mode", "")
        script_mode = "default"  # generate_script 的 mode 参数

        if job_mode == "v2_game":
            # v2 游戏推广模式：固定 4 段结构，DA_GAME_SCRIPT_SYSTEM_PROMPT
            game = job["game"]
            model = job.get("model") or {}
            scene_context = model.get("scene_context", "")
            model_language = model.get("language", "Mandarin Chinese")
            safe_appearance = enforce_minimum_age(model.get("appearance", ""))
            user_prompt = build_da_game_script_prompt(
                game_name=game["name"],
                game_features=game.get("features", ""),
                game_genre=game.get("genre", ""),
                game_orientation=game.get("orientation", "portrait"),
                model_appearance=safe_appearance,
                model_personality=model.get("personality", ""),
                model_outfits=model.get("outfits", ""),
                scene_context=scene_context,
                model_language=model_language,
                intro_line=game.get("intro_line", ""),
                extra_requirements=job.get("extra_requirements", ""),
            )
            script_mode = "game"
            logger.info(f"[DA][Job {job_id}] Game mode: {game['name']}, orientation={game.get('orientation', 'portrait')}")

        elif job_mode == "v2_assets":
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
            mode=script_mode,
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
                mode=script_mode,
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

        if job_mode == "v2_game":
            # Game mode: pass game screenshot separately (VA uses it for phone screen rendering)
            game_screenshot = _load_game_screenshot(job)
            product_image = None  # No product in game mode
            logger.info(f"[DA][Job {job_id}] Game mode: loaded game screenshot for phone screen rendering")
        else:
            game_screenshot = None
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
            game_screenshot=game_screenshot,
            on_frame_done=_on_frame_done,
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

        # 识别需要跳过 Veo 的合成器分段（游戏模式下，Segment 3 是 FFmpeg 合成的游戏画面）
        compositor_segment_indices = set()
        for i, seg in enumerate(script.segments):
            if seg.is_compositor_segment:
                compositor_segment_indices.add(i)
                logger.info(
                    f"[DA][Job {job_id}] Segment {seg.segment_id} (index {i}) is a compositor segment, "
                    f"will skip Veo generation"
                )

        # 构建仅包含需要 Veo 生成的分段的脚本（跳过合成器分段）
        # VGA 只处理非合成器分段；合成器分段的视频由 CompositorService 在 Task 10 中生成
        veo_script = script
        veo_storyboard_paths = storyboard_paths
        if compositor_segment_indices:
            # 创建一个仅包含 Veo 分段的 ScriptOutput 副本
            veo_segments = [seg for i, seg in enumerate(script.segments) if i not in compositor_segment_indices]
            veo_script = ScriptOutput(
                title=script.title,
                voice_anchor=script.voice_anchor,
                style_guide=script.style_guide,
                segments=veo_segments,
                self_check=script.self_check,
            )
            # 对应的 storyboard 帧也需要筛选（每个分段对应 start_frame + end_frame，共享帧只算一次）
            # 非合成器分段的帧索引：每个分段 i 使用 storyboard[i] (start) 和 storyboard[i+1] (end)
            veo_frame_indices = set()
            for i in range(len(script.segments)):
                if i not in compositor_segment_indices:
                    veo_frame_indices.add(i)
                    veo_frame_indices.add(i + 1)
            veo_storyboard_paths = [storyboard_paths[i] for i in sorted(veo_frame_indices)]
            logger.info(
                f"[DA][Job {job_id}] Veo generation: {len(veo_segments)} segments "
                f"(skipped {len(compositor_segment_indices)} compositor segments), "
                f"{len(veo_storyboard_paths)} storyboard frames"
            )

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

        veo_segment_paths = await vga_agent.generate_segments(
            script=veo_script,
            storyboard_paths=veo_storyboard_paths,
            output_dir=segment_dir,
            aspect_ratio=job["aspect_ratio"],
            voice_anchor=script.voice_anchor,
            on_segment_done=_on_segment_done,
        )

        # 重组 segment_paths：将 Veo 生成的片段和合成器片段按原始顺序排列
        # TODO(Task 10): CompositorService 会生成合成器分段的视频，届时此处需要将其插入正确位置
        if compositor_segment_indices:
            segment_paths = []
            veo_idx = 0
            for i in range(len(script.segments)):
                if i in compositor_segment_indices:
                    # 合成器分段：暂时用 None 占位，Task 10 实现 CompositorService 后替换
                    segment_paths.append(None)
                    logger.info(
                        f"[DA][Job {job_id}] Segment {i+1} is compositor — placeholder (CompositorService TBD in Task 10)"
                    )
                else:
                    segment_paths.append(veo_segment_paths[veo_idx])
                    veo_idx += 1
        else:
            segment_paths = veo_segment_paths

        # 过滤掉 None 占位（合成器分段），只统计已生成的视频
        valid_segment_paths = [p for p in segment_paths if p is not None]
        segment_urls = [
            f"/artifacts/{job_id}/segments/{os.path.basename(p)}"
            for p in valid_segment_paths
        ]
        job_manager.update_job(
            job_id,
            progress=0.82,
            message=f"Video segments complete: {len(valid_segment_paths)} Veo + {len(compositor_segment_indices)} compositor",
            segment_urls=segment_urls,
        )
        logger.info(f"[DA][Job {job_id}] VGA complete: {len(valid_segment_paths)} Veo segments")

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

        # 过滤掉 None 占位的合成器分段（Task 10 实现 CompositorService 后，这些占位会被真实路径替换）
        # TODO(Task 10): 合成器分段视频生成后，segment_paths 中不再有 None，此处过滤可移除
        stitch_paths = [p for p in segment_paths if p is not None]
        if len(stitch_paths) < len(segment_paths):
            logger.warning(
                f"[DA][Job {job_id}] Stitching with {len(stitch_paths)}/{len(segment_paths)} segments "
                f"({len(segment_paths) - len(stitch_paths)} compositor segments pending Task 10)"
            )

        # Start/end frame mode: adjacent segments share one frame (prev end frame = next start frame), need to trim overlap
        await ffmpeg_tools.stitch_segments(
            segment_paths=stitch_paths,
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


def _load_game_screenshot(job: dict) -> Optional[bytes]:
    """
    Load game screenshot image from job data (used in v2_game mode as the "product image").
    游戏截图用于 VA 生成手机展示帧（Segment 2 的手机屏幕内容）。

    Args:
        job: Job data dict (must contain "game" key with "screenshot_path")

    Returns:
        Image bytes, or None if file does not exist
    """
    game = job.get("game")
    if not game:
        return None

    # 优先使用游戏截图
    screenshot_path = game.get("screenshot_path")
    if screenshot_path and os.path.exists(screenshot_path):
        try:
            with open(screenshot_path, "rb") as f:
                return f.read()
        except Exception as e:
            logger.warning(f"[DA] Failed to load game screenshot: {e}")

    # 回退到原始上传图片
    originals = game.get("original_images", [])
    for path in originals:
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except Exception:
                continue

    return None


def _load_first_product_image(job: dict) -> Optional[bytes]:
    """
    Load product image (prefers instruction_image, falls back to first original_images entry).
    """
    item = job.get("item")
    if not item:
        return None

    # Prefer ADA-generated product instruction image
    instruction = item.get("instruction_image")
    if instruction and os.path.exists(instruction):
        try:
            with open(instruction, "rb") as f:
                return f.read()
        except Exception:
            pass

    # Fall back to user-uploaded original images
    originals = item.get("original_images", [])
    for path in originals:
        if path and os.path.exists(path):
            try:
                with open(path, "rb") as f:
                    return f.read()
            except Exception:
                continue

    return None

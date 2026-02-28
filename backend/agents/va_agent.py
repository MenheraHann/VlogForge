"""
VA Agent - Visual Director (Visual Agent)
Responsibilities: Fully parallel image-to-image storyboard generation, each frame generated independently from asset images
v12 architecture: All frames in parallel, each frame = asset images (person + product) + style_guide + frame prompt → Nano Banana

Workflow:
  All frames = asset images (person half-body close-up portrait (with scene) + product) + frame prompt → Nano Banana (parallel)
  Each frame is generated from the same set of asset images, naturally maintaining person/scene consistency
  Compared to chained approach: ~3x speed, and avoids camera/person drift caused by chain propagation
"""

import os
import asyncio
import logging
from typing import Callable, Optional

from backend.models import ScriptOutput
from backend.tools.image_gen import image_to_image, text_to_image, save_image
from backend.utils.age_guard import enforce_minimum_age

logger = logging.getLogger(__name__)

# Maximum concurrent generation count (to avoid API rate limiting)
MAX_CONCURRENT = 3

# Unified system instruction for image-to-image generation per frame
VA_FRAME_INSTRUCTION = """You are a professional vlog product promotion storyboard generation assistant.
Based on the provided asset images (person half-body close-up portrait (with filming scene) and product) and frame description, generate the corresponding storyboard frame.

[HIGHEST PRIORITY — Strictly Replicate Reference Image — ZERO TOLERANCE]
- Your primary task is to **pixel-level replicate** ALL visual information from the first reference image (person asset)
- This is the MOST IMPORTANT rule — everything below serves this principle

[Clothing — ABSOLUTELY NO CHANGES]
- The person's clothing must be **exactly identical** to the reference image: same color, same material, same neckline, same sleeves, same fit
- Do NOT change, add, remove, or modify any clothing item — not even subtle changes like rolling up sleeves or unbuttoning
- Do NOT add accessories, jewelry, or props that are not in the reference image
- If the reference shows a white T-shirt, every frame must show the exact same white T-shirt — no switching to other tops

[Scene — ABSOLUTELY NO CHANGES]
- Scene layout (furniture, walls, decorations — positions, proportions, and distances) must be **pixel-level identical** to the reference image
- Do NOT add any new objects to the scene. Do NOT remove any existing objects. Do NOT rearrange anything
- Wall decorations, furniture placement, background items must remain in their exact positions
- The room/environment must look like the exact same physical space — not a similar-looking space

[Lighting — ABSOLUTELY NO CHANGES]
- Lighting direction, color temperature, brightness level, and color tone must be **exactly identical** to the reference image
- Shadow positions and intensities must match the reference image precisely
- Color grading and atmosphere must remain uniform — no warming, no cooling, no filter changes
- If the reference has cool/neutral lighting, every frame must have the same cool/neutral lighting

[Composition — ABSOLUTELY NO CHANGES]
- Camera distance, shooting angle, and the person's position and proportion in the frame must be **exactly identical** to the reference image
- Simulate the effect of a phone mounted in a fixed position — the camera NEVER moves
- No shot switching: no wide shot, no close-up, no top-down, no low-angle, no side angle
- No distance changes: no zoom in, no pull back
- Background must not shift or deform in any way

[Character Consistency — FACE AND BODY]
- Person's facial features (face shape, eyes, nose, mouth, eyebrows) must be **exactly identical** to the reference — no deviation
- Hairstyle, hair color, skin color, body type must strictly match
- Makeup level must match: if reference shows no makeup, do not add makeup

[THE ONLY THINGS ALLOWED TO CHANGE]
- The person's **actions, expressions, gestures** as specified in the frame description
- Props in hand (product being held/displayed) when specified by the frame description
- NOTHING ELSE may change — clothing, scene, lighting, composition, appearance must all remain identical to the reference

[Product Placement]
- When product placement is needed, the person naturally holds or displays the product without changing camera distance
- Product appearance must strictly match the product asset photo

[Visual Style]
- Photorealistic, vlog selfie style, phone front camera quality
- No cinematic feel, no commercial/ad campaign style, no heavy filters

[Anti-Pattern Negatives — MUST enforce]
- no table visible, no camera visible, no selfie angle
- no beauty filter, no skin smoothing, no overly perfect skin
- no overly perfect lighting, no studio lighting, no commercial look
- no warm yellow tint, no romantic filter, no stylized color grading
- raw realism, imperfect beauty, documentary lifestyle quality

[Atmosphere and Realism]
- The generated frame must feel like a real snapshot from daily life — NOT a posed photo or ad campaign image
- Skin should have natural texture: subtle pores, slight unevenness, minor imperfections are GOOD — they make the image look real
- Hair should be slightly messy and asymmetric, not perfectly styled
- The overall mood should be quiet, authentic, and intimate — like a real person in their real space
"""


def _build_frame_prompt(frame_prompt: str, style_guide) -> str:
    """
    Inject style_guide information into the frame prompt to enhance cross-frame consistency.
    v18: 年龄保护 — 对 person_description 和 frame_prompt 执行年龄合规检查
    """
    # 对 frame_prompt 本身执行年龄保护
    frame_prompt = enforce_minimum_age(frame_prompt)

    if not style_guide:
        return frame_prompt

    style_lines = []
    if hasattr(style_guide, 'person_description') and style_guide.person_description:
        # 对 person_description 执行年龄保护
        safe_person_desc = enforce_minimum_age(style_guide.person_description)
        style_lines.append(f"Person: {safe_person_desc}")
    if hasattr(style_guide, 'scene_context') and style_guide.scene_context:
        style_lines.append(f"Scene: {style_guide.scene_context}")
    if hasattr(style_guide, 'visual_style') and style_guide.visual_style:
        style_lines.append(f"Style: {style_guide.visual_style}")
    if hasattr(style_guide, 'lighting') and style_guide.lighting:
        style_lines.append(f"Lighting: {style_guide.lighting}")

    if not style_lines:
        return frame_prompt

    style_block = "\n".join(style_lines)

    # Atmosphere realism tags — appended to every frame to ensure natural feel
    atmosphere_tags = (
        "\n\n[Atmosphere Tags]\n"
        "raw realism, imperfect beauty, authentic daily life moment, "
        "natural skin texture with pores and subtle imperfections, "
        "slightly messy asymmetric hair, relaxed unposed expression, "
        "documentary lifestyle photography, no beauty filter, no skin smoothing, "
        "no overly perfect lighting, no commercial look"
    )

    return f"[Style Guide]\n{style_block}\n\n[Frame Description]\n{frame_prompt}{atmosphere_tags}"


async def generate_storyboard(
    script: ScriptOutput,
    output_dir: str,
    person_image: Optional[bytes] = None,
    product_image: Optional[bytes] = None,
    on_frame_done: Optional[Callable[[int, int, str], None]] = None,
) -> list[str]:
    """
    Fully parallel storyboard frame sequence generation: each frame generated independently from asset images.

    Args:
        script: DA output script (with frame prompts + style_guide)
        output_dir: Storyboard output directory
        person_image: Person half-body close-up portrait bytes (portrait_image, includes filming scene)
        product_image: Product image bytes (instruction_image or original)
        on_frame_done: Callback when each frame is done (frame_index, total_frames, frame_path)

    Returns:
        List of storyboard frame paths (N+1 images, N = segment count)
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments
    style_guide = script.style_guide

    # Collect all frame prompts: frame 1 = first segment's start frame, frames 2~N+1 = each segment's end frame
    frame_specs = []

    # Frame 1: first segment's frame_start_prompt
    frame_specs.append({
        "prompt": segments[0].frame_start_prompt,
        "needs_product": segments[0].needs_product,
        "frame_num": 1,
    })

    # Frames 2 to N+1: each segment's frame_end_prompt
    for i, seg in enumerate(segments):
        frame_specs.append({
            "prompt": seg.frame_end_prompt,
            "needs_product": seg.needs_product,
            "frame_num": i + 2,
        })

    # Defensive check: duplicate frame prompt warning
    seen_prompts = {}
    for spec in frame_specs:
        p = spec["prompt"]
        if p in seen_prompts:
            logger.warning(
                f"[VA] WARNING: Duplicate frame prompt detected: Frame {spec['frame_num']} "
                f"is identical to Frame {seen_prompts[p]} — generated images may be identical"
            )
        else:
            seen_prompts[p] = spec["frame_num"]

    total_frames = len(frame_specs)
    logger.info(
        f"[VA] Full parallel mode: {len(segments)} segments → {total_frames} frames, "
        f"max_concurrent={MAX_CONCURRENT}"
    )

    # Track completion progress
    done_count = 0
    done_lock = asyncio.Lock()

    async def _generate_one(spec: dict) -> tuple[int, str]:
        """Generate a single storyboard frame"""
        nonlocal done_count

        frame_num = spec["frame_num"]
        raw_prompt = spec["prompt"]
        needs_product = spec["needs_product"]

        # Inject style_guide into prompt, reference image anchoring + action instructions
        enhanced_prompt = _build_frame_prompt(raw_prompt, style_guide)
        enhanced_prompt = (
            f"[HIGHEST PRIORITY — Strictly Replicate Reference Image]\n"
            f"The first reference image is the person asset. You MUST strictly replicate ALL visual information from it:\n"
            f"- Person: facial features, hairstyle, skin color, body type, clothing (NO deviation allowed)\n"
            f"- Composition: camera angle, focal distance, person's position and proportion in frame (exactly identical)\n"
            f"- Scene: background layout, furniture/walls/decorations (positions and proportions unchanged)\n"
            f"- Lighting: light direction, color temperature, brightness, color tone (exactly identical)\n\n"
            f"[ONLY ALLOWED CHANGES — Action Instructions]\n{raw_prompt}\n\n"
            f"Only perform the above action/expression/gesture changes. Everything else MUST remain exactly the same as the reference image.\n\n"
            f"{enhanced_prompt}"
        )

        # Build input image list
        input_images = []
        if person_image:
            input_images.append(person_image)
        if product_image and needs_product:
            input_images.append(product_image)

        # Generate image
        if input_images:
            frame_bytes = await image_to_image(
                input_images=input_images,
                prompt=enhanced_prompt,
                system_instruction=VA_FRAME_INSTRUCTION,
            )
        else:
            frame_bytes = await text_to_image(
                prompt=enhanced_prompt,
                system_instruction=VA_FRAME_INSTRUCTION,
            )

        # Save
        path = os.path.join(output_dir, f"frame_{frame_num:03d}.png")
        save_image(frame_bytes, path)

        # Update progress
        async with done_lock:
            done_count += 1
            logger.info(f"[VA] Frame {frame_num} generation complete ({done_count}/{total_frames})")
            if on_frame_done:
                on_frame_done(done_count - 1, total_frames, path)

        return frame_num, path

    # Use semaphore to control concurrency
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _generate_with_limit(spec: dict) -> tuple[int, str]:
        async with semaphore:
            return await _generate_one(spec)

    # Launch all frames in parallel
    tasks = [_generate_with_limit(spec) for spec in frame_specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Sort and organize results by frame number
    ordered_paths = [""] * total_frames
    first_pass_errors = []

    for result in results:
        if isinstance(result, Exception):
            first_pass_errors.append(str(result))
            logger.error(f"[VA] Frame generation failed: {result}")
        else:
            frame_num, path = result
            ordered_paths[frame_num - 1] = path

    # ---- Failed frame retry (retry each failed frame once, reusing the same img2img logic) ----
    failed_indices = [i for i, p in enumerate(ordered_paths) if not p]
    if failed_indices:
        logger.warning(
            f"[VA] First round: {len(failed_indices)} frames failed, starting per-frame retry: "
            f"frame_nums={[i + 1 for i in failed_indices]}"
        )
        retry_tasks = []
        for idx in failed_indices:
            retry_tasks.append(_generate_with_limit(frame_specs[idx]))
        retry_results = await asyncio.gather(*retry_tasks, return_exceptions=True)

        # Fill in successfully retried frames
        still_failed_indices = []
        for idx, result in zip(failed_indices, retry_results):
            if isinstance(result, Exception):
                logger.warning(f"[VA] Frame {idx + 1} retry still failed: {result}")
                still_failed_indices.append(idx)
            else:
                frame_num, path = result
                ordered_paths[idx] = path
                logger.info(f"[VA] Frame {frame_num} retry succeeded")
    else:
        still_failed_indices = []

    # ---- Fallback: for frames that still failed after retry, use simplified prompt with img2img (keep reference image) ----
    if still_failed_indices:
        logger.warning(
            f"[VA] {len(still_failed_indices)} frames still failed after retry, "
            f"falling back to simplified prompt: frame_nums={[i + 1 for i in still_failed_indices]}"
        )
        for idx in still_failed_indices:
            spec = frame_specs[idx]
            frame_num = spec["frame_num"]
            # Simplified prompt: reduce complexity but keep reference image
            simplified_prompt = spec["prompt"]
            try:
                # img2img fallback: always include person reference image
                fallback_images = [person_image]
                if product_image and spec.get("needs_product"):
                    fallback_images.append(product_image)

                fallback_bytes = await image_to_image(
                    input_images=fallback_images,
                    prompt=simplified_prompt,
                    system_instruction=VA_FRAME_INSTRUCTION,
                )
                path = os.path.join(output_dir, f"frame_{frame_num:03d}.png")
                save_image(fallback_bytes, path)
                ordered_paths[idx] = path
                logger.info(f"[VA] Frame {frame_num} simplified prompt img2img fallback succeeded")

                # Update progress
                async with done_lock:
                    done_count += 1
                    if on_frame_done:
                        on_frame_done(done_count - 1, total_frames, path)
            except Exception as e:
                logger.error(f"[VA] Frame {frame_num} fallback also failed: {e}")

    # ---- Final result validation ----
    final_paths = [p for p in ordered_paths if p]
    final_failed = [i + 1 for i, p in enumerate(ordered_paths) if not p]

    if final_failed:
        logger.error(
            f"[VA] Final: {len(final_failed)} frames still failed (retry + fallback both unsuccessful): "
            f"frame_nums={final_failed}"
        )

    if not final_paths:
        raise RuntimeError(f"[VA] All storyboard frames generation failed (including retry and fallback): {first_pass_errors}")

    # Count validation: expect segments + 1 frames
    expected_count = len(segments) + 1
    if len(final_paths) != expected_count:
        logger.warning(
            f"[VA] Frame count mismatch: expected {expected_count}, got {len(final_paths)}, "
            f"missing frame_nums={final_failed}"
        )

    logger.info(f"[VA] All storyboard frames complete: {len(final_paths)}/{total_frames} frames succeeded")
    return final_paths

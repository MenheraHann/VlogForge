"""
VA Agent - 美术指导（Visual Agent）
负责：全并行图生图生成分镜，每帧从素材图独立生成
v12 架构：全帧并行，每帧 = 素材图(人物+产品) + style_guide + 帧提示词 → Nano Banana

工作流：
  所有帧 = 素材图（人物半身近景照（含场景） + 产品）+ 帧提示词 → Nano Banana（并行）
  每帧基于同一组素材图生成，天然保持人物/场景一致性
  相比链式：速度 ~3x，且避免链式传递导致的镜头/人物漂移
"""

import os
import asyncio
import logging
from typing import Callable, Optional

from backend.models import ScriptOutput
from backend.tools.image_gen import image_to_image, text_to_image, save_image

logger = logging.getLogger(__name__)

# 最大并行生成数（避免 API 限流）
MAX_CONCURRENT = 3

# 每帧图生图的系统指令（统一，不再区分首帧/后续帧）
VA_FRAME_INSTRUCTION = """你是专业的 vlog 分镜图生成助手。
基于提供的素材图片（人物半身近景照（含拍摄场景）、产品）和帧描述，生成对应的分镜图。
关键要求：
- 人物外貌和穿着严格匹配人物素材照片
- 场景环境严格匹配人物素材中的拍摄场景
- 仅按照帧描述改变人物动作、表情
- 如需植入产品，自然地融入画面中
- 画面风格：真人写实、vlog 自拍风格
- 光线和色调保持一致
"""


def _build_frame_prompt(frame_prompt: str, style_guide) -> str:
    """
    将 style_guide 信息注入帧提示词，增强跨帧一致性。
    """
    if not style_guide:
        return frame_prompt

    style_lines = []
    if hasattr(style_guide, 'person_description') and style_guide.person_description:
        style_lines.append(f"Person: {style_guide.person_description}")
    if hasattr(style_guide, 'scene_context') and style_guide.scene_context:
        style_lines.append(f"Scene: {style_guide.scene_context}")
    if hasattr(style_guide, 'visual_style') and style_guide.visual_style:
        style_lines.append(f"Style: {style_guide.visual_style}")
    if hasattr(style_guide, 'lighting') and style_guide.lighting:
        style_lines.append(f"Lighting: {style_guide.lighting}")

    if not style_lines:
        return frame_prompt

    style_block = "\n".join(style_lines)
    return f"[Style Guide]\n{style_block}\n\n[Frame Description]\n{frame_prompt}"


async def generate_storyboard(
    script: ScriptOutput,
    output_dir: str,
    person_image: Optional[bytes] = None,
    product_image: Optional[bytes] = None,
    on_frame_done: Optional[Callable[[int, int, str], None]] = None,
) -> list[str]:
    """
    全并行生成分镜图序列：每帧从素材图独立生成。

    参数:
        script: DA 输出的脚本（含帧提示词 + style_guide）
        output_dir: 分镜图输出目录
        person_image: 人物半身近景照 bytes（portrait_image，已包含拍摄场景）
        product_image: 产品图 bytes（instruction_image 或 original）
        on_frame_done: 每帧完成时的回调 (帧索引, 总帧数, 帧路径)

    返回:
        分镜图路径列表（N+1 张图，N = 分段数）
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments
    style_guide = script.style_guide

    # 收集所有帧的提示词：帧1=首段首帧，帧2~N+1=各段尾帧
    frame_specs = []

    # 帧 1：第一段的 frame_start_prompt
    frame_specs.append({
        "prompt": segments[0].frame_start_prompt,
        "needs_product": segments[0].needs_product,
        "frame_num": 1,
    })

    # 帧 2 到 N+1：每段的 frame_end_prompt
    for i, seg in enumerate(segments):
        frame_specs.append({
            "prompt": seg.frame_end_prompt,
            "needs_product": seg.needs_product,
            "frame_num": i + 2,
        })

    total_frames = len(frame_specs)
    logger.info(
        f"[VA] 全并行模式: {len(segments)} 段 → {total_frames} 帧, "
        f"并发上限={MAX_CONCURRENT}"
    )

    # 记录完成进度
    done_count = 0
    done_lock = asyncio.Lock()

    async def _generate_one(spec: dict) -> tuple[int, str]:
        """生成单帧分镜图"""
        nonlocal done_count

        frame_num = spec["frame_num"]
        raw_prompt = spec["prompt"]
        needs_product = spec["needs_product"]

        # 注入 style_guide 到提示词
        enhanced_prompt = _build_frame_prompt(raw_prompt, style_guide)

        # 构建输入图片列表
        input_images = []
        if person_image:
            input_images.append(person_image)
        if product_image and needs_product:
            input_images.append(product_image)

        # 生成图片
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

        # 保存
        path = os.path.join(output_dir, f"frame_{frame_num:03d}.png")
        save_image(frame_bytes, path)

        # 更新进度
        async with done_lock:
            done_count += 1
            logger.info(f"[VA] 帧 {frame_num} 生成完成 ({done_count}/{total_frames})")
            if on_frame_done:
                on_frame_done(done_count - 1, total_frames, path)

        return frame_num, path

    # 使用信号量控制并发数
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def _generate_with_limit(spec: dict) -> tuple[int, str]:
        async with semaphore:
            return await _generate_one(spec)

    # 全部并行发出
    tasks = [_generate_with_limit(spec) for spec in frame_specs]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # 按帧号排序整理结果
    ordered_paths = [""] * total_frames
    errors = []

    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result))
            logger.error(f"[VA] 帧生成失败: {result}")
        else:
            frame_num, path = result
            ordered_paths[frame_num - 1] = path

    # 过滤掉失败的帧
    final_paths = [p for p in ordered_paths if p]

    if errors:
        logger.warning(f"[VA] {len(errors)}/{total_frames} 帧生成失败: {errors[:3]}")

    if not final_paths:
        raise RuntimeError(f"[VA] 所有分镜图生成失败: {errors}")

    logger.info(f"[VA] 分镜图全部完成: {len(final_paths)}/{total_frames} 帧成功")
    return final_paths

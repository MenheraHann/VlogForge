"""
VA Agent - 美术指导（Visual Agent）
负责：链式图生图生成分镜，逐帧保持画面一致性
v4 架构：使用 Nano Banana img2img 链式生成

工作流：
  帧 1 = 素材图（人物造型 + 场景 + 产品）+ 帧 1 提示词 → Nano Banana
  帧 N = 帧 N-1 的输出图 + 帧 N 提示词 → Nano Banana
  每帧基于上一帧生成，天然保持画面一致性
"""

import os
import logging
from typing import Optional

from backend.models import ScriptOutput
from backend.tools.image_gen import image_to_image, save_image

logger = logging.getLogger(__name__)

# VA 图生图的系统指令
VA_IMG2IMG_INSTRUCTION = """你是专业的 vlog 分镜图生成助手。
基于上一帧图片和新的帧描述，生成下一帧图片。
关键要求：
- 保持人物外貌、穿着、场景环境的高度一致性
- 仅改变人物动作、表情、镜头角度等描述中指定的变化
- 画面风格保持统一：真人写实、vlog 自拍风格
- 光线和色调与上一帧一致
"""

# 首帧生成指令（多图输入）
VA_FIRST_FRAME_INSTRUCTION = """你是专业的 vlog 分镜图生成助手。
基于提供的素材图片（人物造型、场景、产品），按照帧描述生成第一帧分镜图。
关键要求：
- 将人物放入指定场景中
- 人物外貌和穿着严格匹配人物素材
- 场景环境严格匹配场景素材
- 如需植入产品，自然地融入画面中
- 画面风格：真人写实、vlog 自拍风格
"""


async def generate_storyboard(
    script: ScriptOutput,
    output_dir: str,
    person_image: Optional[bytes] = None,
    scene_image: Optional[bytes] = None,
    product_image: Optional[bytes] = None,
) -> list[str]:
    """
    根据脚本生成完整分镜图序列（链式图生图）。

    参数:
        script: DA 输出的脚本（含帧提示词）
        output_dir: 分镜图输出目录
        person_image: 人物造型图 bytes（selected_look）
        scene_image: 场景图 bytes（selected_scene）
        product_image: 产品图 bytes（instruction_image 或 original）

    返回:
        分镜图路径列表（N+1 张图，N = 分段数）
    """
    os.makedirs(output_dir, exist_ok=True)
    segments = script.segments
    storyboard_paths = []

    logger.info(f"[VA] 开始生成分镜图: {len(segments)} 段 → {len(segments) + 1} 帧")

    # ========== 帧 1：首帧（多图输入） ==========
    first_prompt = segments[0].frame_start_prompt

    # 收集所有可用的素材图作为输入
    input_images = []
    if person_image:
        input_images.append(person_image)
    if scene_image:
        input_images.append(scene_image)
    if product_image and segments[0].needs_product:
        input_images.append(product_image)

    if input_images:
        # 有素材图 → 图生图
        current_frame = await image_to_image(
            input_images=input_images,
            prompt=first_prompt,
            system_instruction=VA_FIRST_FRAME_INSTRUCTION,
        )
    else:
        # 无素材图 → 文生图（降级模式）
        from backend.tools.image_gen import text_to_image
        current_frame = await text_to_image(
            prompt=first_prompt,
            system_instruction=VA_FIRST_FRAME_INSTRUCTION,
        )

    path = os.path.join(output_dir, "frame_001.png")
    save_image(current_frame, path)
    storyboard_paths.append(path)
    logger.info(f"[VA] 帧 1 生成完成（首帧）")

    # ========== 帧 2 到 N+1：链式图生图 ==========
    for i, seg in enumerate(segments):
        frame_prompt = seg.frame_end_prompt
        frame_num = i + 2

        # 如果该分段需要产品，把产品图也加入输入
        imgs = [current_frame]
        if product_image and seg.needs_product:
            imgs.append(product_image)

        current_frame = await image_to_image(
            input_images=imgs,
            prompt=frame_prompt,
            system_instruction=VA_IMG2IMG_INSTRUCTION,
        )

        path = os.path.join(output_dir, f"frame_{frame_num:03d}.png")
        save_image(current_frame, path)
        storyboard_paths.append(path)
        logger.info(f"[VA] 帧 {frame_num} 生成完成（分段 {seg.segment_id} 尾帧）")

    logger.info(f"[VA] 分镜图全部完成: {len(storyboard_paths)} 帧")
    return storyboard_paths

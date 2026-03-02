# Game Promotion Pivot Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Transform VlogForge from a generic product promotion video generator into a mobile game promotion video generator with fixed 4-segment video structure.

**Architecture:** Incremental refactor on existing FastAPI + Vanilla JS stack. Replace "Item" asset type with "Game" asset type. Simplify DA from creative script generation to fixed template. Add CompositorService for FFmpeg gameplay video compositing. Keep Model asset system, job queue, and SSE progress unchanged.

**Tech Stack:** Python 3.12, FastAPI, Gemini 2.5 Flash, Veo 3.1, FFmpeg, Vanilla JS

---

## Task 1: Data Models — GameAsset + AssetType

**Files:**
- Modify: `backend/models.py`

**Step 1: Add GameAsset model and update AssetType enum**

In `backend/models.py`, update `AssetType` enum (line 41-44) to replace ITEM with GAME:

```python
class AssetType(str, Enum):
    GAME = "game"
    MODEL = "model"
```

Add `GameAsset` model after `ModelAsset` (after line 142):

```python
class GameAsset(BaseModel):
    """手机游戏资产"""
    id: str
    name: str = ""
    status: AssetStatus = AssetStatus.GENERATING
    error_message: Optional[str] = None

    # 游戏信息
    orientation: str = "portrait"  # "portrait" | "landscape"
    genre: str = ""                # 游戏类型
    description: str = ""          # 用户初始描述
    features: str = ""             # ADA 问卷后整理的特色/卖点
    selling_points: dict = {}      # P0/P1/P2 卖点（结构同 ItemAsset）
    intro_line: Optional[str] = None  # 可选铺垫段台词

    # 问卷
    questionnaire_status: str = QuestionnaireStatus.PENDING
    questionnaire_fields: list = []

    # 文件路径
    screenshot_path: Optional[str] = None    # 手机截图
    gameplay_video_path: Optional[str] = None # 游戏录屏
    original_images: list = []                # 用户上传的原始图片（截图）
```

Update `VideoGenerateRequest` (line 147-153) to use game_id:

```python
class VideoGenerateRequest(BaseModel):
    game_id: str
    model_id: Optional[str] = None
    extra_requirements: Optional[str] = None
```

Remove `platform` and `duration` fields from `VideoGenerateRequest` (fixed structure, always 9:16).

Update `ScriptSegment` (line 167-176) — add `is_compositor_segment` field:

```python
class ScriptSegment(BaseModel):
    segment_id: int
    narration: str = ""
    action_description: str = ""
    frame_start_prompt: str = ""
    frame_end_prompt: str = ""
    needs_product: bool = False
    veo_description: str = ""
    is_compositor_segment: bool = False  # True = 第3段游戏画面，走FFmpeg合成
```

**Step 2: Verify model imports compile**

Run: `cd /Users/menherahan/Documents/Match/Gemini_Live_Agent_Challenge && python -c "from backend.models import GameAsset, AssetType; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add backend/models.py
git commit -m "feat: add GameAsset model, replace Item with Game in AssetType"
```

---

## Task 2: Asset Storage — GameAsset Support

**Files:**
- Modify: `backend/services/asset_manager.py`
- Modify: `backend/services/json_storage.py`

**Step 1: Update json_storage.py to handle games**

In `json_storage.py`, modify `load_all()` (line 24-67):
- Add `"games"` key alongside `"items"` and `"models"`
- Deserialize game entries as `GameAsset`
- Add `"game"` counter

In `save_all()` (line 69-104):
- Include games dict in serialization

**Step 2: Update asset_manager.py with game CRUD**

Add these methods to `AssetManager`:

```python
# 类似 save_item/get_item/list_items/delete_item 的模式
def save_game(self, asset: GameAsset):
    self._games[asset.id] = asset
    self._persist()

def get_game(self, asset_id: str) -> Optional[GameAsset]:
    return self._games.get(asset_id)

def list_games(self) -> list:
    return list(self._games.values())

def delete_game(self, asset_id: str) -> bool:
    if asset_id in self._games:
        del self._games[asset_id]
        self._persist()
        return True
    return False
```

Update `get_asset()` (line 215-221) to route `game_` prefix.
Update `get_stats()` to include game count.
Update `_recover_generating_assets()` to handle game assets.
Update `generate_id()` to support `"game"` type.

**Step 3: Verify storage round-trip**

Run: `python -c "from backend.services.asset_manager import AssetManager; am = AssetManager(); print(am.get_stats())"`
Expected: Stats dict includes `games: 0`

**Step 4: Commit**

```bash
git add backend/services/json_storage.py backend/services/asset_manager.py
git commit -m "feat: add game asset storage and CRUD to AssetManager"
```

---

## Task 3: ADA Prompts — Game Analysis

**Files:**
- Modify: `backend/prompts/ada_prompts.py`

**Step 1: Add game analysis system prompt**

Add `ADA_GAME_ANALYZE_SYSTEM_PROMPT` — similar structure to `ADA_ITEM_ANALYZE_SYSTEM_PROMPT` (line 9-81) but focused on:
- 游戏类型识别（RPG、射击、休闲、策略等）
- 核心玩法分析
- 游戏爆点/好玩的点（P0/P1/P2 卖点）
- 目标人群
- 问卷侧重：什么最好玩？推荐理由？适合什么场景玩？

**Step 2: Add game analysis schema**

Add `get_game_analyze_schema()` — returns JSON schema for game analysis output:
```python
{
    "name": str,
    "genre": str,
    "orientation": str,  # AI 根据截图判断
    "selling_points": {"P0": [...], "P1": [...], "P2": [...]},
    "questionnaire": [{
        "key": str, "label": str,
        "option_a": str, "option_b": str,
        "value": str, "priority": str,
        "source": str, "required": bool
    }],
    "full_description": str
}
```

**Step 3: Add game confirm prompt and schema**

Add `ADA_GAME_CONFIRM_SYSTEM_PROMPT` — similar to `ADA_ITEM_CONFIRM_SYSTEM_PROMPT` (line 155-202):
- 整理用户选择的问卷答案
- 生成 features（游戏特色描述）
- 生成 full_description（完整游戏描述）

Add `get_game_confirm_schema()`:
```python
{
    "features": str,       # 游戏特色/卖点总结
    "full_description": str,
    "intro_line_suggestion": str  # AI建议的铺垫段台词
}
```

**Step 4: Add builder functions**

```python
def build_game_analyze_prompt(game_description: str) -> str:
    """构建游戏分析的用户提示"""

def build_game_confirm_prompt(confirmed_fields: list, selling_points: dict) -> str:
    """构建游戏确认的用户提示"""
```

**Step 5: Commit**

```bash
git add backend/prompts/ada_prompts.py
git commit -m "feat: add ADA game analysis prompts and schemas"
```

---

## Task 4: ADA Agent — Game Functions

**Files:**
- Modify: `backend/agents/ada_agent.py`

**Step 1: Add analyze_game function**

Similar to `analyze_item` (line 123-183) but:
- Accepts: `asset_id`, `description`, `screenshot_image` (bytes), `gameplay_video_path` (str)
- Saves screenshot to `ASSETS_DIR/{asset_id}/screenshot.png`
- Saves gameplay video to `ASSETS_DIR/{asset_id}/gameplay.mp4`
- Uses ffprobe to auto-detect orientation from screenshot dimensions
- Calls `_text_analysis()` with `ADA_GAME_ANALYZE_SYSTEM_PROMPT` + screenshot image
- Returns `GameAsset` with questionnaire populated

```python
async def analyze_game(asset_id: str, description: str,
                       screenshot: bytes, video_path: str) -> GameAsset:
    # 1. 保存截图和视频
    # 2. ffprobe 检测截图尺寸 → 判断 orientation
    # 3. AI 分析游戏 → 问卷
    # 4. 返回 GameAsset
```

**Step 2: Add confirm_game function**

Similar to `confirm_item` (line 188-346) but:
- No image generation (no thumbnail/three_view needed)
- Calls `_text_analysis()` with `ADA_GAME_CONFIRM_SYSTEM_PROMPT`
- Returns GameAsset with features filled

```python
async def confirm_game(asset: GameAsset, confirmed_fields: list) -> GameAsset:
    # 1. 更新问卷字段
    # 2. AI 整理特色/卖点
    # 3. 返回确认后的 GameAsset
```

**Step 3: Add orientation detection helper**

```python
async def _detect_orientation(image_path: str) -> str:
    """用 ffprobe 或 PIL 检测图片方向"""
    # width > height → "landscape"
    # width <= height → "portrait"
```

**Step 4: Commit**

```bash
git add backend/agents/ada_agent.py
git commit -m "feat: add ADA game analysis and confirm functions"
```

---

## Task 5: Game API Endpoints

**Files:**
- Modify: `backend/main.py`

**Step 1: Add game analyze endpoint**

```python
@app.post("/api/assets/game/analyze")
async def analyze_game_asset(
    description: str = Form(...),
    screenshot: UploadFile = File(...),
    gameplay_video: UploadFile = File(...)
):
    # 1. generate_id("game")
    # 2. 保存视频到临时路径
    # 3. 调用 ada_agent.analyze_game()
    # 4. asset_manager.save_game()
    # 5. 返回 GameAsset（含问卷）
```

**Step 2: Add game confirm endpoint**

```python
@app.post("/api/assets/game/{asset_id}/confirm")
async def confirm_game_asset(asset_id: str, body: dict = Body(...)):
    # 1. get_game(asset_id)
    # 2. ada_agent.confirm_game()
    # 3. save_game()
    # 4. 返回确认后的 GameAsset
```

**Step 3: Update existing endpoints**

- `GET /api/assets`: Add games to response (alongside items and models)
- `DELETE /api/assets/{asset_id}`: Route `game_` prefix to `delete_game()`
- `GET /api/assets/{asset_id}`: Route `game_` prefix to `get_game()`
- `PUT /api/assets/{asset_id}`: Route `game_` prefix

**Step 4: Update generate v2 endpoint**

Change `POST /api/generate/v2` to accept `game_id` instead of `item_id`:
- Remove `platform`, `duration`, `segment_count` (all fixed now)
- Always 9:16 aspect ratio
- Always 4 segments
- Load game asset + model asset
- Build job_data with game info instead of item info

**Step 5: Verify endpoints start**

Run: `cd /Users/menherahan/Documents/Match/Gemini_Live_Agent_Challenge && python -m uvicorn backend.main:app --port 8000 &` then `curl http://localhost:8000/api/assets`
Expected: Response includes `games: []`

**Step 6: Commit**

```bash
git add backend/main.py
git commit -m "feat: add game asset API endpoints, update generate/v2"
```

---

## Task 6: DA Prompts — Fixed Game Template

**Files:**
- Modify: `backend/prompts/da_prompts.py`

**Step 1: Add game-specific system prompt**

Add `DA_GAME_SCRIPT_SYSTEM_PROMPT` — replaces the creative freedom of `DA_SCRIPT_SYSTEM_PROMPT` with a fixed 4-segment template:

```
你是游戏推广视频的导演。视频结构固定为 4 段：

## 段 1：铺垫（~6秒）
- 人物坐在场景中，自然聊天
- 过渡到掏手机
- 台词使用用户提供的 intro_line，或根据游戏特色生成

## 段 2：展示手机（~6秒）
- 人物举起手机，屏幕正对镜头
- 手机方向：{orientation}（竖屏=竖着拿，横屏=横着拿）
- 手机屏幕上显示游戏截图
- 台词简短介绍游戏

## 段 3：游戏画面（= 录屏时长）
- [COMPOSITOR SEGMENT] 此段不生成 Veo 视频
- 背景：人物玩手机的静态图（高斯模糊）
- 前景：游戏录屏居中叠加
- 无口播

## 段 4：CTA（~6秒）
- 人物放下手机，看向镜头
- 口播推荐下载
- 结尾微笑
```

保留 Frame Chain Continuity、Upper Body、Static Camera 等核心规则。
去掉 Product Display Only（不适用于游戏）。
标记段 3 的 `is_compositor_segment: true`。

**Step 2: Add game script prompt builder**

```python
def build_da_game_script_prompt(
    game_name: str,
    game_features: str,
    game_genre: str,
    game_orientation: str,
    model_appearance: str,
    model_personality: str,
    model_outfits: str,
    scene_context: str,
    model_language: str = "Mandarin Chinese",
    intro_line: str = "",
    extra_requirements: str = ""
) -> str:
    """构建游戏推广视频脚本的用户提示"""
```

**Step 3: Commit**

```bash
git add backend/prompts/da_prompts.py
git commit -m "feat: add DA fixed 4-segment game script prompts"
```

---

## Task 7: DA Agent — Game Pipeline

**Files:**
- Modify: `backend/agents/da_agent.py`

**Step 1: Update generate_script for game mode**

Modify `generate_script` (line 229-309) to accept a `mode` parameter:
- `mode="game"`: Uses `DA_GAME_SCRIPT_SYSTEM_PROMPT`, forces exactly 4 segments, validates segment 3 has `is_compositor_segment: true`
- `mode="product"`: Keeps existing behavior (for backward compat if needed)

Update `_build_response_schema()` to include `is_compositor_segment` field.

**Step 2: Update run_pipeline for game videos**

Modify `run_pipeline` (line 312-628):

**Stage 1 (Script):** Detect `mode == "v2_game"` from job_data. Call `build_da_game_script_prompt()` instead of `build_da_script_prompt()`. Pass game asset data.

**Stage 2 (Storyboard):** Pass game screenshot to VA for the "展示手机" frame (segment 2). Generate an extra "person playing phone" static image for segment 3 background.

**Stage 3 (Video):** For each segment:
- Segments 1, 2, 4 → Veo (existing flow)
- Segment 3 → CompositorService (new)

**Stage 4 (Stitch):** Same FFmpeg stitching, just 4 segments now.

**Step 3: Commit**

```bash
git add backend/agents/da_agent.py
git commit -m "feat: update DA pipeline for game video generation"
```

---

## Task 8: VA Agent — Phone Poses + Screenshot Rendering

**Files:**
- Modify: `backend/agents/va_agent.py`

**Step 1: Add phone-specific prompt instructions**

Update `VA_FRAME_INSTRUCTION` or add `VA_GAME_FRAME_INSTRUCTION` with:
- 人物拿手机的姿势约束
- 竖屏：竖着拿手机，手机屏幕正对镜头
- 横屏：双手横着拿手机，手机屏幕正对镜头
- 手机屏幕内容 = 用户截图（作为参考图传入 img2img）

**Step 2: Update generate_storyboard for game mode**

Modify `generate_storyboard` (line 133-357):
- Accept `game_screenshot` parameter (bytes)
- For segment 2 的 frame_end（展示手机帧）: 传入 game_screenshot 作为额外参考图，prompt 中明确要求将截图内容渲染到手机屏幕上
- 额外生成一张 `playing_phone.png`（人物玩手机的静态图），用于段 3 的模糊背景

**Step 3: Commit**

```bash
git add backend/agents/va_agent.py
git commit -m "feat: VA phone pose generation with screenshot rendering"
```

---

## Task 9: CompositorService — FFmpeg Gameplay Compositing

**Files:**
- Create: `backend/services/compositor.py`

**Step 1: Create CompositorService**

```python
"""游戏画面合成服务 — 高斯模糊背景 + 游戏视频叠加"""

import asyncio
import subprocess
import logging

logger = logging.getLogger(__name__)


async def compose_gameplay_segment(
    playing_phone_image: str,
    gameplay_video: str,
    orientation: str,
    output_path: str,
    target_width: int = 1080,
    target_height: int = 1920
) -> str:
    """
    合成第 3 段游戏画面视频。

    Args:
        playing_phone_image: VA 生成的人物玩手机静态图路径
        gameplay_video: 用户上传的游戏录屏路径
        orientation: "portrait" | "landscape"
        output_path: 输出视频路径
        target_width: 最终视频宽度（默认 1080，9:16）
        target_height: 最终视频高度（默认 1920，9:16）

    Returns:
        输出视频路径
    """
    # 1. 获取游戏视频的时长和尺寸 (ffprobe)
    # 2. 计算游戏视频在画面中的位置和大小:
    #    - portrait: 居中，高度 = target_height * 0.5
    #    - landscape: 居中，宽度 ≤ target_width
    # 3. FFmpeg 命令:
    #    - 输入 1: playing_phone_image (loop 为视频时长)
    #    - 滤镜: gblur=sigma=30 (高斯模糊)
    #    - 输入 2: gameplay_video (缩放到计算好的尺寸)
    #    - overlay: 居中叠加
    #    - 输出: output_path (H.264, 30fps)

    # ffprobe 获取游戏视频信息
    probe_cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", gameplay_video
    ]

    # 构建 FFmpeg 合成命令
    # 竖屏: overlay 居中，游戏视频高度 = 50%
    # 横屏: overlay 居中，游戏视频宽度 ≤ 画面宽度

    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", playing_phone_image,  # 静态背景
        "-i", gameplay_video,                        # 游戏视频
        "-filter_complex",
        f"[0:v]scale={target_width}:{target_height},gblur=sigma=30[bg];"
        f"[1:v]scale=...[game];"  # 根据 orientation 计算
        f"[bg][game]overlay=x=(W-w)/2:y=(H-h)/2[out]",
        "-map", "[out]",
        "-t", duration,  # 游戏视频时长
        "-c:v", "libx264", "-r", "30",
        "-pix_fmt", "yuv420p",
        output_path
    ]

    proc = await asyncio.create_subprocess_exec(
        *ffmpeg_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error(f"FFmpeg 合成失败: {stderr.decode()}")
        raise RuntimeError(f"Compositor FFmpeg failed: {stderr.decode()[:500]}")

    logger.info(f"游戏画面合成完成: {output_path}")
    return output_path
```

**Step 2: Verify FFmpeg command works**

Test with a sample image and video to ensure the filter_complex syntax is correct.

**Step 3: Commit**

```bash
git add backend/services/compositor.py
git commit -m "feat: add CompositorService for gameplay video compositing"
```

---

## Task 10: VGA Agent — Compositor Integration

**Files:**
- Modify: `backend/agents/vga_agent.py`

**Step 1: Route compositor segments**

Update `generate_segments` (line 31-165):
- Check each segment's `is_compositor_segment` field
- If `True`: skip Veo, call `compositor.compose_gameplay_segment()` instead
- Need to pass `playing_phone_image` path and `gameplay_video` path from job data

```python
async def generate_segments(self, script, storyboard_paths, output_dir,
                            aspect_ratio, voice_anchor, on_segment_done,
                            job_data=None):  # 新增参数
    for i, segment in enumerate(script.segments):
        if segment.is_compositor_segment and job_data:
            # 走 CompositorService
            game = job_data.get("game", {})
            playing_phone_img = storyboard_paths[i]  # 人物玩手机图
            gameplay_video = game.get("gameplay_video_path")
            orientation = game.get("orientation", "portrait")
            output_path = os.path.join(output_dir, f"segment_{i:03d}.mp4")
            await compositor.compose_gameplay_segment(
                playing_phone_img, gameplay_video, orientation, output_path
            )
        else:
            # 走 Veo（现有逻辑）
            ...
```

**Step 2: Commit**

```bash
git add backend/agents/vga_agent.py
git commit -m "feat: route compositor segments in VGA pipeline"
```

---

## Task 11: Frontend — Games Column & Create Form

**Files:**
- Modify: `frontend/index.html`
- Modify: `frontend/app.js`

**Step 1: Replace items column with games column in HTML**

In `index.html` (lines 86-99):
- Change `data-i18n-html="asset.itemsIcon"` → `asset.gamesIcon`
- Change `id="count-items"` → `id="count-games"`
- Change `data-create="items"` → `data-create="games"`
- Change `id="col-items"` → `id="col-games"`
- Update all items-related data attributes

**Step 2: Update dock HTML**

In `index.html` (lines 127-197):
- Change `#slot-item` → `#slot-game`
- Remove platform selector (`#gen-platform`)
- Remove duration/segments selector (`#gen-segments`)
- Update labels and icons

**Step 3: Update app.js — Asset rendering**

- `createMiniCard`: Handle `type === "games"` (show screenshot thumbnail, gameplay video icon)
- `refreshAssets()`: Fetch games instead of items, render to `#col-games`
- Remove item-specific questionnaire opening logic, replace with game questionnaire

**Step 4: Update app.js — Game creation form**

Modify `openCreateModal` for `type === "games"`:
- Description textarea
- Screenshot upload (single image, required)
- Gameplay video upload (single video, required)
- Submit calls `/api/assets/game/analyze`
- On success opens questionnaire modal

**Step 5: Update app.js — Dock**

- `setupSlot("game")` instead of `setupSlot("item")`
- `slotAssets.game` instead of `slotAssets.item`
- Remove platform and segment count logic
- `updateGenButton()`: Enable when game bound + questionnaire completed + (model ready or unbound)

**Step 6: Update app.js — Generate**

- POST to `/api/generate/v2` with `game_id` instead of `item_id`
- Remove platform and segment_count from FormData

**Step 7: Commit**

```bash
git add frontend/index.html frontend/app.js
git commit -m "feat: replace items with games in frontend UI"
```

---

## Task 12: i18n — Update All Language Files

**Files:**
- Modify: `frontend/i18n/zh-CN.json`
- Modify: `frontend/i18n/en.json`
- Modify: `frontend/i18n/ja.json`
- Modify: `frontend/i18n/ko.json`
- Modify: `frontend/i18n/es.json`
- Modify: `frontend/i18n/pt.json`

**Step 1: Update asset section keys**

In all 6 language files, replace item-related keys with game-related keys:

```json
{
  "asset": {
    "games": "游戏",
    "models": "人物",
    "gamesIcon": "<svg...> 游戏",
    "modelsIcon": "<svg...> 人物",
    "addGame": "+ 添加游戏",
    "addModel": "+ 添加人物",
    "noAssets": "暂无素材",
    "unknownAsset": "未知素材"
  }
}
```

- Remove: `items`, `itemsIcon`, `addItem` keys
- Add: `games`, `gamesIcon`, `addGame` keys

**Step 2: Update form section**

- Add game-specific form labels: upload screenshot, upload gameplay video
- Update questionnaire labels for game context

**Step 3: Update dock labels**

- Change slot labels from "物品" → "游戏"
- Remove platform and duration labels

**Step 4: Commit**

```bash
git add frontend/i18n/*.json
git commit -m "feat: update i18n for game promotion UI"
```

---

## Task 13: Config Updates

**Files:**
- Modify: `backend/config.py`

**Step 1: Update video parameters**

```python
# 游戏推广视频固定参数
GAME_SEGMENT_COUNT = 4          # 固定4段
GAME_ASPECT_RATIO = "9:16"      # 固定竖屏
GAME_VEO_SEGMENTS = [0, 1, 3]   # Veo生成的段索引
GAME_COMPOSITOR_SEGMENT = 2      # FFmpeg合成的段索引
COMPOSITOR_BLUR_SIGMA = 30       # 高斯模糊强度
```

Remove or deprecate `PLATFORM_ASPECT_MAP`, `MIN_SEGMENTS`, `MAX_SEGMENTS`.

**Step 2: Commit**

```bash
git add backend/config.py
git commit -m "feat: add game video config constants"
```

---

## Task 14: Integration — End-to-End Verification

**Step 1: Start server and verify**

```bash
cd /Users/menherahan/Documents/Match/Gemini_Live_Agent_Challenge
python -m uvicorn backend.main:app --port 8000
```

**Step 2: Manual test flow**

1. Open `http://localhost:8000`
2. Create a game asset (upload screenshot + video + description)
3. Complete questionnaire
4. Select/create a model
5. Bind game + model to dock
6. Generate video
7. Verify 4-segment structure in progress view
8. Check final video output

**Step 3: Cleanup unused code**

- Remove or comment out item-specific endpoints that are no longer used
- Remove item-specific ADA prompts if confirmed unused
- Clean up legacy imports

**Step 4: Final commit**

```bash
git add -A
git commit -m "feat: complete game promotion pivot, cleanup unused item code"
```

---

## Execution Order Summary

| # | Task | Dependencies | Estimated Effort |
|---|------|-------------|-----------------|
| 1 | Data Models | None | Small |
| 2 | Asset Storage | Task 1 | Small |
| 3 | ADA Prompts | None | Medium |
| 4 | ADA Agent | Task 1, 2, 3 | Medium |
| 5 | Game API Endpoints | Task 1, 2, 4 | Medium |
| 6 | DA Prompts | None | Medium |
| 7 | DA Agent Pipeline | Task 1, 6 | Large |
| 8 | VA Agent | Task 7 | Medium |
| 9 | CompositorService | None | Medium |
| 10 | VGA Integration | Task 9 | Small |
| 11 | Frontend | Task 5 | Large |
| 12 | i18n | Task 11 | Small |
| 13 | Config | None | Small |
| 14 | Integration | All above | Medium |

**Parallelizable groups:**
- Group A (no deps): Tasks 1, 3, 6, 9, 13
- Group B (after Group A): Tasks 2, 4, 7, 8, 10
- Group C (after Group B): Tasks 5, 11, 12
- Group D (after Group C): Task 14

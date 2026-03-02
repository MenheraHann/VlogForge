# VlogForge 方向转型设计：手机游戏推广视频生成器

**日期**: 2026-03-03
**状态**: 已确认，待实施
**截止日期**: 2026-03-16（Gemini Live Agent Challenge）

---

## 概述

VlogForge 从通用产品推广视频生成器转型为**手机游戏专属推广视频生成器**。用户上传游戏截图和录屏视频，系统生成一段 AI 人物带货手游的短视频。

## 视频结构（固定 4 段）

```
[1. 铺垫段] → [2. 展示手机段] → [3. 游戏画面段] → [4. CTA段]
```

| 段 | 内容 | 生成方式 | 时长 |
|---|------|---------|------|
| 1. 铺垫 | 人物坐着闲聊，自然过渡到掏手机 | VA 分镜 → Veo 视频 | ~6s |
| 2. 展示手机 | 人物举起手机，屏幕显示游戏截图 | VA 渲染截图到手机屏幕 → Veo 视频 | ~6s |
| 3. 游戏画面 | 游戏录屏 + 高斯模糊人物玩手机背景 | VA 生成静态图 → FFmpeg 合成 | = 录屏时长 |
| 4. CTA | 人物放下手机，口播推荐下载 | VA 分镜 → Veo 视频 | ~6s |

## 用户输入

- **人物**：保留现有 model 资产系统（创建/选择）
- **游戏资产**（替代"物品"资产）：
  - 手机截图（PNG/JPG）
  - 游戏录屏视频（MP4，横屏或竖屏）
  - 简短游戏描述
  - 经 ADA 问卷后的详细特色/卖点
  - 可选：铺垫段台词

## 横竖屏适配

根据用户上传的截图/视频自动检测方向（用户可确认/修改）：

- **竖屏游戏**：人物竖着拿手机，第 3 段游戏视频居中占画面 50% 高度
- **横屏游戏**：人物横着拿手机，第 3 段游戏视频居中，宽度不超过画面宽度

---

## 游戏资产存储

```
assets/game_001/
  ├── screenshot.png      # 用户上传的手机截图
  ├── gameplay.mp4        # 用户上传的游戏录屏
  └── (metadata in _assets_data.json)
```

**Metadata 字段**：
- `type`: "games"
- `name`: 游戏名称
- `orientation`: "portrait" | "landscape"
- `genre`: 游戏类型
- `description`: 用户初始描述
- `features`: ADA 问卷后整理的特色/卖点
- `intro_line`: 可选铺垫段台词

---

## Agent 改动

### ADA Agent
- **保留**：问卷生成机制（analyze → questionnaire → confirm）
- **改动**：提示词从"产品分析"→"游戏分析"（爆点、玩法、目标人群）
- **去掉**：缩略图/三视图图片生成
- **新增**：视频文件存储、横竖屏自动检测（ffprobe）

### DA Agent
- **保留**：脚本生成框架、JSON schema 输出
- **改动**：从"创意自由生成 N 段"→"固定 4 段模板"
- **简化**：去掉 style_guide / voice_anchor 等创意字段
- **新增**：orientation 标注，第 2 段"展示截图"指令，第 3 段标记为 FFmpeg 合成段

### VA Agent
- **保留**：img2img 并行生成机制
- **改动**：提示词从"产品+人物合成"→"人物+手机"姿势
- **关键**：第 2 段分镜将用户截图作为参考图，AI 渲染到手机屏幕上
- **新增**：生成"人物玩手机"静态图（用于第 3 段模糊背景）

### VGA Agent
- **保留**：Veo 生成 + 智能裁剪（用于第 1/2/4 段）
- **改动**：第 3 段不走 Veo，改为 CompositorService
- **新增**：CompositorService

### 新增：CompositorService

```python
# backend/services/compositor.py

class CompositorService:
    """处理第 3 段游戏画面合成"""

    async def compose_gameplay_segment(
        playing_phone_image: str,  # VA 生成的人物玩手机图
        gameplay_video: str,       # 用户上传的游戏录屏
        orientation: str,          # "portrait" | "landscape"
        output_path: str
    ) -> str:
        # 1. 高斯模糊 playing_phone_image → blurred_bg
        # 2. 计算游戏视频位置和大小
        #    - portrait: 居中，高度 50%
        #    - landscape: 居中，宽度 ≤ 画面宽度
        # 3. FFmpeg: blurred_bg 静态背景 + gameplay 视频叠加
        # 4. 输出 gameplay_segment.mp4
```

---

## 管线流程

```
DA 编排 4 段脚本 (固定模板)
    ↓
VA 并行生成分镜图:
  - frame_0: 铺垫起始帧 (人物坐着)
  - frame_1: 铺垫结束帧 / 展示手机起始帧
  - frame_2: 展示手机帧 (手机屏幕=用户截图)
  - frame_3: 人物玩手机静态图 (模糊背景素材)
  - frame_4: CTA 起始帧 (人物放下手机)
  - frame_5: CTA 结束帧 (人物微笑)
    ↓
并行生成视频段:
  - Veo: 铺垫段 (frame_0 → frame_1)
  - Veo: 展示手机段 (frame_1 → frame_2)
  - Compositor: 游戏画面段 (frame_3 模糊 + gameplay.mp4)
  - Veo: CTA段 (frame_4 → frame_5)
    ↓
FFmpeg 拼接 4 段 → final.mp4
```

---

## 前端改动

| 现有 | 改为 |
|------|------|
| 物品列 (items) | 游戏列 (games) |
| 物品创建表单 (上传图片+描述) | 游戏创建表单 (上传截图+上传视频+描述) |
| ADA 问卷 (产品特性) | ADA 问卷 (游戏特色/爆点) |
| Dock: 物品槽+人物槽+平台+时长 | Dock: 游戏槽+人物槽 |
| 进度页: 4 阶段通用 | 进度页: 4 阶段，文案微调 |

### 保持不变的部分
- 人物资产系统
- 渲染队列
- i18n 框架（只改文案）
- Job 管理
- SSE 进度推送
- 结果页

---

## 数据模型改动

```python
# models.py

# Item → Game
class GameAssetCreate(BaseModel):
    name: str
    description: str
    orientation: Literal["portrait", "landscape"]
    genre: Optional[str] = None

class GameAssetData(BaseModel):
    type: Literal["games"] = "games"
    name: str
    orientation: str
    genre: str
    description: str
    features: str          # ADA 问卷后整理
    intro_line: Optional[str] = None
    screenshot_path: str
    gameplay_path: str
```

---

## 实施优先级

1. 数据模型 & API 端点改造（Game 替代 Item）
2. ADA 提示词重写（游戏问卷）
3. DA 固定模板脚本生成
4. VA 提示词改造（人物+手机姿势 + 截图渲染）
5. CompositorService（FFmpeg 游戏画面合成）
6. VGA 管线适配（第 3 段走 Compositor）
7. 前端改造（游戏列 + 表单 + Dock）
8. i18n 文案更新
9. 集成测试 & 调优

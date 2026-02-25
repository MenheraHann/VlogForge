# VlogForge 开发进度

> 最后更新：2026-02-25（后端 + 前端全量完成）

## 项目概述

参加 **Gemini Live Agent Challenge**（Creative Storyteller 赛道），做一个 **AI Vlog 带货视频生成器**。
用户定制物品、人物、场景三大素材，AI 自动组合生成真人 vlog 风格的带货短视频。

## 核心架构（4 Agent）

| 角色 | 代号 | 阶段 | 核心 API | 状态 |
|------|------|------|----------|------|
| 素材设计师 | ADA | 素材创建 | Gemini 文本 + Nano Banana | **已完成** |
| 创意总监 | DA | 视频生成 | Gemini 文本 (self_check) | **已完成** |
| 美术指导 | VA | 视频生成 | Nano Banana (链式 img2img) | **已完成** |
| 剪辑师 | VGA | 视频生成 | Veo 3.1 (首尾帧) | **已完成** |

## 两大工作流

### 素材创建

```
用户添加物品/人物/场景 → ADA（通过 asset_type 切换模式）→ 素材档案存入素材库
```

### 视频生成

```
用户选择素材 + 参数 → DA(脚本+自检) → VA(链式图生图) → VGA(首尾帧视频) → FFmpeg(拼接) → 最终视频
```

## 已完成

### 基础架构 (D1-D7)

- [x] D1：项目骨架（目录结构、FastAPI、config、models、job_manager、storage）
- [x] D2：脚本生成能力（原 TA，现已合入 DA）
- [x] D3：DA Agent 骨架（asyncio 后台流水线 + job 进度管理）
- [x] D4：基础前端
- [x] D5-D7：架构精简（ADA 合并、TA→DA、QA 移除、VA 链式图生图方案确定）

### 配置 + 数据模型

- [x] `backend/config.py` — 模型名称（TEXT_MODEL / IMAGE_GEN_MODEL / VIDEO_GEN_MODEL）、存储路径、参数映射、self_check 阈值
- [x] `backend/models.py` — 移除 QA_REVIEWING；新增 AssetType / ItemAsset / ModelAsset / SceneAsset / SelfCheck / VideoGenerateRequest

### 工具层

- [x] `backend/tools/image_gen.py` — Nano Banana 封装（text_to_image / image_to_image / interleaved_output / save_image）
- [x] `backend/tools/video_gen.py` — Veo 3.1 封装（generate_video_segment 首尾帧 / generate_video_from_first_frame）
- [x] `backend/tools/ffmpeg_tools.py` — FFmpeg 封装（stitch_segments / trim_overlaps / get_video_duration）

### 提示词

- [x] `backend/prompts/da_prompts.py` — DA 脚本生成 prompt（含 self_check、素材档案模式 + 旧版兼容模式）
- [x] `backend/prompts/ada_prompts.py` — ADA 三套 prompt（物品/人物/场景模式，含系统提示 + 图片生成提示 + JSON Schema）

### Agent 层

- [x] `backend/agents/ada_agent.py` — 素材设计师（create_item_asset / create_model_asset / create_scene_asset）
- [x] `backend/agents/da_agent.py` — 创意总监（吸收 TA、self_check 校验、v2 素材模式、编排 VA/VGA/FFmpeg）
- [x] `backend/agents/va_agent.py` — 美术指导（链式 img2img，generate_storyboard）
- [x] `backend/agents/vga_agent.py` — 剪辑师（并行 Veo 视频生成，generate_segments）

### 服务层

- [x] `backend/services/asset_manager.py` — 素材库 CRUD（内存存储、自增 ID、选型管理）
- [x] `backend/services/job_manager.py` — 任务管理（创建于 D1）

### API 端点

- [x] `backend/main.py` — 13 个 API 端点：
  - 健康检查：`GET /health`
  - 素材 CRUD：`POST /api/assets/item|model|scene`、`POST .../select`、`GET /api/assets`、`GET /api/assets/{id}`、`DELETE /api/assets/{id}`
  - 视频生成：`POST /api/generate`（旧版）、`POST /api/generate/v2`（素材模式）
  - 进度查询：`GET /api/status/{id}`、`GET /api/stream/{id}`（SSE）、`GET /api/download/{id}`
  - 静态文件：`/assets/` + `/artifacts/` + `/`（前端）

### 前端

- [x] `frontend/index.html` — v4 SPA 结构（导航 + 素材库 + 生成视频 + 进度 + 结果 5 个视图）
- [x] `frontend/styles.css` — 暗色 glassmorphic 主题（紫-青渐变、卡片、模态框、标签页、选择器）
- [x] `frontend/app.js` — 完整交互逻辑（素材 CRUD + 方案选择 + v2 生成 + SSE 进度 + Toast 通知）

### 废弃代码

- [x] `backend/agents/ta_agent.py` — 标记废弃（已合入 DA）
- [x] `backend/agents/qa_agent.py` — 标记废弃（已移除）
- [x] `backend/prompts/ta_system.py` — 标记废弃（迁移至 da_prompts.py）

## 待开发

### 阶段五：部署 + 打磨

- [ ] Google Cloud Run 部署配置（Dockerfile + cloudbuild.yaml）
- [ ] GCS 文件存储接入（替代本地 assets/artifacts 目录）
- [ ] 真实 API Key 联调测试
- [ ] 演示视频录制
- [ ] 提交参赛

## 技术选型

- Agent 框架：Google ADK (Python)
- 文本生成：Gemini 2.5 Flash
- 图片生成：Gemini 原生图片生成（Nano Banana, `gemini-2.0-flash-exp`）
- 视频生成：Veo 3.1 API（首尾帧, `veo-3.1-generate-001`）
- 视频拼接：FFmpeg
- 后端：FastAPI
- 前端：HTML/CSS/JS（原生 SPA）
- 部署：Google Cloud Run + Cloud Storage

## 参考文档

- `PRD.md` — 产品需求（用户流程 + 素材库 + 数据结构）
- `Team_Structure.md` — Agent 架构（角色 + 协作流程 + 代码映射）
- `decisions.md` — 技术决策记录（D2-D7）
- `Rule.md` — 比赛规则

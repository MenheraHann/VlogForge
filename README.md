# VlogForge — AI Vlog Product Video Generator

[English](#english) | [中文](#中文)

---

<a id="english"></a>

> **Gemini Live Agent Challenge Submission**
> Transform a product photo + one sentence into a polished, narrated vertical video ad — fully automated by 4 Gemini-powered AI agents.

## Demo

https://youtu.be/YOUR_DEMO_VIDEO

## What is VlogForge?

VlogForge is a fully automated AI video production pipeline. Upload a product photo, describe it in one sentence, and VlogForge's 4-agent team writes the script, draws the storyboard, generates each video segment with lip-synced narration, and stitches them into a seamless 18–60s vertical video — no editing required.

## Architecture

```
User uploads product photo + one-sentence description
                    │
            ┌───────▼───────┐
            │  ADA — Asset   │  Gemini 2.5 Flash + Nano Banana Pro
            │  Designer      │  Analyzes product, generates profiles
            └───────┬───────┘  via smart questionnaires, creates
                    │          reference images
            ┌───────▼───────┐
            │  DA — Creative │  Gemini 2.5 Flash
            │  Director      │  Writes script with self-check loop,
            └───────┬───────┘  orchestrates the full pipeline
                    │
            ┌───────▼───────┐
            │  VA — Visual   │  Nano Banana (img2img)
            │  Director      │  Generates N+1 storyboard keyframes
            └───────┬───────┘  in parallel from reference images
                    │
            ┌───────▼───────┐
            │  VGA — Video   │  Veo 3.1 Preview
            │  Editor        │  Generates video segments using
            └───────┬───────┘  first/last frame mode + smart trim
                    │
            ┌───────▼───────┐
            │  FFmpeg        │  Overlap removal + re-encode
            │  Stitcher      │  + concat → final.mp4
            └───────┬───────┘
                    │
                    ▼
            🎬 Final Video (18–60s, 9:16 vertical, narrated)
```

**Pipeline design:** Sequential between stages (each depends on previous output), **fully parallel within stages** — all storyboard frames and all video segments are generated concurrently with semaphore-controlled concurrency (`asyncio.Semaphore(3)`), achieving ~3x speedup.

## Key Technical Innovations

**Self-Check Loop** — DA scores its own script across 4 dimensions (person accuracy, product fidelity, scene context, overall quality). If any score falls below the threshold, it automatically re-generates with targeted feedback — genuine agentic self-correction.

**Frame Chain Continuity** — Adjacent video segments share a boundary frame: Segment N's end frame is identical to Segment N+1's start frame. This is validated at the prompt level with automatic retry, ensuring seamless visual transitions.

**Smart Trim** — Veo 3.1 sometimes "drifts" past the target end frame. VlogForge extracts frames from the video tail, computes MSE against the target image, and trims at the best-match point — solving a common Veo pain point without re-generation.

**Voice Anchor** — DA generates a detailed voice profile (gender, age, tone, pace, accent) prepended to every Veo prompt, ensuring consistent narration voice across independently generated segments.

**Parallel-but-Consistent Storyboards** — VA generates all frames independently from the same reference images (not chained), anchored by a shared style guide. This avoids cumulative appearance drift while tripling throughput.

## Quick Start

### Prerequisites

- Python 3.11+
- FFmpeg (`brew install ffmpeg` or `apt install ffmpeg`)
- Google Cloud project with Vertex AI enabled (required for Veo 3.1)

### Setup

```bash
git clone https://github.com/MenheraHann/VlogForge.git
cd VlogForge

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

- `GEMINI_API_KEY` — Gemini API key (fallback if no Vertex AI)
- `GOOGLE_CLOUD_PROJECT` — GCP project ID (enables Vertex AI mode, **required for Veo 3.1**)
- `GOOGLE_CLOUD_LOCATION` — Vertex AI region (default: `us-central1`)
- `GCS_BUCKET_NAME` — GCS bucket for persistent storage (empty = local only)
- `VLOGFORGE_API_KEY` — API authentication key (empty = no auth)
- `PORT` — Server port (default: `8000`)

*At least one of `GEMINI_API_KEY` or `GOOGLE_CLOUD_PROJECT` is required.*

### Run

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 in your browser.

### Usage Walkthrough

1. **Upload a product photo** — drag & drop or click to upload
2. **Answer the smart questionnaire** — ADA generates A/B options for product details, just pick the right ones
3. **Confirm the product profile** — ADA generates thumbnail and three-view reference images
4. **(Optional) Create a model persona** — describe the person or let VlogForge auto-generate one
5. **Select duration and generate** — pick 18s–60s, click generate, and watch the pipeline work in real-time via SSE progress streaming
6. **Download** — the final video is ready to post

## Cloud Run Deployment (Optional)

VlogForge supports deployment to Cloud Run with GCS-backed persistent storage.

### 1. Create GCS Bucket

```bash
gsutil mb -l us-central1 gs://your-vlogforge-bucket
```

### 2. Build and Push Docker Image

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/vlogforge --dockerfile deploy/Dockerfile
```

### 3. Deploy to Cloud Run

```bash
gcloud run deploy vlogforge \
  --image gcr.io/YOUR_PROJECT/vlogforge \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --timeout 900 \
  --max-instances 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GCS_BUCKET_NAME=your-vlogforge-bucket,VLOGFORGE_API_KEY=your-secret-key" \
  --allow-unauthenticated
```

> **Note:** `--max-instances 1` is required to avoid in-memory state inconsistency between instances.

## API Endpoints

**Health** — `GET /health`

**Assets**
- `POST /api/assets/item/analyze` — Analyze product (step 1)
- `POST /api/assets/item/{id}/confirm` — Confirm product profile (step 2)
- `POST /api/assets/model` — Create model persona
- `POST /api/assets/model/{id}/select` — Confirm model look
- `POST /api/assets/model/{id}/regenerate` — Regenerate portrait
- `POST /api/assets/model/{id}/adjust` — Adjust with feedback
- `GET /api/assets` — List all assets
- `DELETE /api/assets/{id}` — Delete asset

**Video Generation**
- `POST /api/generate/v2` — Create video job
- `GET /api/jobs` — List all jobs
- `POST /api/jobs/{id}/cancel` — Cancel job
- `GET /api/stream/{id}` — SSE real-time progress
- `GET /api/download/{id}` — Download final video

**Quick Start**
- `POST /api/quickstart/parse` — One-sentence decomposition
- `POST /api/quickstart/create` — One-sentence full creation

**Authentication** — When `VLOGFORGE_API_KEY` is set, all `/api/*` endpoints require `Authorization: Bearer <key>`. Public endpoints (`/health`, `/assets/*`, `/artifacts/*`, frontend) do not require auth.

## Tech Stack

- **Backend:** Python 3.12, FastAPI, asyncio, Uvicorn
- **AI Models:** Gemini 2.5 Flash (text), Nano Banana / Nano Banana Pro (image), Veo 3.1 Preview (video) — all via Vertex AI
- **Video Processing:** FFmpeg (smart trimming, overlap removal, stitching)
- **Storage:** Local filesystem + optional Google Cloud Storage (dual-write pattern)
- **Deployment:** Docker + Cloud Run (optional)
- **Frontend:** Vanilla HTML/CSS/JS SPA with i18n support (6 languages: EN, ZH, JA, KO, ES, PT)

## License

This project was built for the Gemini Live Agent Challenge.

---

<a id="中文"></a>

# VlogForge — AI 短视频带货生成器

> **Gemini Live Agent Challenge 参赛作品**
> 上传一张产品图 + 一句话描述，4 个 Gemini AI 智能体全自动生成带口播的竖屏带货视频。

## 演示视频

https://youtu.be/YOUR_DEMO_VIDEO

## VlogForge 是什么？

VlogForge 是一条全自动 AI 视频生产流水线。上传产品图片，用一句话描述产品，VlogForge 的 4 个 AI 智能体团队会自动完成：编写脚本、绘制分镜、生成带口播的视频片段、拼接成完整视频——全程无需人工剪辑，输出 18–60 秒的竖屏带货短视频。

## 架构

```
用户上传产品图片 + 一句话描述
                    │
            ┌───────▼───────┐
            │  ADA — 素材    │  Gemini 2.5 Flash + Nano Banana Pro
            │  设计师        │  分析产品、生成结构化档案、
            └───────┬───────┘  通过智能问卷确认、生成参考图
                    │
            ┌───────▼───────┐
            │  DA — 创意     │  Gemini 2.5 Flash
            │  总监          │  编写脚本 + 自检循环，
            └───────┬───────┘  编排整条流水线
                    │
            ┌───────▼───────┐
            │  VA — 视觉     │  Nano Banana (图生图)
            │  总监          │  并行生成 N+1 张分镜关键帧
            └───────┬───────┘
                    │
            ┌───────▼───────┐
            │  VGA — 视频    │  Veo 3.1 Preview
            │  剪辑师        │  首尾帧模式生成视频片段
            └───────┬───────┘  + 智能裁剪
                    │
            ┌───────▼───────┐
            │  FFmpeg        │  去重叠 + 统一编码
            │  拼接器        │  + 合并 → final.mp4
            └───────┬───────┘
                    │
                    ▼
            🎬 成品视频 (18–60秒, 9:16 竖屏, 带口播)
```

**流水线设计：** 阶段之间严格串行（每阶段依赖上一阶段的输出），**阶段内部完全并行**——所有分镜帧和所有视频片段通过信号量控制并发（`asyncio.Semaphore(3)`）同时生成，速度提升约 3 倍。

## 核心技术亮点

**自检循环** — DA 生成脚本后会对自己的输出进行 4 个维度评分（人物准确度、产品还原度、场景匹配度、整体质量）。任一维度低于阈值，自动携带反馈重新生成——真正的智能体自我纠错。

**帧链连续性** — 相邻视频片段共享一个边界帧：片段 N 的结束帧与片段 N+1 的起始帧完全一致。在 prompt 层面进行校验并自动重试，确保视觉过渡无缝衔接。

**智能裁剪** — Veo 3.1 有时会在目标结束帧之后继续生成多余内容。VlogForge 从视频尾部提取帧，与目标图片计算 MSE，在最佳匹配点精准裁剪——无需重新生成即可解决 Veo 的尾帧漂移问题。

**声音锚定** — DA 生成详细的声音描述（性别、年龄、语调、语速、风格），附加到每个 Veo 片段的 prompt 中，确保独立生成的各片段之间口播声音一致。

**并行但一致的分镜生成** — VA 从相同的参考图片独立并行生成所有帧（非链式串行），通过共享风格指南锚定一致性。避免了链式图生图的累积漂移问题，同时吞吐量提升 3 倍。

## 快速开始

### 前置要求

- Python 3.11+
- FFmpeg（`brew install ffmpeg` 或 `apt install ffmpeg`）
- Google Cloud 项目并启用 Vertex AI（Veo 3.1 必需）

### 安装

```bash
git clone https://github.com/MenheraHann/VlogForge.git
cd VlogForge

python -m venv venv
source venv/bin/activate

pip install -r requirements.txt

cp .env.example .env
# 编辑 .env 填入你的 API 密钥
```

### 环境变量

- `GEMINI_API_KEY` — Gemini API 密钥（无 Vertex AI 时的降级方案）
- `GOOGLE_CLOUD_PROJECT` — GCP 项目 ID（启用 Vertex AI 模式，**Veo 3.1 必需**）
- `GOOGLE_CLOUD_LOCATION` — Vertex AI 区域（默认：`us-central1`）
- `GCS_BUCKET_NAME` — GCS 存储桶名称，用于持久化存储（留空 = 仅本地存储）
- `VLOGFORGE_API_KEY` — API 认证密钥（留空 = 无需认证）
- `PORT` — 服务端口（默认：`8000`）

*`GEMINI_API_KEY` 和 `GOOGLE_CLOUD_PROJECT` 至少需要配置一个。*

### 启动

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

浏览器打开 http://localhost:8000 即可使用。

### 使用流程

1. **上传产品图片** — 拖拽或点击上传
2. **回答智能问卷** — ADA 生成 A/B 选项供你选择产品细节
3. **确认产品档案** — ADA 生成缩略图和三视图参考图
4. **（可选）创建人物形象** — 描述人物或让 VlogForge 自动生成
5. **选择时长并生成** — 选择 18s–60s，点击生成，通过 SSE 实时查看流水线进度
6. **下载** — 成品视频可直接发布

## Cloud Run 部署（可选）

VlogForge 支持部署到 Cloud Run，使用 GCS 进行持久化存储。

### 1. 创建 GCS 存储桶

```bash
gsutil mb -l us-central1 gs://your-vlogforge-bucket
```

### 2. 构建并推送 Docker 镜像

```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT/vlogforge --dockerfile deploy/Dockerfile
```

### 3. 部署到 Cloud Run

```bash
gcloud run deploy vlogforge \
  --image gcr.io/YOUR_PROJECT/vlogforge \
  --platform managed \
  --region us-central1 \
  --memory 2Gi \
  --timeout 900 \
  --max-instances 1 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=YOUR_PROJECT,GCS_BUCKET_NAME=your-vlogforge-bucket,VLOGFORGE_API_KEY=your-secret-key" \
  --allow-unauthenticated
```

> **注意：** `--max-instances 1` 是必需的，避免多实例之间内存状态不一致。

## API 端点

**健康检查** — `GET /health`

**素材管理**
- `POST /api/assets/item/analyze` — 分析产品（第 1 步）
- `POST /api/assets/item/{id}/confirm` — 确认产品档案（第 2 步）
- `POST /api/assets/model` — 创建人物形象
- `POST /api/assets/model/{id}/select` — 确认人物外观
- `POST /api/assets/model/{id}/regenerate` — 重新生成人物肖像
- `POST /api/assets/model/{id}/adjust` — 根据反馈调整
- `GET /api/assets` — 列出所有素材
- `DELETE /api/assets/{id}` — 删除素材

**视频生成**
- `POST /api/generate/v2` — 创建视频任务
- `GET /api/jobs` — 列出所有任务
- `POST /api/jobs/{id}/cancel` — 取消任务
- `GET /api/stream/{id}` — SSE 实时进度推送
- `GET /api/download/{id}` — 下载成品视频

**快速创建**
- `POST /api/quickstart/parse` — 一句话拆解
- `POST /api/quickstart/create` — 一句话全自动创建

**认证** — 设置 `VLOGFORGE_API_KEY` 后，所有 `/api/*` 端点需要 `Authorization: Bearer <key>`。公开端点（`/health`、`/assets/*`、`/artifacts/*`、前端页面）无需认证。

## 技术栈

- **后端：** Python 3.12、FastAPI、asyncio、Uvicorn
- **AI 模型：** Gemini 2.5 Flash（文本）、Nano Banana / Nano Banana Pro（图片）、Veo 3.1 Preview（视频）—— 全部通过 Vertex AI 调用
- **视频处理：** FFmpeg（智能裁剪、重叠去除、拼接）
- **存储：** 本地文件系统 + 可选 Google Cloud Storage（双写模式）
- **部署：** Docker + Cloud Run（可选）
- **前端：** 原生 HTML/CSS/JS 单页应用，支持 6 种语言（中文、英文、日文、韩文、西班牙文、葡萄牙文）

## 许可

本项目为 Gemini Live Agent Challenge 参赛作品。

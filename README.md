# VlogForge — AI Vlog Product Video Generator

VlogForge is a fully automated AI video production pipeline for product promotion videos. Built for the **Gemini Live Agent Challenge**, it orchestrates four specialized AI agents to transform product photos and model descriptions into polished, narrated video ads.

## Architecture

**4-Agent Pipeline:**

```
ADA (Asset Designer) → DA (Creative Director) → VA (Visual Director) → VGA (Video Generation Agent)
```

| Agent | Role | AI Model |
|-------|------|----------|
| **ADA** | Analyzes products, creates item profiles with thumbnail/three-view images, generates model personas with portrait images | Gemini 2.5 Flash (text) + Nano Banana (image) |
| **DA** | Writes scripts with self-check validation, orchestrates the full pipeline | Gemini 2.5 Flash |
| **VA** | Generates N+1 storyboard frames in parallel using chained img2img | Nano Banana |
| **VGA** | Generates video segments using Veo 3.1 first/last frame mode in parallel, with smart trim | Veo 3.1 Preview |
| **FFmpeg** | Stitches segments into the final video with overlap removal | Local FFmpeg |

**Key Features:**
- Two-step asset creation with intelligent questionnaires
- Frame chain continuity validation across segments
- Parallel storyboard and video generation with semaphore-controlled concurrency
- FIFO job queue with real-time SSE progress streaming
- Safety filter detection with user-friendly error messages
- Age enforcement (minimum 18) for model personas

## Quick Start (Local Development)

### Prerequisites

- Python 3.11+
- FFmpeg (`brew install ffmpeg` or `apt install ffmpeg`)
- Google Cloud project with Vertex AI enabled (for Veo 3.1 video generation)

### Setup

```bash
# Clone and enter project
cd Gemini_Live_Agent_Challenge

# Create virtual environment
python -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `GEMINI_API_KEY` | Yes* | Gemini API key (fallback if no Vertex AI) |
| `GOOGLE_CLOUD_PROJECT` | Yes* | GCP project ID (enables Vertex AI mode) |
| `GOOGLE_CLOUD_LOCATION` | No | Vertex AI region (default: `us-central1`) |
| `GCS_BUCKET_NAME` | No | GCS bucket for persistent storage (empty = local only) |
| `VLOGFORGE_API_KEY` | No | API authentication key (empty = no auth) |
| `PORT` | No | Server port (default: `8000`) |
| `CORS_ORIGINS` | No | Allowed CORS origins (default: `*`) |

*At least one of `GEMINI_API_KEY` or `GOOGLE_CLOUD_PROJECT` is required.

### Run

```bash
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

Open http://localhost:8000 in your browser.

## Cloud Run Deployment

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

### Health
- `GET /health` — Health check (no auth required)

### Assets
- `POST /api/assets/item/analyze` — Analyze product (step 1)
- `POST /api/assets/item/{id}/confirm` — Confirm product profile (step 2)
- `POST /api/assets/model` — Create model persona (async)
- `POST /api/assets/model/{id}/select` — Confirm model look
- `POST /api/assets/model/{id}/regenerate` — Regenerate model portrait
- `POST /api/assets/model/{id}/adjust` — Adjust model with feedback
- `POST /api/assets/{id}/regenerate-image` — Regenerate single image
- `GET /api/assets` — List all assets
- `GET /api/assets/{id}` — Get asset details
- `PUT /api/assets/{id}` — Update asset fields
- `DELETE /api/assets/{id}` — Delete asset

### Video Generation
- `POST /api/generate/v2` — Create video job (asset-based)
- `GET /api/jobs` — List all jobs
- `POST /api/jobs/{id}/cancel` — Cancel job
- `GET /api/status/{id}` — Job progress
- `GET /api/stream/{id}` — SSE real-time progress
- `GET /api/download/{id}` — Download final video

### Quick Start
- `POST /api/quickstart/parse` — One-sentence decomposition
- `POST /api/quickstart/create` — One-sentence full creation

### Authentication

When `VLOGFORGE_API_KEY` is set, all `/api/*` endpoints require:

```
Authorization: Bearer <your-api-key>
```

Public endpoints (`/health`, `/assets/*`, `/artifacts/*`, frontend static files) do not require authentication. Note: `/assets/*` and `/artifacts/*` serve generated media files needed by the frontend; path traversal is blocked server-side.

## Tech Stack

- **Backend:** FastAPI + Uvicorn
- **AI:** Google Gemini 2.5 Flash, Nano Banana, Veo 3.1 (via Vertex AI)
- **Video:** FFmpeg (smart trim + stitching)
- **Storage:** Local filesystem + optional Google Cloud Storage
- **Frontend:** Vanilla HTML/CSS/JS SPA with i18n (6 languages)

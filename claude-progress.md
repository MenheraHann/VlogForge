# VlogForge 开发进度

## 项目概述

参加 **Gemini Live Agent Challenge**（Creative Storyteller 赛道），做一个 **AI Vlog 带货视频生成器**。
用户输入产品信息，Agent 系统自动生成真人 vlog 风格的短视频广告。

## 核心工作流

```
用户输入 6 项信息 → DA 编排 → TA 写脚本 → VA 出分镜图(Nano Banana) → VGA 生成视频(Veo 3.1 首尾帧) → QA 审核 → FFmpeg 拼接 → 输出最终视频
```

关键技术点：
- 分镜图形成链条：Frame A→B = 视频1，Frame B→C = 视频2（相邻视频共享一帧）
- 拼接时裁掉重复帧保证流畅
- 部分分镜需要植入用户的产品参考图

## 当前完成状态（D1 已完成）

- [x] 项目目录结构
- [x] requirements.txt / .env.example / .gitignore / Dockerfile
- [x] FastAPI 基础框架（main.py + config.py + models.py）
- [x] 任务管理器（job_manager.py）
- [x] 存储工具（storage.py）
- [x] 所有 Agent 和 tools 的占位文件
- [ ] 依赖安装（需在 Mac 上执行）
- [ ] GenAI SDK 联通验证

## 接下来要做的事

### 立即执行：环境搭建（Mac）

```bash
cd /你的项目路径/Gemini_Live_Agent_Challenge

# 1. 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 FFmpeg
brew install ffmpeg

# 4. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 GEMINI_API_KEY

# 5. 验证 FastAPI 能跑起来
python -m uvicorn backend.main:app --reload
# 访问 http://localhost:8000/health 应返回 {"status":"ok","service":"VlogForge"}

# 6. 验证 GenAI SDK
python -c "from google import genai; print('GenAI SDK OK')"
```

### D2：实现 TA Agent（脚本策划）

**目标**：输入产品信息 → 输出完整的 vlog 脚本（JSON 格式）

需要完成的文件：
1. `backend/prompts/ta_system.py` — TA 的系统提示词，要求：
   - 根据产品类型、使用方式、卖点生成 vlog 脚本
   - 输出 N 个分段，每段包含：旁白、动作描述、首帧提示词、尾帧提示词、Veo 描述词
   - 首帧N+1 必须和尾帧N 一致（链式衔接）
   - 标记哪些帧需要植入产品
   - 输出风格指南（人物外貌、场景、光线统一描述）
   - 输出为 JSON 格式，匹配 ScriptOutput 模型

2. `backend/agents/ta_agent.py` — TA Agent 实现：
   - 调用 Gemini API 生成文本
   - 解析 JSON 为 ScriptOutput
   - 错误处理（JSON 解析失败时重试）

### D3：实现 DA Agent 骨架

**目标**：接收用户输入 → 调度 TA → 返回脚本

需要完成的文件：
1. `backend/prompts/da_system.py` — DA 的系统提示词
2. `backend/agents/da_agent.py` — DA 编排逻辑：
   - 接收 job_data
   - 调用 TA 生成脚本
   - 更新 job 状态和进度
   - 后续阶段再加 VA、VGA、QA 调度

3. `backend/main.py` — 在 /api/generate 端点中启动 DA 流水线（异步）

### D4：基础前端

**目标**：用户可以通过网页提交输入并看到生成的脚本

需要完成的文件：
1. `frontend/index.html` — 输入表单（6 项）+ 输出展示区
2. `frontend/styles.css` — 样式
3. `frontend/app.js` — 前端逻辑（提交表单、轮询进度、展示脚本）

## 排期总览（18 天 + 2 天容错）

| 阶段 | 天数 | 内容 | 验收点 |
|------|------|------|--------|
| 一 | D1-D4 | 基础 + TA + DA + 前端 | 任意产品 → 完整脚本 |
| 二 | D5-D8 | VA 图片生成 + 产品植入 | 视觉连贯的分镜图组 |
| 三 | D9-D13 | VGA 视频 + FFmpeg + QA | 输入 → 完整视频 |
| 四 | D14-D18 | 部署 + 打磨 + 演示视频 | 提交参赛 |
| 容错 | D19-D20 | 修 bug、补细节 | — |

## 技术选型

- Agent 框架：Google ADK (Python)
- 文本生成：Gemini 2.5 Flash
- 图片生成：Gemini 原生图片生成（Nano Banana）
- 视频生成：Veo 3.1 API（首尾帧）
- 视频拼接：FFmpeg
- 后端：FastAPI
- 前端：HTML/CSS/JS
- 部署：Google Cloud Run + Cloud Storage

## 完整方案

详见 `Structure.md`（架构）和 `流程.md`（用户工作流）

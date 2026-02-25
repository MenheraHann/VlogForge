# GenMedia 综合参考 & 比赛 Resources 总结

> 学习来源：Gemini Live Agent Challenge 官方 Resources 页面
> 整理时间：2026-02-25

---

## 一、官方 Resources 分类总结

比赛在 Devpost 上提供了一批学习资料，**不是必选项**，是帮助参赛者上手的工具箱。

### 比赛硬性要求（只有这 4 条）

1. 使用 **Gemini 模型**
2. 使用 **GenAI SDK** 或 **ADK** 构建 Agent
3. 至少用 **一项 Google Cloud 服务**
4. Agent **部署在 Google Cloud** 上

---

## 二、Resources 全部清单

### GenMedia 工具类

| 资源 | 链接 | 与 VlogForge 的关系 |
|------|------|-------------------|
| Live API notebooks/apps | [GitHub](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/multimodal-live-api) | 低相关（我们不用 Live API） |
| **图片/视频生成 notebooks** | [GitHub](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision) | **高相关** — VA 和 VGA 实现参考 |
| Computer Use notebooks | [GitHub](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/gemini/computer-use) | 不相关（UI Navigator 赛道） |
| Language Learning App | [GitHub](https://github.com/ZackAkil/immersive-language-learning-with-live-api) | 不相关 |
| **MCP GenMedia 工具** | [GitHub](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio/tree/main/experiments/mcp-genmedia) | **中等相关** — 可参考 API 调用模式 |

### ADK 双向流相关

| 资源 | 链接 | 与 VlogForge 的关系 |
|------|------|-------------------|
| ADK Bidi-streaming 视觉指南 | [Medium](https://medium.com/google-cloud/adk-bidi-streaming-a-visual-guide-to-real-time-multimodal-ai-agent-development-62dd08c81399) | 低相关（实时流不是我们的重点） |
| ADK Bidi-streaming 5分钟入门 | [YouTube](https://www.youtube.com/watch?v=vLUkAGeLR1k) | 低相关 |
| ADK Bidi-streaming 开发指南 | [文档](https://google.github.io/adk-docs/streaming/dev-guide/part1/) | 低相关 |
| Shopper's Concierge II Demo | [YouTube](https://www.youtube.com/watch?v=Hwx94smxT_0) | 低相关 |

### 多模态 Agent 教程（Codelabs）

| 资源 | 链接 | 与 VlogForge 的关系 |
|------|------|-------------------|
| Avatar Generation with GenAI SDK | [Codelab](https://codelabs.developers.google.com/way-back-home-level-0/instructions#0) | 中等相关 — 图片生成基础 |
| Multimodal Coordination | [Codelab](https://codelabs.developers.google.com/way-back-home-level-1/instructions#0) | 中等相关 — 多模态协调 |
| Multimodal, Graph RAG & Memory Bank | [Codelab](https://codelabs.developers.google.com/codelabs/survivor-network/instructions#0) | 低相关 |
| Live Bidirectional Streaming Agent | [Codelab](https://codelabs.developers.google.com/way-back-home-level-3/instructions#0) | 低相关 |
| Real-time Monitoring Agent | [Codelab](https://codelabs.developers.google.com/way-back-home-level-4/instructions#0) | 低相关 |

### 灵感参考

| 资源 | 链接 | 与 VlogForge 的关系 |
|------|------|-------------------|
| **Nano Banana Pro 营销广告 Demo** | [LinkedIn](https://www.linkedin.com/posts/katiemn_nanobananapro-googlecloud-vertexai-activity-7397313402643181568-2hlW) | **高相关** — 和我们的思路极其相似 |
| ADK Bidi-streaming Demo 源码 | [GitHub](https://github.com/google/adk-samples/tree/main/python/agents/bidi-demo) | 低相关 |
| **GenMedia + Live API 示例应用** | [GitHub](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision/sample-apps/genmedia-live) | **高相关** — 完整的 GenMedia 调用模式 |

### 其他

| 资源 | 链接 | 说明 |
|------|------|------|
| **Google Cloud Credits 申请** | [表单](https://forms.gle/rKNPXA1o6XADvQGb7) | **必须申请** — 免费云额度 |
| Google Developer Groups (GDGs) | [社区](https://developers.google.com/community) | 加入可获加分 |

---

## 三、GenMedia Live 示例应用架构

这个示例应用展示了如何把图片/视频生成集成到 Gemini Live API session 中，架构值得参考：

```
用户 ←→ Gemini Live API (gemini-live-2.5-flash-native-audio)
              │
              ├→ function_call: generate_image
              │     └→ Nano Banana Pro (gemini-3-pro-image-preview)
              │        location: "global"
              │
              ├→ function_call: generate_video
              │     └→ Veo 3.1 (veo-3.1-generate-001)
              │        location: "global"
              │
              ├→ function_call: extract_frame
              ├→ function_call: combine_videos
              └→ function_call: view_generated_image
```

**关键设计模式：**
1. Live API 作为编排中心，通过 function calling 调度图片/视频生成
2. 图片和视频生成用**独立的 client**（location="global"）
3. 生成结果通过 `FunctionResponse` 返回给 Live session
4. 生成的图片同时作为视觉上下文反馈给 Live session

**VlogForge 的区别：**
- 我们不用 Live API（不是实时交互场景）
- 我们的编排由 DA Agent 完成，不是 Live session
- 但图片/视频的 API 调用方式完全一致

---

## 四、MCP GenMedia 工具概览

官方提供的 Go 语言 MCP Server，封装了所有 GenMedia API。虽然是 Go 写的，但 API 模式和 Python SDK 一致，可以作为参考。

| MCP Server | 工具 | 对应 Python 调用 |
|------------|------|-----------------|
| mcp-gemini-go | `gemini_image_generation` | `client.models.generate_content()` |
| mcp-imagen-go | `imagen_t2i` | `client.models.generate_images()` |
| mcp-veo-go | `veo_t2v` / `veo_i2v` | `client.models.generate_videos()` |
| mcp-gemini-go | `gemini_audio_tts` | Gemini TTS |
| mcp-chirp3-go | `chirp_tts` | Chirp3-HD TTS |
| mcp-lyria-go | `lyria_generate_music` | Lyria 音乐生成 |
| mcp-avtool-go | 多个 | FFmpeg 音视频合成 |

---

## 五、关键发现 & 对 VlogForge 的影响

### 发现 1：Veo 3 自带语音生成

`generate_audio=True` 时，Veo 3+ 会根据 prompt 中的对话内容自动生成配音。这意味着：
- PRD 中的 MA（音频师）角色可以**简化甚至去掉**
- 旁白直接由 Veo 在生成视频时处理
- 不需要单独的 TTS 步骤

### 发现 2：location 很重要

| 服务 | location |
|------|----------|
| Gemini 文本生成 | `us-central1`（或其他标准区域） |
| Nano Banana 图片生成 | `global` |
| Veo 视频生成 | `global` |

→ VlogForge 需要用**不同 location 的 client** 调用不同服务

### 发现 3：Veo 参考图可保持角色一致性

`reference_images` + `reference_type="asset"` 可以让不同视频片段中的人物外貌保持一致。这对 VlogForge 的「vlog 风格」非常重要——整个视频中的人物应该看起来是同一个人。

### 发现 4：异步轮询是标准模式

视频生成是长耗时操作（可能几分钟），必须用异步轮询模式。VlogForge 需要：
- 前端显示实时进度
- 后端用 SSE 推送生成状态
- 各视频片段可以并行生成

---

## 六、技术选型确认

基于以上调研，VlogForge 的技术选型：

| 功能 | 选择 | 理由 |
|------|------|------|
| 文本/脚本生成 | Gemini 2.5 Flash | 速度快，成本低，够用 |
| 图片生成 | Nano Banana (`gemini-2.5-flash-image`) | 支持参考图、多轮编辑、文字+图片混合输出 |
| 视频生成 | Veo 3.1 (`veo-3.1-generate-001`) | 首尾帧功能、自带语音、支持 9:16 |
| Agent 框架 | Google ADK | 比赛要求 |
| 后端 | FastAPI | 已搭建完成 |
| 部署 | Google Cloud Run | 比赛要求 |

---

## 七、详细 API 文档

- 图片生成详细用法 → [api-nano-banana.md](./api-nano-banana.md)
- 视频生成详细用法 → [api-veo.md](./api-veo.md)

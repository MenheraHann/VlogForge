# Veo 视频生成 API 参考

> 学习来源：官方 Resources 中的 GenMedia notebooks + MCP GenMedia 工具
> 整理时间：2026-02-25

---

## 一、什么是 Veo

Veo 是 Google 的视频生成模型，VlogForge 使用 **Veo 3.1** 的**首尾帧功能**：给定两张图片（首帧 + 尾帧），Veo 生成中间的过渡视频。

**模型列表：**

| 模型 ID                       | 特点                         | 时长   | 比例       | 音频 |
| ----------------------------- | ---------------------------- | ------ | ---------- | ---- |
| `veo-3.1-generate-001`      | 正式版，高质量               | 4/6/8s | 16:9, 9:16 | 支持 |
| `veo-3.1-fast-generate-001` | 快速版，低延迟               | 4/6/8s | 16:9, 9:16 | 支持 |
| `veo-3.1-generate-preview`  | 预览版，支持视频延长和参考图 | 4/6/8s | 16:9, 9:16 | 支持 |
| `veo-3.0-generate-001`      | 旧版                         | 4/6/8s | 仅 16:9    | 支持 |

**重要发现：Veo 3+ 自带语音/对话生成**（`generate_audio=True`），旁白可以直接在视频中生成，不需要额外 TTS。

---

## 二、客户端初始化

```python
from google import genai
from google.genai import types

# 方式 A：API Key（开发阶段）
client = genai.Client(api_key="YOUR_GEMINI_API_KEY")

# 方式 B：Vertex AI（部署阶段）
# 注意：视频生成 location 用 "global"
client = genai.Client(vertexai=True, project="项目ID", location="global")
```

---

## 三、核心 API 调用

### 3.1 文字生成视频（基础用法）

```python
import time

operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt="年轻亚洲女生在浴室对镜头说话，vlog风格，自然光",
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        number_of_videos=1,       # 1~4
        duration_seconds=6,       # 4, 6, 或 8
        resolution="1080p",       # 720p / 1080p / 4k
        person_generation="allow_adult",
        enhance_prompt=True,      # 自动优化提示词
        generate_audio=True,      # 生成语音/对话
    ),
)

# 异步轮询等待完成（视频生成需要时间）
while not operation.done:
    time.sleep(15)
    operation = client.operations.get(operation)

# 下载视频
if operation.result and operation.result.generated_videos:
    video_bytes = operation.result.generated_videos[0].video.video_bytes
    with open("output.mp4", "wb") as f:
        f.write(video_bytes)
```

### 3.2 图片生成视频（单张首帧）

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt="镜头从花田缓缓推进",
    image=types.Image.from_file(location="flowers.png"),  # 首帧
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        number_of_videos=1,
        duration_seconds=6,
        resolution="1080p",
        person_generation="allow_adult",
        generate_audio=True,
    ),
)
```

### 3.3 首帧 + 尾帧（VlogForge 核心用法）

这是 VlogForge 的关键功能：给定 Frame A 和 Frame B，Veo 生成从 A 到 B 的过渡视频。

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt="女生从对镜说话过渡到举起产品展示",
    image=types.Image.from_file(location="frame_A.png"),      # 首帧
    config=types.GenerateVideosConfig(
        last_frame=types.Image.from_file(location="frame_B.png"),  # 尾帧
        aspect_ratio="9:16",
        duration_seconds=6,
        resolution="1080p",
        number_of_videos=1,
        person_generation="allow_adult",
        generate_audio=True,
    ),
)

# 轮询等待
while not operation.done:
    time.sleep(15)
    operation = client.operations.get(operation)

# 获取视频
video_bytes = operation.result.generated_videos[0].video.video_bytes
```

**用 bytes 方式传入图片（适合从内存/存储读取）：**

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt=prompt_text,
    image=types.Image(
        image_bytes=first_frame_bytes,
        mime_type="image/png",
    ),
    config=types.GenerateVideosConfig(
        last_frame=types.Image(
            image_bytes=last_frame_bytes,
            mime_type="image/png",
        ),
        aspect_ratio="9:16",
        duration_seconds=6,
        resolution="1080p",
        number_of_videos=1,
        person_generation="allow_adult",
        generate_audio=True,
    ),
)
```

**用 GCS URI 传入（适合云端部署）：**

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt="女生展示产品",
    image=types.Image(gcs_uri="gs://bucket/frame_A.png", mime_type="image/png"),
    config=types.GenerateVideosConfig(
        last_frame=types.Image(gcs_uri="gs://bucket/frame_B.png", mime_type="image/png"),
        output_gcs_uri="gs://bucket/output/",  # 输出到 GCS
        aspect_ratio="9:16",
        duration_seconds=6,
        resolution="1080p",
        number_of_videos=1,
        person_generation="allow_adult",
        generate_audio=True,
    ),
)
```

### 3.4 参考图保持角色一致性（asset 模式）

用 `reference_images` 传入角色参考图，保持视频中人物外貌一致（最多 3 张）：

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",  # 注意：需要 preview 版本
    prompt="女生在浴室洗脸，vlog风格",
    config=types.GenerateVideosConfig(
        reference_images=[
            types.VideoGenerationReferenceImage(
                image=types.Image.from_file(location="character_ref.png"),
                reference_type="asset",
            ),
        ],
        aspect_ratio="9:16",
        number_of_videos=1,
        duration_seconds=8,
        resolution="1080p",
        person_generation="allow_adult",
        generate_audio=True,
    ),
)
```

### 3.5 视频延长

在已有视频末尾继续生成新片段：

```python
operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt="女生转身走出浴室",
    video=types.Video(uri="gs://bucket/existing_video.mp4", mime_type="video/mp4"),
    config=types.GenerateVideosConfig(
        output_gcs_uri="gs://bucket/output/",
        number_of_videos=1,
        duration_seconds=7,  # 延长 7 秒
        person_generation="allow_adult",
        generate_audio=True,
    ),
)
```

---

## 四、GenerateVideosConfig 完整参数

| 参数                  | 可选值                                  | 说明                      |
| --------------------- | --------------------------------------- | ------------------------- |
| `aspect_ratio`      | `"16:9"`, `"9:16"`                  | 画面比例                  |
| `number_of_videos`  | 1~4                                     | 生成数量（Veo 3+ 最多 2） |
| `duration_seconds`  | 4, 6, 8                                 | 视频时长（秒）            |
| `resolution`        | `"720p"`, `"1080p"`, `"4k"`       | 分辨率                    |
| `enhance_prompt`    | `True`/`False`                      | 自动优化提示词            |
| `generate_audio`    | `True`/`False`                      | 生成语音/对话（Veo 3+）   |
| `person_generation` | `"allow_adult"`, `"dont_allow"`     | 是否允许生成人物          |
| `last_frame`        | `types.Image`                         | 尾帧图片（首尾帧功能）    |
| `reference_images`  | `list[VideoGenerationReferenceImage]` | 角色参考图（最多 3 张）   |
| `output_gcs_uri`    | GCS 路径字符串                          | 输出到 Cloud Storage      |

---

## 五、输出方式

两种获取视频的方式：

**方式 1：直接获取 bytes（不设 output_gcs_uri）**

```python
video_bytes = operation.result.generated_videos[0].video.video_bytes
with open("output.mp4", "wb") as f:
    f.write(video_bytes)
```

**方式 2：存到 GCS（设置 output_gcs_uri）**

```python
config = types.GenerateVideosConfig(
    output_gcs_uri="gs://your-bucket/output/",
    ...
)
# 获取 GCS URI
video_uri = operation.result.generated_videos[0].video.uri
```

---

## 六、异步轮询模式

视频生成是异步操作，必须轮询等待完成：

```python
import time

operation = client.models.generate_videos(model=..., prompt=..., config=...)

# 轮询（建议 15 秒间隔，总超时 5 分钟）
timeout = 300  # 5 分钟
elapsed = 0
while not operation.done:
    if elapsed >= timeout:
        raise TimeoutError("视频生成超时")
    time.sleep(15)
    elapsed += 15
    operation = client.operations.get(operation)

# 检查结果
if operation.result and operation.result.generated_videos:
    video = operation.result.generated_videos[0]
    # 处理视频...
else:
    # 生成失败，检查 operation.error
    print(f"生成失败: {operation.error}")
```

---

## 七、VlogForge 中的使用场景

VlogForge 的视频生成链：

```
Frame 1 → Frame 2 → Frame 3 → Frame 4 → Frame 5 → Frame 6
   └─ 视频1 ─┘    └─ 视频2 ─┘    └─ 视频3 ─┘    └─ 视频4 ─┘    └─ 视频5 ─┘
```

每个视频片段的生成调用：

```python
# 视频 N：Frame N → Frame N+1
operation = client.models.generate_videos(
    model="veo-3.1-generate-001",
    prompt=segment.veo_description,                               # TA 生成的 Veo 描述词
    image=types.Image(image_bytes=frame_n_bytes, mime_type="image/png"),
    config=types.GenerateVideosConfig(
        last_frame=types.Image(image_bytes=frame_n1_bytes, mime_type="image/png"),
        aspect_ratio=job_data["aspect_ratio"],                    # 来自用户选择的平台
        duration_seconds=segment_duration,                        # 根据总时长/分段数计算
        resolution="1080p",
        number_of_videos=1,
        person_generation="allow_adult",
        generate_audio=True,                                      # 旁白由 Veo 自动生成
    ),
)
```

**注意事项：**

- 首尾帧的画面要有相似性（同一人物、同一场景），效果最好
- `generate_audio=True` 时 Veo 会根据 prompt 中的对话内容生成语音
- 各片段可以**并行生成**，最后由 FFmpeg 拼接
- 拼接时需要裁掉相邻片段的重复帧（尾帧N = 首帧N+1）

---

## 八、参考资源

- [Veo 3 Video Generation notebook](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision/getting-started)
- [Veo 3 Reference-to-Video notebook](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision/getting-started)
- [GenMedia Live 示例应用](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision/sample-apps/genmedia-live)
- [MCP Veo 工具源码](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio/tree/main/experiments/mcp-genmedia)

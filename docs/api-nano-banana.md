# Nano Banana 图片生成 API 参考

> 学习来源：官方 Resources 中的 GenMedia notebooks + MCP GenMedia 工具 + Nano Banana Pro LinkedIn Demo
> 整理时间：2026-02-25

---

## 一、什么是 Nano Banana

Nano Banana 是 Gemini 原生图片生成能力的代号，不是 Imagen。它通过 Gemini 的 `generate_content` 接口实现，设置 `response_modalities=["TEXT", "IMAGE"]` 后，Gemini 可以同时输出文字和图片。

**模型列表：**

| 代号 | 模型 ID | 特点 |
|------|---------|------|
| Nano Banana | `gemini-2.5-flash-image` | 速度快，性价比高 |
| Nano Banana Pro | `gemini-3-pro-image-preview` | 质量高，支持复杂多轮编辑 |

---

## 二、客户端初始化

```python
from google import genai
from google.genai import types

# 方式 A：API Key（开发阶段，简单直接）
client = genai.Client(api_key="YOUR_GEMINI_API_KEY")

# 方式 B：Vertex AI（部署阶段，需要 GCP 项目）
# 注意：图片生成 location 用 "global"，不是 "us-central1"
client = genai.Client(vertexai=True, project="项目ID", location="global")
```

---

## 三、核心 API 调用

### 3.1 纯文字生成图片

```python
response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents="年轻亚洲女生在浴室对镜头说话，自然光，vlog风格",
    config=types.GenerateContentConfig(
        temperature=0.7,
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio="9:16",
            image_size="2K",
        ),
    ),
)

# 提取生成的图片
for part in response.parts:
    if part.text is not None:
        print(part.text)  # 模型可能会附带文字说明
    elif part.inline_data is not None:
        # 方式 1：用 PIL Image
        image = part.as_image()
        image.save("output.png")
        # 方式 2：直接写 bytes
        with open("output.png", "wb") as f:
            f.write(part.inline_data.data)
```

### 3.2 带参考图生成（产品植入核心用法）

传入用户上传的产品图作为参考，让生成的画面中包含该产品：

```python
from PIL import Image

product_img = Image.open("product.jpg")

response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=[
        product_img,  # 产品参考图放在前面
        "女生手持这个产品特写，浴室场景，暖色调，vlog风格",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(
            aspect_ratio="9:16",
            image_size="2K",
        ),
    ),
)
```

也可以用 inline bytes 方式传入参考图（适合从网络/存储读取的场景）：

```python
content_parts = []
# 添加参考图（bytes 格式）
content_parts.append(
    {"inline_data": {"mime_type": "image/png", "data": image_bytes}}
)
# 添加文字提示词
content_parts.append("基于参考图中的产品，生成女生手持产品的特写画面")

response = client.models.generate_content(
    model="gemini-2.5-flash-image",
    contents=content_parts,
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="9:16", image_size="2K"),
    ),
)
```

### 3.3 多张参考图（最多 14 张）

```python
response = client.models.generate_content(
    model="gemini-3-pro-image-preview",
    contents=[
        Image.open("product.png"),
        Image.open("brand_logo.png"),
        Image.open("color_palette.png"),
        "使用这些品牌素材，生成一张营销广告图",
    ],
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="16:9", image_size="2K"),
    ),
)
```

### 3.4 多轮对话迭代编辑

```python
chat = client.chats.create(
    model="gemini-3-pro-image-preview",
    config=types.GenerateContentConfig(
        response_modalities=["TEXT", "IMAGE"],
    )
)

# 第 1 轮：生成基础图
response = chat.send_message("创建一张明亮浴室场景的 vlog 画面")

# 第 2 轮：修改已有图片
response = chat.send_message("把背景改成粉色系，增加温馨感")

# 第 3 轮：继续调整
response = chat.send_message("在画面中添加一瓶白色洗面奶")
```

---

## 四、ImageConfig 参数

| 参数 | 可选值 | 说明 |
|------|--------|------|
| `aspect_ratio` | `"1:1"`, `"2:3"`, `"3:2"`, `"3:4"`, `"4:3"`, `"4:5"`, `"5:4"`, `"9:16"`, `"16:9"`, `"21:9"` | 画面比例 |
| `image_size` | `"1K"`, `"2K"`, `"4K"` | 分辨率 |

---

## 五、与 Imagen 4 的区别

| 特性 | Nano Banana (Gemini) | Imagen 4 |
|------|---------------------|----------|
| API 接口 | `generate_content()` | `generate_images()` |
| 输出 | 文字 + 图片混合 | 纯图片 |
| 参考图编辑 | 直接在 contents 中传入 | 需要用 EditImage API |
| 多轮对话 | 支持 | 不支持 |
| 适用场景 | 需要理解上下文、做编辑的场景 | 单次高质量出图 |

**VlogForge 选择 Nano Banana**，因为我们需要：
- 传入产品参考图生成画面（参考图编辑能力）
- 可能需要多轮调整分镜图质量
- 与 Gemini 的理解能力结合（理解脚本内容生成对应画面）

---

## 六、VlogForge 中的使用场景

| 场景 | 调用方式 |
|------|---------|
| 普通分镜帧 | 风格指南 + 帧提示词 → `generate_content` |
| 产品植入帧 | 用户产品图 + 风格指南 + 帧提示词 → `generate_content`（带参考图） |
| 风格一致性维护 | 可传入前序生成的图片作为参考，保持画风统一 |

---

## 七、参考资源

- [GenMedia notebooks (图片/视频)](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision)
- [Gemini 3 Image Gen notebook](https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/getting-started/intro_gemini_3_image_gen.ipynb)
- [GenMedia Live 示例应用](https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision/sample-apps/genmedia-live)
- [MCP GenMedia 工具](https://github.com/GoogleCloudPlatform/vertex-ai-creative-studio/tree/main/experiments/mcp-genmedia)
- [Nano Banana Pro 营销 Demo (LinkedIn)](https://www.linkedin.com/posts/katiemn_nanobananapro-googlecloud-vertexai-activity-7397313402643181568-2hlW)

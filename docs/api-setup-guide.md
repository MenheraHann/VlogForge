# API 申请 & 比赛额度指南

> 整理时间：2026-02-25

---

## 一、获取 Gemini API Key

### 方式 A：Google AI Studio（开发调试用）

最简单的方式，适合本地开发和测试。

1. 打开 https://aistudio.google.com
2. 用 Google 账号登录
3. 左侧点 **"Get API key"**（或直接访问 https://aistudio.google.com/apikey ）
4. 点 **"Create API key"**
   - 选 "Create API key in new project"（自动创建 GCP 项目）
   - 或选已有的 GCP 项目
5. 复制生成的 Key（格式：`AIzaSy...`）
6. 写入项目 `.env` 文件：
   ```
   GEMINI_API_KEY=AIzaSy...你的Key...
   ```

**注意**：AI Studio 的免费额度对文本和图片生成够用，但 **Veo 视频生成可能有严格限制**，建议申请比赛额度走 Vertex AI。

### 方式 B：Vertex AI（比赛部署用）

比赛要求必须部署在 Google Cloud，最终需要用这种方式。

1. 打开 https://console.cloud.google.com
2. 创建新项目（或用 AI Studio 自动创建的项目）
3. 启用 **Vertex AI API**：
   - APIs & Services → Enable APIs → 搜索 "Vertex AI API" → 启用
4. 安装 gcloud CLI 并登录：
   ```bash
   gcloud auth application-default login
   ```
5. 在代码中使用：
   ```python
   client = genai.Client(vertexai=True, project="你的项目ID", location="global")
   ```

**关键**：视频生成（Veo）和图片生成（Nano Banana）的 location 必须用 `"global"`，文本生成用 `"us-central1"`。

---

## 二、比赛额度申请

### Google Cloud Credits 申请表（必填！）

**申请链接**：https://forms.gle/rKNPXA1o6XADvQGb7

这是比赛官方 Resources 里列出的**必申请项目**，填表后 Google 会给你的 GCP 账户充入免费额度，用于开发和测试。

> 历史经验：Google 黑客松通常给参赛者 $50 ~ $300 不等的额度，具体金额由 Google 审批决定。

**申请建议**：

- 尽早申请，额度可能需要几个工作日到账
- 填写时注明你的 GCP Project ID
- 说明需要使用 Veo 视频生成（计算密集型）

### Google Cloud 免费试用（新用户）

如果你的 Google Cloud 账号是新的，还没用过免费试用：

- **$300 免费额度**，90 天有效
- 申请地址：https://cloud.google.com/free
- 可以和比赛额度叠加使用

---

## 三、比赛奖金 & GCP Credits

### 奖项总览（总奖池约 $80,000）

| 奖项                                       | 现金 (USD)       | GCP Credits | 名额 |
| ------------------------------------------ | ---------------- | ----------- | ---- |
| **Grand Prize** 总冠军               | $25,000 | $3,000 | 1           |      |
| **Best of Live Agents**              | $10,000 | $1,000 | 1           |      |
| **Best of Creative Storytellers**    | $10,000 | $1,000 | 1           |      |
| **Best of UI Navigators**            | $10,000 | $1,000 | 1           |      |
| **Best Multimodal Integration & UX** | $5,000 | $500    | 1           |      |
| **Best Technical Execution**         | $5,000 | $500    | 1           |      |
| **Best Innovation**                  | $5,000 | $500    | 1           |      |
| **Honorable Mentions** 荣誉提名      | $2,000 | $500    | 5           |      |

我们参加的是 **Creative Storyteller** 赛道，对应奖项 $10,000 + $1,000 GCP Credits。

---

## 四、Veo 视频生成的费用估算

Veo 是整个项目中最贵的 API 调用，需要注意成本控制。

### 预估单价

- Veo 3.x 视频生成：约 **$0.30 ~ $0.50 / 秒**
- 一段 8 秒视频 ≈ **$2.5 ~ $4**

### VlogForge 单次完整生成的估算

- 5 个分段 × 8 秒 = 40 秒视频
- 预估成本：**$12 ~ $20 / 次**

### 省钱建议

| 阶段     | 策略                                           |
| -------- | ---------------------------------------------- |
| 开发调试 | 用 `veo-3.1-fast-generate-001`（更快更便宜） |
| 开发调试 | 时长用 4s，分辨率用 720p                       |
| 开发调试 | `number_of_videos=1`                         |
| 正式演示 | 切换 `veo-3.1-generate-001`，8s + 1080p      |

---

## 五、项目 .env 完整配置

```env
# Gemini API Key（AI Studio 获取）
GEMINI_API_KEY=AIzaSy...

# Google Cloud 项目（部署时需要）
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=us-central1

# Cloud Storage 桶（存储中间产物：图片、视频）
GCS_BUCKET_NAME=vlogforge-artifacts

# 服务端口
PORT=8000
```

---

## 六、关键时间节点

| 日期                          | 事项                            |
| ----------------------------- | ------------------------------- |
| 2026-02-16                    | 比赛开始                        |
| **2026-03-16 17:00 PT** | **提交截止**              |
| 2026-03-17 ~ 04-03            | 评审期                          |
| 2026-04-22~24                 | Google Cloud Next 2026 公布获奖 |

> 距离截止还有约 **19 天**。

---

## 七、关键链接汇总

| 用途                       | 链接                                                                  |
| -------------------------- | --------------------------------------------------------------------- |
| 比赛主页                   | https://geminiliveagentchallenge.devpost.com/                         |
| 比赛规则                   | https://geminiliveagentchallenge.devpost.com/rules                    |
| **GCP Credits 申请** | https://forms.gle/rKNPXA1o6XADvQGb7                                   |
| AI Studio（获取 API Key）  | https://aistudio.google.com/apikey                                    |
| Google Cloud 免费试用      | https://cloud.google.com/free                                         |
| Gemini API 文档            | https://ai.google.dev/gemini-api/docs                                 |
| Veo API 文档               | https://ai.google.dev/gemini-api/docs/video                           |
| GenMedia 示例代码          | https://github.com/GoogleCloudPlatform/generative-ai/tree/main/vision |

---

## 八、提交要求清单

比赛提交需要准备：

- [ ] **公开代码仓库** — README 包含可复现的启动/部署说明
- [ ] **架构图** — 清晰的系统架构
- [ ] **演示视频** — < 4 分钟，真实执行（非 mock），说明问题和方案
- [ ] **部署到 Google Cloud** — 必须使用至少一个 Google Cloud 服务

### 加分项（可选）

- [ ] 发布关于使用 Google AI & Cloud 构建的内容（带 `#GeminiLiveAgentChallenge` 标签）
- [ ] 加入 Google Developer Group (GDG)
- [ ] 使用脚本/IaC 实现自动化云部署

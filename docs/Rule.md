# Gemini Live Agent Challenge 比赛说明

## 官方链接

- **比赛主页**：https://geminiliveagentchallenge.devpost.com/
- **官方规则**：https://geminiliveagentchallenge.devpost.com/rules

---

## 一、比赛简介

**主题**：Redefining Interaction: From Static Chatbots to Immersive Experiences  
（重新定义交互：从静态聊天机器人到沉浸式体验）

**核心要求**：参赛者需开发**新一代 AI Agent**，使用多模态输入与输出，突破「纯文字对话」的范式，结合 **Google Live API** 与视频/图像生成能力，在以下**三大赛道**中任选其一完成作品。

**通用技术约束**（所有项目必须满足）：
- 使用 **Gemini 模型**
- 使用 **Google GenAI SDK** 或 **ADK（Agent Development Kit）** 构建 Agent
- 至少使用**一项 Google Cloud 服务**
- Agent 须**托管在 Google Cloud** 上

---

## 二、三大赛道

### 赛道 1：Live Agents（实时语音/视觉 Agent）

| 项目 | 说明 |
|------|------|
| **重点** | 实时交互（音频 + 视觉） |
| **必选技术** | 必须使用 **Gemini Live API** 或 **ADK**，Agent 托管在 Google Cloud |
| **方向说明** | 用户能用自然语言与 Agent 对话，且**可被打断**（barge-in）。例如：实时翻译、能「看到」作业的视觉辅导老师、能优雅处理打断的客服语音 Agent 等。 |

---

### 赛道 2：Creative Storyteller（创意叙事 / 多模态内容生成）

| 项目 | 说明 |
|------|------|
| **重点** | 多模态叙事与**交错输出**（Interleaved Output） |
| **必选技术** | 必须使用 **Gemini 的交错/混合输出能力**（interleaved/mixed output），Agent 托管在 Google Cloud |
| **方向说明** | Agent 像创意总监一样思考与创作，在**同一条流式输出**中交织文本、图片、音频、视频。例如：互动故事书（文字 + 内联插图）、营销素材生成（文案 + 视觉 + 视频一气呵成）、教育讲解（旁白 + 图表）、社媒内容（文案 + 图 + 话题标签一起生成）等。 |

---

### 赛道 3：UI Navigator（界面理解与操作 Agent）

| 项目 | 说明 |
|------|------|
| **重点** | 视觉 UI 理解与交互（「用户的手」） |
| **必选技术** | 必须使用 **Gemini 多模态**理解截图/录屏，并输出**可执行操作**，Agent 托管在 Google Cloud |
| **方向说明** | Agent 观察浏览器或设备画面，理解界面元素（可结合或可不结合 API/DOM），根据用户意图执行操作。例如：通用网页导航、跨应用工作流自动化、基于视觉的 QA 测试 Agent 等。 |

---

## 三、提交要求

| 类型 | 要求 |
|------|------|
| **代码仓库** | 公开仓库 URL，README 中需包含**可复现的启动/部署说明** |
| **架构图** | 清晰展示系统架构（如 Gemini、后端、数据库、前端的连接关系） |
| **演示视频** | 时长 **&lt; 4 分钟**；需展示多模态/Agent 功能**实时运行**（非 mock）；说明解决的问题与方案价值 |

**加分项（可选）**：
- 发布一篇内容（博客/播客/视频）介绍如何用 Google AI 与 Google Cloud 构建项目，并注明为本次黑客松创作，使用话题 `#GeminiLiveAgentChallenge`
- 加入 Google Developer Group（GDG）并提交公开资料链接
- 用脚本或 IaC 自动化云部署，相关代码放入公开仓库

---

## 四、奖项概览

| 奖项 | 奖金（USD） | 名额 |
|------|-------------|------|
| **Grand Prize（总冠军）** | $25,000 + $3,000 GCP 积分等 | 1 |
| **Best of Live Agents** | $10,000 + $1,000 GCP 积分等 | 1 |
| **Best of Creative Storytellers** | $10,000 + $1,000 GCP 积分等 | 1 |
| **Best of UI Navigators** | $10,000 + $1,000 GCP 积分等 | 1 |
| **Best Multimodal Integration & User Experience** | $5,000 + $500 GCP 积分 | 1 |
| **Best Technical Execution & Agent Architecture** | $5,000 + $500 GCP 积分 | 1 |
| **Best Innovation & Thought Leadership** | $5,000 + $500 GCP 积分 | 1 |
| **Honorable Mentions** | $2,000 + $500 GCP 积分 | 5 |

总奖池约 **$80,000**。具体奖品细节（会议门票、差旅等）以官方规则为准。

---

## 五、评审标准（权重）

| 维度 | 权重 | 要点 |
|------|------|------|
| **Innovation & Multimodal User Experience** | 40% | 是否打破「文本框」范式；是否自然、沉浸；See / Hear / Speak 是否流畅；Live Agents 是否自然处理打断；Storyteller 是否流畅交织多模态；UI Navigator 是否具备视觉精度 |
| **Technical Implementation & Agent Architecture** | 30% | 是否有效使用 GenAI SDK/ADK；是否稳健托管于 Google Cloud；逻辑是否清晰、是否处理异常与幻觉、是否有 grounding |
| **Demo & Presentation** | 30% | 视频是否展示真实运行（非 mock）；架构图是否清晰；是否有云部署的可视化证明；是否清晰说明问题与方案 |

---

## 六、重要时间（太平洋时间 PT）

| 阶段 | 时间 |
|------|------|
| **比赛开始** | 2026-02-16 10:00 PT |
| **提交截止** | 2026-03-16 17:00 PT |
| **评审期** | 2026-03-17 ~ 2026-04-03 |
| **获奖公布** | 约 2026-04-22 ~ 04-24（Google Cloud Next 2026） |

---

*以上整理自官方 Devpost 页面与 Rules，如有更新以官网为准。*

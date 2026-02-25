# 技术方案决策记录

## D2：TA Agent

**选定方案 A：单次调用 + JSON Schema 模式**

- 1 次 Gemini 调用 → 直接输出 ScriptOutput JSON
- `response_mime_type="application/json"` + `response_schema`
- MVP 优先，15s/30s 足够，60s 质量不行再升级方案 B（两阶段）
- 方案 B 是 A 的超集，随时可升级

## D3：DA Agent

**选定方案：asyncio.create_task 后台执行流水线**

- `/api/generate` 收到请求后立即返回 job_id，DA 在后台异步运行
- DA 按固定顺序调度：TA → VA → VGA → QA → FFmpeg
- 通过 job_manager 更新进度，前端用 SSE 轮询
- 当前 D3 只接通 TA，VA/VGA/QA/FFmpeg 为占位 TODO

## D4：前端

**选定方案 A：单页向导流（Step Flow）**

- 三步全屏过渡：输入 → 生成中 → 结果
- 纯 HTML + CSS + JS，不用框架
- 暗色主题 + 毛玻璃 + 渐变，现代 AI 产品风格
- SSE 实时更新进度

## D5：架构精简

**合并 PDA/CDA/SDA → ADA（素材设计师）**

- 三者工作流同构（Gemini 文本 → Nano Banana 生图），仅 prompt 不同
- 合并为一个 ADA Agent + `asset_type` 参数切换 prompt 模板
- 减少约 60% 重复代码（1 个 agent 文件 + 1 个 prompt 文件 vs 3+3）

**QA 降为 P4 可选**

- 主流程：TA → VA → VGA → FFmpeg，不含 QA
- QA 增加额外调用成本和延迟，hackathon 阶段先跑通主链路
- 后续作为优化项插入 VGA 和 FFmpeg 之间

**DA 保留**

- 虽然当前只是顺序调用，但保留编排层便于后续加重试/动态调度

## D6：DA 脚本审核

**选定方案 B：自检 + DA 规则校验**

- DA 生成脚本时同步输出 `self_check` 字段（人物匹配度/产品准确度/场景一致性，各 1-5 分）
- DA 对自身输出做规则校验：低于阈值 → 带反馈重跑（最多 1 次）
- 零额外 Gemini 调用，零额外延迟
- VA/VGA 的审核能力留作 TODO，后续按需加入

## D7：架构 v4 — 精简至 4 Agent

> 基于全面审核后的 4 项决策，一次性落地

**1. TA 合入 DA**

- DA 直接调用 Gemini 生成脚本，不再有独立 TA Agent
- DA 读取素材档案（物品+人物+场景）+ 用户额外要求 → Gemini 文本生成 ScriptOutput
- DA 成为真正的"创意总监"：既编排又创作
- 好处：减少一层调用延迟；DA 天然拥有素材上下文，脚本质量更高
- D2 的技术方案（单次 JSON Schema 调用）不变，仅执行者从 TA 变为 DA

**2. VA 链式图生图**

- VA 使用 Nano Banana img2img 逐帧生成分镜图
- 帧 1 = 素材图（人物造型 + 场景 + 产品）+ 帧 1 提示词 → Nano Banana
- 帧 N = 帧 N-1 的输出图 + 帧 N 提示词 → Nano Banana
- 每帧基于上一帧生成，天然保持人物/场景/产品的画面一致性
- 替代原方案"每帧独立生图 + 风格指南约束"，一致性大幅提升

**3. QA 完全移除**

- 从 D5 的"P4 可选"升级为"完全移除"
- DA 通过 self_check 自检替代独立 QA 环节（D6 方案）
- JobStatus 中移除 `QA_REVIEWING` 状态
- 后续如需恢复，作为 DA 的一个可选步骤插入，不再作为独立 Agent

**4. 模式 B 由 DA 负责**

- DA 收到一句话需求 → Gemini 文本拆解为物品+人物+场景需求
- DA 调用 ADA（物品模式）、ADA（人物模式）、ADA（场景模式）
- 用户确认后存入素材库 → 进入视频生成流程

**最终架构：4 Agent**

| 角色 | 代号 | 阶段 | 核心 API |
|------|------|------|----------|
| 素材设计师 | ADA | 素材创建 | Gemini 文本 + Nano Banana |
| 创意总监 | DA | 视频生成 | Gemini 文本 |
| 美术指导 | VA | 视频生成 | Nano Banana (img2img) |
| 剪辑师 | VGA | 视频生成 | Veo 3.1 |

**视频生成主链路**：DA(脚本+自检) → VA(链式图生图) → VGA(首尾帧视频) → FFmpeg(拼接)

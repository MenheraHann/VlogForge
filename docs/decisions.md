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

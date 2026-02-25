# VGA — 剪辑师（Video Generation Agent）

> 用 Veo 首尾帧功能生成视频片段，支持链式延长

---

## 首段视频生成（First Segment）

### Task

使用 Veo 的首帧图片功能生成第一个视频片段。这是整个视频的起始段，只有首帧图片作为视觉输入。

### Context

**Prompt 构建规则：**
```
完整 prompt = voice_anchor + "\n\n" + veo_description
```

- `voice_anchor`（来自 DA）放在 prompt 最前面，让 Veo 优先感知声音特征
- `veo_description`（来自 DA 脚本的每个分段）描述动态过程
- 旁白内容已包含在 `veo_description` 中，Veo 会据此生成语音

**Veo 参数：**
- 模型：`veo-3.1-generate-001`
- 首帧图片：VA 生成的帧图
- `generate_audio=True`：让 Veo 自动生成语音
- `aspect_ratio`：由平台决定（抖音/小红书 9:16，YouTube 16:9）

### Reference

工作流：
```
输入：frame_1.png + voice_anchor + segment_1.veo_description
  ↓
VGA 调用 Veo generate_videos API（image=frame_1, generate_audio=True）
  ↓
等待生成完成（轮询 operation）
  ↓
输出：segment_1.mp4（约 8 秒）
```

---

## 后续段视频生成（Chain Extension Mode）

### Task

使用 Veo 的首尾帧功能或视频延长功能生成后续视频片段，与前一段在画面和声音上保持连贯。

### Context

**两种模式：**

**模式 A — 首尾帧模式（默认）：**
- 使用当前分段的首帧图 + 尾帧图作为 Veo 的 `image` 和 `last_frame` 输入
- 适用于有明确首尾帧的标准分段

**模式 B — 视频延长模式：**
- 使用上一段生成的视频作为输入，通过 `VIDEO_EXTEND_MODEL` 延长
- 适用于需要更平滑过渡的连续场景
- 延长模型：`veo-3.1-generate-preview`

**声音连贯性：**
- 每个片段的 prompt 都以相同的 `voice_anchor` 开头
- Veo 会根据 prompt 生成匹配的语音，`voice_anchor` 确保跨片段声音一致

### Reference

**模式 A 工作流：**
```
输入：frame_N.png + frame_N+1.png + voice_anchor + segment_N.veo_description
  ↓
VGA 调用 Veo API（image=frame_N, last_frame=frame_N+1, generate_audio=True）
  ↓
输出：segment_N.mp4
```

**模式 B 工作流：**
```
输入：segment_N-1.mp4 + voice_anchor + segment_N.veo_description
  ↓
VGA 调用 Veo extend API（video=segment_N-1.mp4, generate_audio=True）
  ↓
输出：segment_N.mp4（在前一段基础上延长）
```

---

## 最终拼接（FFmpeg）

### Task

将所有视频片段按顺序拼接为最终输出视频。

### Context

- 使用 FFmpeg 的 concat 模式拼接
- 输出格式：MP4，H.264 编码
- 按分段顺序拼接：segment_1.mp4 + segment_2.mp4 + ... + segment_N.mp4
- 不额外添加 BGM（Veo 已生成语音）

### Reference

```bash
# 创建拼接列表
echo "file 'segment_1.mp4'" > concat_list.txt
echo "file 'segment_2.mp4'" >> concat_list.txt
echo "file 'segment_3.mp4'" >> concat_list.txt

# 拼接
ffmpeg -f concat -safe 0 -i concat_list.txt -c copy output.mp4
```

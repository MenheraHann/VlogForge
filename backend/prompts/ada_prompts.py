"""
ADA Agent 提示词模板
素材设计师（Asset Designer Agent）两套 prompt：物品 / 人物（含场景）
v10 架构：场景融入人物，人物生成一张「人在场景中的半身近景」portrait_image
"""

# ========== 物品模式 — 第 1 步：分析 + 生成问卷 ==========

ADA_ITEM_ANALYZE_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**物品模式 — 分析阶段**。

## Task

分析用户提供的产品图片和描述，完成以下工作：
1. 识别产品类型，判断是否为可处理的小型产品（small/large）
2. 按 P0/P1/P2 优先级梳理该产品的特征与卖点
3. 为每个需要确认/补充的信息维度，生成一道**选择题**
4. 输出一份逐题选择式问卷，前端将一次只展示一道题给用户

## Context

### 卖点优先级规则

| 优先级 | 含义 | 收集策略 |
|--------|------|----------|
| P0 | 核心卖点，视频必须重点展示 | 优先收集。无法自信推断时，必须主动询问用户 |
| P1 | 辅助卖点，增强说服力 | AI 预填为主，用户可修改 |
| P2 | 锦上添花信息 | AI 预填，标记为可选（用户可跳过） |

### 信息收集规则
- 向用户提出的问题控制在 5~10 个
- 优先完成 P0 等级的信息收集
- 如果你不确定某产品的 P0 卖点，第一个问题就问：「你认为这个产品最大的卖点是什么？」
- P0 信息是视频脚本的灵魂

### 逐题选择式问卷规则（核心）

每道题必须包含 **option_a** 和 **option_b** 两个 AI 候选答案：
- **选项 A 和 B 必须是有实质差异的两个回答**，不能只是换个说法
- 选项文案风格偏**口语化 + 营销化**，适合带货短视频的语境
- P0 级别的题目：两个选项从不同角度切入（如功效 vs 情感、成分 vs 体验）
- P1 级别的题目：两个选项提供不同的信息密度或侧重
- 每个选项控制在 1~2 句话，不要太长
- 用户还可以选择「我来填写」（选项 C），自行输入回答

### 参考维度（不固定，按品类灵活调整）
产品名称、产品类别、核心卖点、解决什么问题、使用人群、使用场景、使用方法、材质/品质细节、价格信息、优惠福利、售后保障、发货时间、信任背书、促单话术 ……

### 尺寸判断
- small：上半身可演示的小型产品（化妆品、书本、手机壳、饰品等）→ 允许
- large：需要全身/户外场景的产品（家具、电器、汽车等）→ 拒绝

## Reference

### 示例：护肤品（氨基酸洗面奶）
输入："氨基酸洗面奶，温和不紧绷"

问卷题目示例：
```
题目 1 (P0): "你认为这款洗面奶最大的卖点是什么？"
  option_a: "氨基酸温和配方，洗后不紧绷不假滑"
  option_b: "深层清洁不伤肌肤屏障，敏感肌的福音"

题目 2 (P0): "这款产品主要解决什么皮肤问题？"
  option_a: "洗完脸总觉得紧绷干燥，像被扒了一层皮"
  option_b: "清洁不干净又怕刺激，找不到平衡的洗面奶"

题目 3 (P1): "怎么描述使用方法最吸引人？"
  option_a: "挤出黄豆大小，加水打出绵密泡沫，上脸打圈按摩后冲洗"
  option_b: "泡沫超绵密，轻轻揉两下就满脸泡泡，冲水即净"
```

注意 A/B 选项的差异：
- 题目 1：A 侧重成分配方，B 侧重功效承诺
- 题目 2：A 从体感痛点切入，B 从选择困难切入
- 题目 3：A 偏教程式描述，B 偏体验式种草

## 输出格式
严格按照 JSON Schema 输出。
"""


def build_item_analyze_prompt(product_description: str) -> str:
    """构建物品分析的用户提示词（第 1 步：生成问卷）"""
    return f"""请分析以下产品，输出结构化的分析结果和智能问卷：

【用户描述】
{product_description}

请根据描述（和图片，如果提供了的话）：
1. 识别产品类型和尺寸（small/large）
2. 按 P0/P1/P2 梳理卖点
3. 生成问卷字段（每个字段标注优先级、来源、是否必填）
4. 问题总数控制在 5~10 个
"""


def get_item_analyze_schema() -> dict:
    """物品分析 JSON Schema（第 1 步）"""
    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "产品名称"},
            "category": {"type": "STRING", "description": "产品类别"},
            "size_category": {"type": "STRING", "description": "尺寸: small 或 large"},
            "selling_points": {
                "type": "OBJECT",
                "description": "按优先级分组的卖点",
                "properties": {
                    "P0": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "核心卖点列表",
                    },
                    "P1": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "辅助卖点列表",
                    },
                    "P2": {
                        "type": "ARRAY",
                        "items": {"type": "STRING"},
                        "description": "锦上添花信息",
                    },
                },
                "required": ["P0", "P1", "P2"],
            },
            "questionnaire": {
                "type": "ARRAY",
                "description": "逐题选择式问卷，每题包含 A/B 两个候选答案",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "key": {"type": "STRING", "description": "字段标识，如 selling_point"},
                        "label": {"type": "STRING", "description": "题目文案，如「你认为这款洗面奶最大的卖点是什么？」"},
                        "option_a": {"type": "STRING", "description": "AI 候选答案 A（口语化营销风格，1-2 句话）"},
                        "option_b": {"type": "STRING", "description": "AI 候选答案 B（与 A 有实质差异，不同角度/侧重）"},
                        "value": {"type": "STRING", "description": "AI 预填值（P1/P2 可预填为 option_a，P0 留空让用户主动选择）"},
                        "priority": {"type": "STRING", "description": "P0/P1/P2"},
                        "source": {"type": "STRING", "description": "ai 或 user"},
                        "required": {"type": "BOOLEAN", "description": "是否必填（P2 为 false，可跳过）"},
                    },
                    "required": ["key", "label", "option_a", "option_b", "value", "priority", "source", "required"],
                },
            },
            "full_description": {"type": "STRING", "description": "AI 生成的初步产品描述"},
        },
        "required": ["name", "category", "size_category", "selling_points", "questionnaire", "full_description"],
    }


# ========== 物品模式 — 第 2 步：根据确认信息生成最终档案 ==========

ADA_ITEM_CONFIRM_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**物品模式 — 确认阶段**。

## Task

根据用户确认/修改后的问卷信息，生成最终的完整产品档案。

## Context

用户已经通过逐题选择式问卷确认或自行填写了产品信息。现在你需要：

1. **统一优化用户自定义输入的措辞**（核心）：
   - 用户选择 A/B 选项的内容可直接使用
   - 用户选择「我来填写」自行输入的内容，必须进行措辞优化：
     - **保留用户的原始意思**，只调整措辞和表述
     - 优化方向：更口语化、更有感染力、更适合短视频旁白使用
     - 如果用户的原始输入已经很好，可以只做微调甚至原样保留
   - 优化后的内容直接写入产品档案，不再需要用户二次确认

2. 整合所有确认后的信息

3. 生成一段完整的产品描述（150-250字），突出 P0 卖点

4. 提取核心卖点（P0 第一条）作为 selling_point

5. 描述要适合后续视频脚本使用，突出视觉特征和使用动作

6. **生成产品使用说明（usage_guide）**（关键）：
   - 面向「完全没有接触过该产品的人」，逐步描述如何使用
   - 每一步必须具体到动作细节，例如：
     - ✅ "用手拧开白色旋转瓶盖，放在一旁"
     - ✅ "按压泵头 2-3 次，挤出约黄豆大小的膏体到指尖"
     - ❌ "打开产品使用"（太模糊，不知道怎么打开）
   - 必须清晰指出产品各部位名称（如"旋转盖""按压泵头""瓶口""管口"）
   - 用编号列表（1. 2. 3. ...）格式输出
   - 这段文字会提供给视频制作 AI，让它正确编排产品使用动作，所以必须足够详细

## Reference

用户自定义输入优化示例：
- 原始："这个洗面奶挺温和的不刺激" → 优化："温和到闭眼冲都不怕，敏感肌放心用"
- 原始："泡沫细腻好冲洗" → 优化："绵密泡泡上脸超舒服，清水一冲就干净"
- 原始："价格合理性价比高" → 可原样保留，已经足够简洁

## 输出格式
严格按照 JSON Schema 输出。
"""


def build_item_confirm_prompt(confirmed_fields: list[dict], selling_points: dict) -> str:
    """构建物品确认的用户提示词（第 2 步：含用户自定义输入标记）"""
    fields_text = ""
    for f in confirmed_fields:
        # 标记来源：如果 value 不是 option_a/option_b，则为用户自定义输入
        source_tag = ""
        if f.get("source") == "user":
            source_tag = " 【用户自填，需优化措辞】"
        fields_text += f"- {f['label']}：{f['value']}（{f['priority']}{source_tag}）\n"

    p0_text = "、".join(selling_points.get("P0", []))

    return f"""用户已通过逐题选择式问卷确认以下产品信息，请生成最终产品档案：

【确认后的产品信息】
{fields_text}

【核心卖点（P0）】
{p0_text}

注意：标记为「用户自填，需优化措辞」的内容是用户手动输入的，请优化措辞使其更口语化、更有感染力、更适合短视频旁白，但必须保留用户原意。

请整合以上信息，生成完整的产品档案 JSON。
"""


def get_item_confirm_schema() -> dict:
    """物品确认 JSON Schema（第 2 步）"""
    return {
        "type": "OBJECT",
        "properties": {
            "usage": {"type": "STRING", "description": "使用方式描述（简短概括）"},
            "selling_point": {"type": "STRING", "description": "核心卖点一句话（取 P0 第一条）"},
            "full_description": {"type": "STRING", "description": "完整产品描述 150-250 字"},
            "usage_guide": {
                "type": "STRING",
                "description": "产品使用说明：面向完全没接触过该产品的人，用编号列表逐步描述操作方式。"
                "每一步必须具体到动作细节（如'拧开白色旋转瓶盖''按压泵头2-3次'），"
                "并清晰指出产品各部位名称（如'瓶口''按压泵头''旋转盖'）。"
                "目标是让视频制作 AI 能据此正确编排产品使用动作，不出现操作错误。",
            },
        },
        "required": ["usage", "selling_point", "full_description", "usage_guide"],
    }


# ========== 物品模式 — 图片生成 ==========

# v9: 三图体系 — 缩略图（img2img，参考原图）
ADA_ITEM_THUMBNAIL_PROMPT = """请参考附带的产品实物照片，生成一张产品缩略图。

产品名称：{name}
产品描述：{full_description}

要求：
- 严格参考附带的产品照片，还原真实产品的外观、颜色、形状、标签
- 产品正面居中特写，背景纯白
- 类似电商白底主图风格，辨识度高
- 不要凭空想象产品外观，必须以照片中的实物为准
"""

# v9: 两图体系 — 三视图（img2img，参考原图，纯产品画面）
ADA_ITEM_THREE_VIEW_PROMPT = """请参考附带的产品实物照片，生成一张产品三视图。

产品名称：{name}
产品描述：{full_description}

要求：
- 严格参考附带的产品照片，还原真实产品的外观、颜色、形状、标签
- 在一张图中展示产品的正面、侧面、背面三个角度
- 三个视角水平排列，间距均匀
- 只展示产品本身，画面中不要出现任何文字、标注、箭头
- 背景纯白，光线均匀
- 不要凭空想象产品外观，必须以照片中的实物为准
"""

# 兼容旧版（保留以免其他地方引用）
ADA_ITEM_IMAGE_PROMPT = ADA_ITEM_THUMBNAIL_PROMPT


# ========== 兼容旧版（直接创建模式）==========

ADA_ITEM_SYSTEM_PROMPT = ADA_ITEM_ANALYZE_SYSTEM_PROMPT  # 兼容旧引用


def build_item_analysis_prompt(product_description: str) -> str:
    """兼容旧版：直接分析模式"""
    return build_item_analyze_prompt(product_description)


def get_item_response_schema() -> dict:
    """兼容旧版 Schema"""
    return get_item_analyze_schema()


# ========== 人物模式 ==========

ADA_MODEL_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**人物模式**（v10：场景已融入人物）。

## Task

根据用户提供的参考图或描述，拓展出完整的 vlog 模特人设档案，**包括拍摄场景信息**。

## Context

输出字段：
1. name：人物标签（简短，如"邻家短发女生"、"清冷御姐"）
2. appearance：外貌关键词（用顿号分隔，如"中国女性、25岁、长发、素颜、杏眼、自然肤色"）
3. personality：气质性格关键词（如"亲和活泼、邻家感"）
4. outfits：穿搭关键词（如"白色基础T恤、浅色牛仔裤"）
5. scene_context：场景关键词（用顿号分隔，如"客厅，背景是沙发、夜晚自然光、明亮的环境"）
6. image_prompt：**图片生成专用提示词**，严格使用关键词顿号分隔格式，不要写长句
7. full_description：完整的人设描述（用于其他 Agent 参考）

## 关键：image_prompt 格式

image_prompt 必须严格遵循以下格式，用顿号分隔关键词，不要写完整句子：

格式：`半身近景、{性别民族}、{年龄}岁、{发型}、{妆容/表情}、面对镜头、{场景}，背景是{背景物}、{光线}、{环境氛围}、手机拍摄的真实质感`

示例：
- "半身近景、中国女性、25岁、长发、素颜、面对镜头、客厅，背景是沙发、夜晚自然光、明亮的环境、手机拍摄的真实质感"
- "半身近景、中国女性、22岁、短发及肩、淡妆、面对镜头微笑、卧室，背景是白色床头和台灯、晨间自然光、温馨的环境、手机拍摄的真实质感"
- "半身近景、亚洲女性、28岁、马尾、清爽妆容、面对镜头、书房，背景是书架和绿植、午后自然光、安静明亮的环境、手机拍摄的真实质感"

规则：
- 人设要适合 vlog 带货场景，亲和力强
- **所有描述都用关键词格式**，不要写段落式长文
- **场景规则**：
  - 用户描述中有场景信息就直接用，没有就自动补充室内家居场景（客厅、卧室、书房、浴室）
  - 光线必须是自然光（非影棚专业灯光），环境明亮温暖
  - 必须有"手机拍摄的真实质感"关键词
  - 必须有"面对镜头"关键词

## 输出格式
严格按照 JSON Schema 输出。
"""

ADA_MODEL_IMAGE_PROMPT = "{image_prompt}"

def build_model_analysis_prompt(model_description: str) -> str:
    """构建人物分析的用户提示词（v10：包含场景信息分析）"""
    return f"""请根据以下描述拓展完整的 vlog 模特人设（包含拍摄场景信息）：

【用户描述】
{model_description}

请输出完整的人设档案 JSON，包含 scene_context 场景信息字段。
如果用户提供了参考图，请以参考图的外貌为基准进行描述。
如果用户描述中没有提及拍摄场景，请自动补充一个合适的室内家居场景。
"""


def get_model_response_schema() -> dict:
    """人物档案 JSON Schema（v10：含 scene_context + image_prompt）"""
    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "人物标签"},
            "appearance": {"type": "STRING", "description": "外貌关键词（顿号分隔）"},
            "personality": {"type": "STRING", "description": "气质性格关键词"},
            "outfits": {"type": "STRING", "description": "穿搭关键词"},
            "scene_context": {
                "type": "STRING",
                "description": "场景关键词（如'客厅，背景是沙发、夜晚自然光、明亮的环境'）",
            },
            "image_prompt": {
                "type": "STRING",
                "description": "图片生成专用提示词，严格关键词顿号分隔格式（如'半身近景、中国女性、25岁、长发、素颜、面对镜头、客厅，背景是沙发、夜晚自然光、明亮的环境、手机拍摄的真实质感'）",
            },
            "full_description": {"type": "STRING", "description": "完整人设描述"},
        },
        "required": ["name", "appearance", "personality", "outfits", "scene_context", "image_prompt", "full_description"],
    }


# ========== 一句话快速开始 — 拆解模式 ==========

ADA_QUICKSTART_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**一句话快速拆解模式**（v10：场景融入人物）。

## Task

用户输入了一句话描述 + 可能附带产品图片。你需要从这句话中拆解出两类素材信息：
1. **物品**（item）：要推广的产品
2. **人物**（model）：出镜的 vlog 模特 + 拍摄场景（场景已融入人物描述）

## Context

### 拆解规则
- 必须从用户的一句话中提取出物品和人物两个维度的信息
- **场景信息融入人物描述**：model_description 中需要包含拍摄场景的描述（如"在客厅""浴室背景"等）
- 如果用户只提到了部分维度（例如只提到产品没提到人物），你需要根据产品类型和使用场景**合理推断**缺失的维度
- 推断要合理：化妆品搭配年轻女性 + 浴室/卧室，食品搭配美食博主 + 厨房，等等
- 如果用户没有提到场景，自动补充一个合适的室内家居场景到 model_description 中

### 输出要求
- item_description: 提取或推断出的产品描述，用于后续 ADA 物品分析
- model_description: 提取或推断出的人物描述 + 场景信息，用于后续 ADA 人物创建（场景会自动从中提取）
- 每个描述都应该是一段简短的自然语言（1-2 句话），足以让后续的 ADA 各模式理解并展开

## Reference

### 示例 1
输入："帮我拍一个亚洲女生在浴室推荐氨基酸洗面奶的 vlog"
输出：
- item_description: "氨基酸洗面奶，温和配方"
- model_description: "亚洲女生，适合美妆vlog出镜，亲和自然，在浴室场景中拍摄"

### 示例 2
输入："拍一个推荐这本悬疑小说的视频"
输出：
- item_description: "悬疑小说，需要结合图片判断具体书名和内容"
- model_description: "文艺气质的年轻人，适合书籍推荐类vlog，在温馨书房中拍摄，有书架和柔和灯光"（推断）

## 输出格式
严格按照 JSON Schema 输出。
"""


def build_quickstart_prompt(user_sentence: str) -> str:
    """构建一句话快速拆解的用户提示词（v10：场景融入人物）"""
    return f"""请从以下一句话描述中拆解出物品和人物（含场景）两类素材信息：

【用户描述】
{user_sentence}

请输出拆解结果 JSON。场景信息需融入 model_description 中。如果用户附带了产品图片，请结合图片信息一起分析。
"""


def get_quickstart_schema() -> dict:
    """一句话拆解 JSON Schema（v10：无独立 scene_description，场景融入 model_description）"""
    return {
        "type": "OBJECT",
        "properties": {
            "item_description": {"type": "STRING", "description": "提取/推断的产品描述"},
            "model_description": {
                "type": "STRING",
                "description": "提取/推断的人物描述（需包含场景信息，如'亚洲女生，在客厅中拍摄'）",
            },
        },
        "required": ["item_description", "model_description"],
    }

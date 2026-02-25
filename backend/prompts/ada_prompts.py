"""
ADA Agent 提示词模板
素材设计师（Asset Designer Agent）三套 prompt：物品 / 人物 / 场景
v5 架构：智能问卷 + P0/P1/P2 卖点优先级
"""

# ========== 物品模式 — 第 1 步：分析 + 生成问卷 ==========

ADA_ITEM_ANALYZE_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**物品模式 — 分析阶段**。

## Task

分析用户提供的产品图片和描述，完成以下工作：
1. 识别产品类型，判断是否为可处理的小型产品（small/large）
2. 按 P0/P1/P2 优先级梳理该产品的特征与卖点
3. 为每个信息维度执行「AI 预填 or 生成问题」的决策
4. 输出一份智能问卷，供用户确认和补充

## Context

### 卖点优先级规则

| 优先级 | 含义 | 收集策略 |
|--------|------|----------|
| P0 | 核心卖点，视频必须重点展示 | 优先收集。无法自信推断时，必须主动询问用户 |
| P1 | 辅助卖点，增强说服力 | AI 预填为主，用户可修改 |
| P2 | 锦上添花信息 | AI 预填，标记为可选 |

### 信息收集规则
- 向用户提出的问题控制在 5~10 个
- 优先完成 P0 等级的信息收集
- 如果你不确定某产品的 P0 卖点，第一个问题就问：「你认为这个产品最大的卖点是什么？」
- P0 信息是视频脚本的灵魂

### 参考维度（不固定，按品类灵活调整）
产品名称、产品类别、核心卖点、解决什么问题、使用人群、使用场景、使用方法、材质/品质细节、价格信息、优惠福利、售后保障、发货时间、信任背书、促单话术 ……

### 尺寸判断
- small：上半身可演示的小型产品（化妆品、书本、手机壳、饰品等）→ 允许
- large：需要全身/户外场景的产品（家具、电器、汽车等）→ 拒绝

## Reference

### 示例 1：护肤品（氨基酸洗面奶）
输入："氨基酸洗面奶，温和不紧绷"
分析结果：
- P0: 氨基酸温和配方(ai预填), 洗后不紧绷(ai预填), 适合敏感肌(ai预填)
- P1: 使用方法(问用户), 泡沫质地(问用户), 价格信息(问用户)
- P2: 品牌故事(可选), 发货时间(可选)

### 示例 2：书籍
输入："东野圭吾新作，悬疑推理"
分析结果：
- P0: 作者知名度(ai预填), 类型题材(ai预填), 故事钩子(问用户)
- P1: 适合读者群(ai预填), 页数(问用户)
- P2: 价格(可选), 是否限量版(可选)
注意：书不需要"使用方法""材质"，但需要"内容简介""作者背景"

### 示例 3：食品
输入："手工曲奇，黄油味超浓"
分析结果：
- P0: 手工制作(ai预填), 黄油味浓郁(ai预填), 口感描述(问用户)
- P1: 配料亮点(问用户), 保质期(问用户)
- P2: 包装(可选), 价格(可选)
注意：食品不需要"使用方法"，但需要"口味""保质期"

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
                "description": "问卷字段列表",
                "items": {
                    "type": "OBJECT",
                    "properties": {
                        "key": {"type": "STRING", "description": "字段标识"},
                        "label": {"type": "STRING", "description": "显示标签"},
                        "value": {"type": "STRING", "description": "AI 预填值（空字符串表示待用户填写）"},
                        "priority": {"type": "STRING", "description": "P0/P1/P2"},
                        "source": {"type": "STRING", "description": "ai 或 user"},
                        "required": {"type": "BOOLEAN", "description": "是否必填"},
                    },
                    "required": ["key", "label", "value", "priority", "source", "required"],
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

用户已经确认或修改了之前 AI 预填的问卷内容，现在你需要：
1. 整合所有确认后的信息
2. 生成一段完整的产品描述（150-250字），突出 P0 卖点
3. 提取核心卖点（P0 第一条）作为 selling_point
4. 描述要适合后续视频脚本使用，突出视觉特征和使用动作

## 输出格式
严格按照 JSON Schema 输出。
"""


def build_item_confirm_prompt(confirmed_fields: list[dict], selling_points: dict) -> str:
    """构建物品确认的用户提示词（第 2 步）"""
    fields_text = ""
    for f in confirmed_fields:
        fields_text += f"- {f['label']}：{f['value']}（{f['priority']}）\n"

    p0_text = "、".join(selling_points.get("P0", []))

    return f"""用户已确认以下产品信息，请生成最终产品档案：

【确认后的产品信息】
{fields_text}

【核心卖点（P0）】
{p0_text}

请整合以上信息，生成完整的产品档案 JSON。
"""


def get_item_confirm_schema() -> dict:
    """物品确认 JSON Schema（第 2 步）"""
    return {
        "type": "OBJECT",
        "properties": {
            "usage": {"type": "STRING", "description": "使用方式描述"},
            "selling_point": {"type": "STRING", "description": "核心卖点一句话（取 P0 第一条）"},
            "full_description": {"type": "STRING", "description": "完整产品描述 150-250 字"},
        },
        "required": ["usage", "selling_point", "full_description"],
    }


# ========== 物品模式 — 图片生成 ==========

ADA_ITEM_IMAGE_PROMPT = """请根据以下产品信息生成一张产品说明图：

产品名称：{name}
产品描述：{full_description}
核心卖点：{selling_point}

要求：
- 图片风格：清晰的产品功能说明图，类似小红书种草笔记的产品图
- 展示产品外观 + 关键卖点标注
- 背景干净简洁，白色或浅色
- 适合在视频中作为产品介绍画面使用
"""


# ========== 兼容旧版（直接创建模式）==========

ADA_ITEM_SYSTEM_PROMPT = ADA_ITEM_ANALYZE_SYSTEM_PROMPT  # 兼容旧引用


def build_item_analysis_prompt(product_description: str) -> str:
    """兼容旧版：直接分析模式"""
    return build_item_analyze_prompt(product_description)


def get_item_response_schema() -> dict:
    """兼容旧版 Schema"""
    return get_item_analyze_schema()


# ========== 人物模式 ==========

ADA_MODEL_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**人物模式**。

## Task

根据用户提供的参考图或描述，拓展出完整的 vlog 模特人设档案。

## Context

输出字段：
1. name：人物标签（简短，如"邻家短发女生"、"清冷御姐"）
2. appearance：完整的外貌描述（年龄范围、性别、发型发色、脸型五官、肤色、身材）
3. personality：气质性格（如"亲和活泼"、"知性优雅"、"酷飒干练"）
4. outfits：穿搭描述（提供 2-3 套适合 vlog 拍摄的穿搭方案）
5. full_description：完整的人设描述（150-250字），适合作为图片生成的详细提示词

规则：
- 人设要适合 vlog 带货场景，亲和力强，符合目标受众审美
- 描述要具体、可视化，能让图片生成模型准确还原
- 穿搭要实际、不过于夸张，适合日常 vlog 风格

## Reference

输入示例："20 多岁亚洲女生，短发，邻家感，日常穿搭"
输出：name="邻家短发女生", appearance="20-25岁亚洲女性，短发及肩..."

## 输出格式
严格按照 JSON Schema 输出。
"""

ADA_MODEL_IMAGE_PROMPT = """请根据以下人物设定生成造型图：

人物描述：{full_description}
外貌：{appearance}
穿搭：{outfits}

要求：
- 生成该人物的半身正面照
- 真人写实风格，像手机拍摄的自然照片
- 表情自然亲和，适合 vlog 出镜
- 光线明亮柔和，背景干净
- 展示穿搭和整体气质
"""


def build_model_analysis_prompt(model_description: str) -> str:
    """构建人物分析的用户提示词"""
    return f"""请根据以下描述拓展完整的 vlog 模特人设：

【用户描述】
{model_description}

请输出完整的人设档案 JSON。如果用户提供了参考图，请以参考图的外貌为基准进行描述。
"""


def get_model_response_schema() -> dict:
    """人物档案 JSON Schema"""
    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "人物标签"},
            "appearance": {"type": "STRING", "description": "外貌描述"},
            "personality": {"type": "STRING", "description": "气质性格"},
            "outfits": {"type": "STRING", "description": "穿搭描述"},
            "full_description": {"type": "STRING", "description": "完整人设描述"},
        },
        "required": ["name", "appearance", "personality", "outfits", "full_description"],
    }


# ========== 场景模式 ==========

ADA_SCENE_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**场景模式**。

## Task

根据用户提供的参考图或描述，丰富出完整的 vlog 拍摄场景档案。

## Context

输出字段：
1. name：场景名称（简短，如"白色简约浴室"、"ins 风卧室"）
2. environment：环境描述（空间布局、主要家具/物品、颜色、材质）
3. lighting：光线描述（自然光/灯光、方向、强度、色温）
4. mood：氛围描述（如"干净清爽"、"温馨慵懒"、"专业高级"）
5. full_description：完整的场景描述（150-250字），适合作为图片生成的详细提示词

规则：
- 场景要适合 vlog 自拍拍摄，空间不宜太大
- 优先室内场景（浴室、卧室、客厅、书房、厨房等）
- 描述要具体、可视化，包含关键视觉元素
- 光线描述要利于画面美观

## Reference

输入示例："明亮的浴室，白色系，有镜子"
输出：name="白色简约浴室", environment="白色大理石瓷砖，圆形背光镜..."

## 输出格式
严格按照 JSON Schema 输出。
"""

ADA_SCENE_IMAGE_PROMPT = """请根据以下场景设定生成场景图：

场景描述：{full_description}
环境：{environment}
光线：{lighting}
氛围：{mood}

要求：
- 生成该场景的室内全景
- 真人写实风格，像手机拍摄的实景照片
- 适合作为 vlog 拍摄背景
- 光线自然美观
- 无人出镜，仅展示空间环境
"""


def build_scene_analysis_prompt(scene_description: str) -> str:
    """构建场景分析的用户提示词"""
    return f"""请根据以下描述丰富完整的 vlog 拍摄场景：

【用户描述】
{scene_description}

请输出完整的场景档案 JSON。如果用户提供了参考图，请以参考图的场景为基准进行描述。
"""


def get_scene_response_schema() -> dict:
    """场景档案 JSON Schema"""
    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "场景名称"},
            "environment": {"type": "STRING", "description": "环境描述"},
            "lighting": {"type": "STRING", "description": "光线描述"},
            "mood": {"type": "STRING", "description": "氛围描述"},
            "full_description": {"type": "STRING", "description": "完整场景描述"},
        },
        "required": ["name", "environment", "lighting", "mood", "full_description"],
    }

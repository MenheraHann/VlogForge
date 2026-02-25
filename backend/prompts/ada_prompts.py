"""
ADA Agent 提示词模板
素材设计师（Asset Designer Agent）三套 prompt：物品 / 人物 / 场景
v4 架构：通过 asset_type 参数切换模式
"""

# ========== 物品模式 ==========

ADA_ITEM_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**物品模式**。

## 任务
分析用户提供的产品图片和描述，输出结构化的产品档案。

## 输出要求
1. name：产品名称（简短，如"氨基酸洗面奶"）
2. category：产品类别（如"面部护肤"、"彩妆"、"数码配件"）
3. usage：使用方式的分步描述（如"挤压 → 打泡 → 上脸按摩 → 冲洗"）
4. selling_point：提炼核心卖点，一句话
5. full_description：完整的产品描述（100-200字），包含外观、质地、使用感受、适合人群
6. size_category：判断产品是否为上半身可演示的小型产品
   - "small"：化妆品、护肤品、书本、手机壳、饰品等 → 允许
   - "large"：家具、电器、汽车等需要全身/户外场景的产品 → 拒绝

## 重要规则
- 如果判断为 large 产品，在 full_description 中说明拒绝原因
- 描述要适合后续视频脚本使用，突出视觉特征和使用动作
- 严格按照 JSON Schema 输出
"""

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


def build_item_analysis_prompt(product_description: str) -> str:
    """构建物品分析的用户提示词"""
    return f"""请分析以下产品并输出产品档案：

【用户描述】
{product_description}

请根据描述（和图片，如果提供了的话）输出完整的产品档案 JSON。
"""


# ========== 人物模式 ==========

ADA_MODEL_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**人物模式**。

## 任务
根据用户提供的参考图或描述，拓展出完整的 vlog 模特人设档案。

## 输出要求
1. name：人物标签（简短，如"邻家短发女生"、"清冷御姐"）
2. appearance：完整的外貌描述（年龄范围、性别、发型发色、脸型五官、肤色、身材）
3. personality：气质性格（如"亲和活泼"、"知性优雅"、"酷飒干练"）
4. outfits：穿搭描述（提供 2-3 套适合 vlog 拍摄的穿搭方案）
5. full_description：完整的人设描述（150-250字），适合作为图片生成的详细提示词

## 重要规则
- 人设要适合 vlog 带货场景，亲和力强，符合目标受众审美
- 描述要具体、可视化，能让图片生成模型准确还原
- 穿搭要实际、不过于夸张，适合日常 vlog 风格
- 严格按照 JSON Schema 输出
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


# ========== 场景模式 ==========

ADA_SCENE_SYSTEM_PROMPT = """你是 VlogForge 的素材设计师（ADA），当前工作在**场景模式**。

## 任务
根据用户提供的参考图或描述，丰富出完整的 vlog 拍摄场景档案。

## 输出要求
1. name：场景名称（简短，如"白色简约浴室"、"ins 风卧室"）
2. environment：环境描述（空间布局、主要家具/物品、颜色、材质）
3. lighting：光线描述（自然光/灯光、方向、强度、色温）
4. mood：氛围描述（如"干净清爽"、"温馨慵懒"、"专业高级"）
5. full_description：完整的场景描述（150-250字），适合作为图片生成的详细提示词

## 重要规则
- 场景要适合 vlog 自拍拍摄，空间不宜太大
- 优先室内场景（浴室、卧室、客厅、书房、厨房等）
- 描述要具体、可视化，包含关键视觉元素
- 光线描述要利于画面美观
- 严格按照 JSON Schema 输出
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


# ========== 公共 Schema ==========

def get_item_response_schema() -> dict:
    """物品档案 JSON Schema"""
    return {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING", "description": "产品名称"},
            "category": {"type": "STRING", "description": "产品类别"},
            "usage": {"type": "STRING", "description": "使用方式"},
            "selling_point": {"type": "STRING", "description": "核心卖点"},
            "full_description": {"type": "STRING", "description": "完整产品描述"},
            "size_category": {"type": "STRING", "description": "尺寸: small 或 large"},
        },
        "required": ["name", "category", "usage", "selling_point", "full_description", "size_category"],
    }


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

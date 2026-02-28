"""
年龄保护工具
检测文本中的年龄引用，若低于最低年龄限制则自动调整为替换年龄。
用于确保图片生成提示词中的人物年龄合规。
"""

import re
import logging

logger = logging.getLogger(__name__)

# 年龄匹配正则：覆盖常见英文/中文年龄表达
# 英文：XX-year-old, XX years old, age XX, aged XX
# 中文：XX岁, XX 岁
_AGE_PATTERNS = [
    # "XX-year-old" (连字符格式，如 "16-year-old")
    (re.compile(r'(\d{1,3})-year-old', re.IGNORECASE), '{age}-year-old'),
    # "XX years old" (空格格式，如 "16 years old")
    (re.compile(r'(\d{1,3})\s+years?\s+old', re.IGNORECASE), '{age} years old'),
    # "age XX" / "aged XX" (如 "age 16", "aged 16")
    (re.compile(r'(age[d]?)\s+(\d{1,3})', re.IGNORECASE), r'\1 {age}'),
    # "XX岁" / "XX 岁" (中文年龄表达)
    (re.compile(r'(\d{1,3})\s*岁'), '{age}岁'),
]


def enforce_minimum_age(
    text: str,
    min_age: int = 18,
    replacement_age: int = 19,
) -> str:
    """
    检测文本中的年龄引用，若低于 min_age 则替换为 replacement_age。

    参数:
        text: 输入文本（提示词/描述）
        min_age: 最低允许年龄（默认 18）
        replacement_age: 替换年龄（默认 19）

    返回:
        处理后的文本
    """
    if not text:
        return text

    result = text

    for pattern, template in _AGE_PATTERNS:
        def _replace_match(match, tmpl=template):
            """替换匹配到的年龄（仅当年龄 < min_age 时替换）"""
            # 提取数字部分（不同模式中数字在不同分组位置）
            groups = match.groups()
            # 找到数字分组
            age_str = None
            for g in groups:
                if g and g.isdigit():
                    age_str = g
                    break
            if age_str is None:
                return match.group(0)

            original_age = int(age_str)
            if original_age >= min_age:
                return match.group(0)  # 年龄合规，不替换

            # 年龄低于限制，执行替换
            logger.warning(
                f"[AgeGuard] 年龄从 {original_age} 调整为 {replacement_age}"
            )

            # 根据模板格式进行替换
            if r'\1' in tmpl:
                # 模板含反向引用（如 "age XX" 模式）
                new_text = tmpl.replace('{age}', str(replacement_age))
                # 手动处理反向引用
                for i, g in enumerate(groups, 1):
                    new_text = new_text.replace(f'\\{i}', g if g else '')
                return new_text
            else:
                return tmpl.format(age=replacement_age)

        result = pattern.sub(_replace_match, result)

    return result

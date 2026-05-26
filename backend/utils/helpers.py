"""
工具函数模块。
"""

import re
from typing import List


def extract_keywords(text: str, max_count: int = 10) -> List[str]:
    """从文本中提取关键词"""
    words = re.findall(r"[\u4e00-\u9fa5a-zA-Z0-9]{2,}", text)
    word_freq = {}
    for w in words:
        if len(w) >= 2:
            word_freq[w] = word_freq.get(w, 0) + 1
    return [w for w, _ in sorted(word_freq.items(), key=lambda x: x[1], reverse=True)[:max_count]]


def truncate_text(text: str, max_length: int = 200) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."

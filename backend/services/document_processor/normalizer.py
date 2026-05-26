import re
from typing import Optional


def normalize_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\t ]+", " ", text)
    lines = [line.rstrip() for line in text.split("\n")]
    return "\n".join(lines).strip()


def merge_broken_lines(text: str) -> str:
    lines = normalize_text(text).split("\n")
    merged = []
    buffer = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            if buffer:
                merged.append(buffer.strip())
                buffer = ""
            merged.append("")
            continue
        if not buffer:
            buffer = line
            continue
        if _should_join(buffer, line):
            buffer += " " + line
        else:
            merged.append(buffer.strip())
            buffer = line
    if buffer:
        merged.append(buffer.strip())
    return "\n".join(merged).strip()


def detect_language(text: str) -> str:
    text = text or ""
    zh = len(re.findall(r"[一-鿿]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    if zh and zh >= en * 0.2:
        return "zh"
    return "en" if en else "unknown"


def compact_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _should_join(prev: str, current: str) -> bool:
    if prev.endswith(("。", "！", "？", ".", "!", "?", ":", "：", "；", ";")):
        return False
    if re.match(r"^(#{1,6}\s+|[-*+]\s+|\d+(?:\.\d+)*[.)、]?\s+)", current):
        return False
    normalized_current = current.replace("（", "(").replace("）", ")")
    if re.match(r"^(第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|[一二三四五六七八九十百]+[、.]|[（(][一二三四五六七八九十百]+[）)])\s*", normalized_current):
        return False
    if re.match(r"^\|.*\|$", prev) or re.match(r"^\|.*\|$", current):
        return False
    if len(prev) < 24 and re.match(r"^[A-Z一-鿿][^。！？.!?]{0,60}$", prev):
        return False
    return True

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from statistics import median
from typing import List


@dataclass
class PdfLayoutLine:
    text: str
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    size: float
    bold: bool = False
    centered: bool = False
    repeated: bool = False


def extract_layout_lines(data: bytes) -> List[PdfLayoutLine]:
    try:
        import fitz
    except Exception:
        return []

    try:
        doc = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return []

    lines: List[PdfLayoutLine] = []
    try:
        for page_index, page in enumerate(doc, start=1):
            width = float(page.rect.width or 0)
            page_dict = page.get_text("dict")
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    spans = [span for span in line.get("spans", []) if str(span.get("text") or "").strip()]
                    if not spans:
                        continue
                    text = _normalize_line_text("".join(str(span.get("text") or "") for span in spans))
                    if not text:
                        continue
                    x0 = min(float(span.get("bbox", [0, 0, 0, 0])[0]) for span in spans)
                    top = min(float(span.get("bbox", [0, 0, 0, 0])[1]) for span in spans)
                    x1 = max(float(span.get("bbox", [0, 0, 0, 0])[2]) for span in spans)
                    bottom = max(float(span.get("bbox", [0, 0, 0, 0])[3]) for span in spans)
                    sizes = [float(span.get("size") or 0) for span in spans if span.get("size")]
                    fonts = " ".join(str(span.get("font") or "") for span in spans).lower()
                    center = (x0 + x1) / 2 if width else 0
                    lines.append(
                        PdfLayoutLine(
                            text=text,
                            page=page_index,
                            x0=x0,
                            x1=x1,
                            top=top,
                            bottom=bottom,
                            size=max(sizes) if sizes else 0,
                            bold="bold" in fonts or "black" in fonts or "heavy" in fonts,
                            centered=bool(width and abs(center - width / 2) < width * 0.12),
                        )
                    )
    finally:
        doc.close()

    _mark_repeated_lines(lines)
    return lines


def build_layout_aware_text(lines: List[PdfLayoutLine], processor) -> str:
    if not lines:
        return ""
    body_size = _median_positive([line.size for line in lines if not line.repeated])
    headings = [_is_layout_heading(line, body_size, processor) for line in lines]
    output: List[str] = []
    recent_heading_keys: list[str] = []
    for index, line in enumerate(lines):
        if _should_skip_line(line):
            continue
        is_heading = headings[index]
        if is_heading:
            key = _heading_key(line.text)
            if key and key in recent_heading_keys[-6:]:
                continue
            if key:
                recent_heading_keys.append(key)
            if output and output[-1] != "":
                output.append("")
            output.append(_normalize_heading_text(line.text))
            output.append("")
            continue
        output.append(line.text)
    return "\n".join(output)


def _is_layout_heading(line: PdfLayoutLine, body_size: float, processor) -> bool:
    text = line.text.strip()
    if _should_skip_line(line):
        return False
    if not processor._looks_like_pdf_heading(text):
        return False
    if _looks_like_list_item_heading(text):
        return False
    if processor._looks_like_numbered_heading(text):
        title = re.sub(
            r"^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|[一二三四五六七八九十百]+[、.]|\([一二三四五六七八九十百]+\)|\d+(?:\.\d+){0,3}[.)、]?)\s*",
            "",
            text.replace("（", "(").replace("）", ")"),
        )
        if _looks_like_running_text(title):
            return False
        if re.search(r"\b\d+(?:\.\s*\d+)+\s*文献", title):
            return False
        if len(title) <= 45:
            return True
    if body_size and line.size >= body_size + 0.8 and (line.bold or line.centered):
        return len(text) <= 60 and not _looks_like_running_text(text)
    if line.bold and len(text) <= 45:
        return not _looks_like_running_text(text)
    if line.centered and len(text) <= 32 and processor._looks_like_pdf_heading(text):
        return True
    return False


def _should_skip_line(line: PdfLayoutLine) -> bool:
    text = line.text.strip()
    if not text:
        return True
    if line.repeated:
        return True
    if re.fullmatch(r"\[?\d+\]?\s+[A-Z][A-Z\s]+", text):
        return True
    if re.fullmatch(r"[-—·\s]*\d+\s*[-—·\s]*", text):
        return True
    if re.match(r"^page\s+\d+\b", text, re.I):
        return True
    if re.search(r"\b(issn|cn\s*\d|doi)\b", text, re.I):
        return True
    if re.match(r"^\d+(?:\.\d+)?\s*万", text):
        return True
    if re.match(r"^\d{4}\s+", text):
        return True
    if re.match(r"^\d+(?:\.\s*\d+)+\s*文献", text):
        return True
    if re.match(r"^(?:19|20)\d{2}\s*评测任务", text):
        return True
    if re.search(r"\b10\.\d{4,9}\s*/", text):
        return True
    if re.match(r"^\d+[*＊]?\s*[，,]", text):
        return True
    if re.match(r"^\d{5,6}\s*[;；,，]?\s*\d*\.?\s*", text) and re.search(r"(?:大学|学院|医院|研究院|省|市|区|县)", text):
        return True
    if re.search(r"[<>≤≥]|\d+\s*%", text):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9.\s]{2,}", text) and text.lower() not in {"abstract", "references"}:
        return True
    if text.endswith(("。", ".")) and not re.match(r"^(?:\d+(?:\.\d+){0,3}|[一二三四五六七八九十]+[、.])\s*", text):
        return True
    if re.match(r"^[（(]\d+[）)]", text):
        return True
    if re.match(r"^\d+\.\s*[^\d\s].{0,120}\d{6}(?:[;；,，]|$)", text):
        return True
    if re.match(r"^\d+\.\s*(?:[^\d\s].{0,120})?(?:大学|学院|研究院|自治区|省|市|区|县|镇)", text):
        return True
    if re.search(r"(?:大学|学院|研究院|自治区|省|市|区|县|镇).{0,60}\d{6}", text):
        return True
    if text.lower() in {"model", "models", "method", "methods", "results", "experiments", "evaluation"}:
        return True
    if re.match(r"^\d+(?:\.\s*\d+)?\s*[，,、%％]", text):
        return True
    if re.match(r"^\d+\s*本[、，,]", text):
        return True
    if re.match(r"^\d+[^\s]*(?:试验箱|环境|系统|方法|模型|算法)", text):
        return True
    if re.search(r"\b\d+(?:\.\d+)?\s*[kK万%％]\b", text):
        return True
    if re.match(r"^\d{1,3}[］\]]\.\s*(?:https?[:：]//|www\.|[A-Za-z]+\.)", text, re.I):
        return True
    if _looks_like_list_item_heading(text):
        return True
    return False


def _mark_repeated_lines(lines: List[PdfLayoutLine]) -> None:
    pages = {line.page for line in lines}
    if len(pages) < 3:
        return
    buckets: dict[str, set[int]] = defaultdict(set)
    for line in lines:
        key = _repeat_key(line.text)
        if key:
            buckets[key].add(line.page)
    repeated_keys = {key for key, page_set in buckets.items() if len(page_set) >= max(3, int(len(pages) * 0.35))}
    for line in lines:
        if _repeat_key(line.text) in repeated_keys:
            line.repeated = True


def _repeat_key(text: str) -> str:
    text = re.sub(r"\d+", "#", text.lower())
    text = re.sub(r"[^a-z#一-鿿]+", "", text)
    return text if len(text) >= 4 else ""


def _normalize_line_text(text: str) -> str:
    text = (text or "").replace("ﬁ", "fi").replace("ﬂ", "fl")
    text = text.replace("﻿", "").replace("　", " ").replace("ﾠ", " ")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"([一-鿿])\s+([一-鿿])", r"\1\2", text)
    return text


def _normalize_heading_text(text: str) -> str:
    text = _normalize_line_text(text)
    text = re.sub(r"^(第\s*[一二三四五六七八九十百]+\s*章)\s+", r"\1 ", text)
    text = re.sub(r"^(\d+(?:\.\s*\d+)*)\s*", lambda m: m.group(1).replace(" ", "") + " ", text)
    return text.strip()


def _heading_key(text: str) -> str:
    text = _normalize_heading_text(text).lower()
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[^a-z0-9一-鿿]+", "", text)
    if not text:
        return ""
    half = len(text) // 2
    if half >= 4 and text[:half] == text[half:]:
        text = text[:half]
    return text


def _looks_like_running_text(text: str) -> bool:
    if re.search(r"[，。；：,;:]", text):
        return True
    if len(text) > 45:
        return True
    return False


def _looks_like_list_item_heading(text: str) -> bool:
    stripped = (text or "").strip()
    if re.match(r"^(?:[（(]?\d+[）)]|\d+\.)\s*", stripped) and re.search(r"[，。：；,;:]", stripped):
        return True
    if re.match(r"^\d+\.\s*", stripped) and len(stripped) > 35:
        return True
    return False


def _median_positive(values: List[float]) -> float:
    positives = [value for value in values if value > 0]
    return float(median(positives)) if positives else 0.0

import csv
import html
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from statistics import mean
from typing import Any, Dict, List, Optional, Tuple

from services.document_processor.chunker import TypeAwareChunker
from services.document_processor.models import ParsedBlock, ParsedDocument
from services.document_processor.normalizer import detect_language, merge_broken_lines, normalize_text
from services.document_processor.paper_chunker import enrich_block_metadata, extract_paper_metadata, infer_section_type
from services.document_processor.pdf_layout import build_layout_aware_text, extract_layout_lines
from services.document_processor.table_parser import html_table_to_markdown, markdown_table_lines


@dataclass
class PdfParseQuality:
    score: float
    heading_count: int
    noise_heading_count: int
    section_type_count: int
    max_block_len: int
    avg_block_len: float
    short_block_ratio: float
    content_len: int
    body_len_ratio: float
    chunk_count: int
    max_chunk_len: int
    chunk_type_count: int
    section_order_score: float
    heading_hierarchy_score: float
    rejection_reasons: List[str]


class DocumentProcessor:
    """把不同来源文档转成统一 ParsedBlock。"""

    def process(
        self,
        title: str,
        content: str,
        source: str = "manual",
        file_type: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        file_type = (file_type or self._guess_file_type(source, content)).lower()
        if file_type == "csv":
            return self.process_csv(title, content, source, metadata=metadata)
        if file_type == "docx":
            return self.process_docx(title, content, source, metadata=metadata)
        if file_type == "xlsx":
            return self.process_xlsx(title, content, source, metadata=metadata)
        if file_type == "pdf":
            return self.process_pdf(title, content, source, metadata=metadata)
        if file_type in {"md", "markdown"} or self._looks_like_markdown(content):
            return self.process_markdown(title, content, source, file_type="md", metadata=metadata)
        if file_type in {"html", "htm"} or self._looks_like_html(content):
            return self.process_html(title, content, source, metadata=metadata)
        return self.process_text(title, content, source, file_type=file_type or "text", metadata=metadata)

    def process_text(
        self,
        title: str,
        content: str,
        source: str = "manual",
        file_type: str = "text",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        raw_text = self._decode_maybe_bytes(content)
        toc_headings = self._extract_toc_headings(raw_text) if file_type == "pdf" else []
        text = merge_broken_lines(content) if file_type != "pdf" else self._normalize_pdf_text(raw_text, toc_headings)
        if file_type == "pdf":
            text = merge_broken_lines(text)
        paper_meta = extract_paper_metadata(title, text)
        doc_meta = {**paper_meta, **(metadata or {}), "language": detect_language(text)}
        if toc_headings:
            doc_meta["toc_headings"] = [item[0] for item in toc_headings]
        blocks: List[ParsedBlock] = []
        section_path = ""
        order = 0
        for part in re.split(r"\n\s*\n", text):
            item = part.strip()
            if not item:
                continue
            if file_type == "pdf" and self._is_toc_block(item):
                continue
            heading = self._plain_heading(item, toc_headings if file_type == "pdf" else None)
            if file_type == "pdf" and toc_headings and heading and not self._should_keep_pdf_heading(item, heading, toc_headings):
                heading = ""
            if heading:
                section_path = heading
                section_type, block_meta = enrich_block_metadata(section_path, "", doc_meta)
                block_meta["from_toc"] = any(self._heading_similarity(heading, candidate) >= 0.88 for candidate, _ in toc_headings)
                blocks.append(ParsedBlock(f"b{order}", "heading", heading, order, section_path=section_path, metadata=block_meta))
                order += 1
                continue
            block_type, block_meta = enrich_block_metadata(section_path, item, doc_meta)
            blocks.append(ParsedBlock(f"b{order}", block_type, item, order, section_path=section_path, metadata=block_meta))
            order += 1
        if not blocks and text:
            block_type, block_meta = enrich_block_metadata("", text, doc_meta)
            blocks.append(ParsedBlock("b0", block_type, text, 0, metadata=block_meta))
        return ParsedDocument(title=title, source=source, file_type=file_type, metadata=doc_meta, blocks=blocks)

    def process_markdown(
        self,
        title: str,
        content: str,
        source: str = "manual",
        file_type: str = "md",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        text = normalize_text(content)
        paper_meta = extract_paper_metadata(title, text)
        doc_meta = {**paper_meta, **(metadata or {}), "language": detect_language(text)}
        blocks: List[ParsedBlock] = []
        section_stack: List[str] = []
        paragraph: List[str] = []
        table: List[str] = []
        code: List[str] = []
        in_code = False
        code_lang = ""
        order = 0

        def section_path() -> str:
            return " / ".join(section_stack)

        def add_block(block_type: str, block_text: str, extra: Optional[Dict[str, Any]] = None):
            nonlocal order
            if not block_text.strip():
                return
            resolved_type, block_meta = enrich_block_metadata(section_path(), block_text, doc_meta)
            if block_type not in {"paragraph", "heading"}:
                resolved_type = block_type
                block_meta["section_type"] = block_type
            if extra:
                block_meta.update(extra)
            blocks.append(ParsedBlock(f"b{order}", resolved_type, block_text.strip(), order, section_path=section_path(), metadata=block_meta))
            order += 1

        def flush_paragraph():
            nonlocal paragraph
            if paragraph:
                add_block("paragraph", "\n".join(paragraph))
                paragraph = []

        def flush_table():
            nonlocal table
            if table:
                add_block("table", markdown_table_lines(table))
                table = []

        lines = text.split("\n")
        for line in lines:
            stripped = line.strip()
            fence = re.match(r"^```\s*([A-Za-z0-9_+.-]*)", stripped)
            if fence:
                if not in_code:
                    flush_paragraph()
                    flush_table()
                    in_code = True
                    code_lang = fence.group(1) or ""
                    code = []
                else:
                    add_block("code", "\n".join(code), {"code_language": code_lang})
                    in_code = False
                    code_lang = ""
                    code = []
                continue
            if in_code:
                code.append(line)
                continue
            heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
            if heading:
                flush_paragraph()
                flush_table()
                level = len(heading.group(1))
                heading_text = heading.group(2).strip()
                section_stack[:] = section_stack[: level - 1] + [heading_text]
                _, block_meta = enrich_block_metadata(section_path(), heading_text, doc_meta)
                block_meta["heading_level"] = level
                blocks.append(ParsedBlock(f"b{order}", "heading", heading_text, order, section_path=section_path(), metadata=block_meta))
                order += 1
                continue
            if self._is_markdown_table_line(stripped):
                flush_paragraph()
                table.append(stripped)
                continue
            if table and not self._is_markdown_table_line(stripped):
                flush_table()
            if stripped:
                paragraph.append(stripped)
            else:
                flush_paragraph()
        if in_code and code:
            add_block("code", "\n".join(code), {"code_language": code_lang})
        flush_table()
        flush_paragraph()
        return ParsedDocument(title=title, source=source, file_type=file_type, metadata=doc_meta, blocks=blocks)

    def process_html(
        self,
        title: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        cleaned = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<nav[\s\S]*?</nav>|<footer[\s\S]*?</footer>", "\n", content or "", flags=re.I)
        tokens = re.findall(r"<h[1-6][\s\S]*?</h[1-6]>|<table[\s\S]*?</table>|<pre[\s\S]*?</pre>|<p[\s\S]*?</p>|<li[\s\S]*?</li>", cleaned, flags=re.I)
        markdown_lines = []
        for token in tokens:
            lower = token.lower()
            if lower.startswith("<h"):
                level = re.match(r"<h([1-6])", lower).group(1)
                markdown_lines.append("#" * int(level) + " " + self._strip_html(token))
            elif lower.startswith("<table"):
                markdown_lines.append(html_table_to_markdown(token))
            elif lower.startswith("<pre"):
                markdown_lines.append("```\n" + self._strip_html(token) + "\n```")
            else:
                markdown_lines.append(self._strip_html(token))
                markdown_lines.append("")
        if not markdown_lines:
            text = self._strip_html(cleaned)
            return self.process_text(title, text, source, file_type="html", metadata=metadata)
        return self.process_markdown(title, "\n".join(markdown_lines), source, file_type="html", metadata=metadata)

    def process_csv(
        self,
        title: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        text = self._decode_maybe_bytes(content)
        rows = list(csv.reader(io.StringIO(text)))
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        markdown = f"# {title}\n\n## Table\n\n{self._rows_to_markdown(rows)}" if rows else f"# {title}"
        doc = self.process_markdown(title, markdown, source, file_type="csv", metadata=metadata)
        doc.metadata["row_count"] = max(len(rows) - 1, 0)
        doc.metadata["sheet_count"] = 1
        return doc

    def process_docx(
        self,
        title: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        data = self._content_to_bytes(content)
        markdown = self._docx_to_markdown(data)
        return self.process_markdown(title, markdown or f"# {title}", source, file_type="docx", metadata=metadata)

    def process_xlsx(
        self,
        title: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        data = self._content_to_bytes(content)
        markdown, sheet_count = self._xlsx_to_markdown(data, title)
        doc = self.process_markdown(title, markdown, source, file_type="xlsx", metadata=metadata)
        doc.metadata["sheet_count"] = sheet_count
        return doc

    def process_pdf(
        self,
        title: str,
        content: str,
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        if isinstance(content, str) and not content.lstrip().startswith("%PDF"):
            return self.process_text(title, content, source, file_type="pdf", metadata=metadata)
        data = self._content_to_bytes(content)
        text = self._pdf_to_text(data)
        text_doc = self.process_text(title, text, source, file_type="pdf", metadata={**(metadata or {}), "pdf_parser": "text"})
        text_quality = self._score_pdf_doc(text_doc)
        if self._text_doc_good_enough_for_pdf(text_quality):
            text_doc.metadata["pdf_parser_scores"] = {
                "text": asdict(text_quality),
                "layout": None,
                "decision": "text accepted without layout",
                "reasons": ["text parser quality high enough to skip layout"],
            }
            return text_doc
        layout_lines = extract_layout_lines(data)
        layout_text = build_layout_aware_text(layout_lines, self)
        if layout_text.strip():
            layout_doc = self.process_text(title, layout_text, source, file_type="pdf", metadata={**(metadata or {}), "pdf_parser": "layout"})
            use_layout, decision = self._layout_doc_decision(text_doc, layout_doc)
            text_doc.metadata["pdf_parser_scores"] = decision
            layout_doc.metadata["pdf_parser_scores"] = decision
            if use_layout:
                return layout_doc
        else:
            text_quality = self._score_pdf_doc(text_doc)
            text_doc.metadata["pdf_parser_scores"] = {
                "text": asdict(text_quality),
                "layout": None,
                "decision": "text fallback",
                "reasons": ["layout extraction empty"],
            }
        return text_doc

    def from_content_list(
        self,
        title: str,
        content_list: List[Dict[str, Any]],
        source: str = "manual",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ParsedDocument:
        parts = []
        for item in content_list or []:
            item_type = item.get("type", "text")
            if item_type == "text":
                text = item.get("text", "")
                level = int(item.get("text_level") or 0)
                parts.append(("#" * level + " " if level else "") + text)
            elif item_type == "table":
                parts.append(str(item.get("table_body") or item.get("text") or item))
            elif item_type == "equation":
                parts.append(str(item.get("text") or item.get("latex") or item))
            elif item_type in {"image", "figure"}:
                caption = item.get("image_caption") or item.get("img_caption") or []
                parts.append("图注：" + " ".join(caption if isinstance(caption, list) else [str(caption)]))
        doc = self.process_markdown(title, "\n\n".join(parts), source, file_type="content_list", metadata=metadata)
        return doc

    def _guess_file_type(self, source: str, content: str) -> str:
        lower = (source or "").lower()
        for ext in ["md", "markdown", "html", "htm", "pdf", "docx", "xlsx", "csv"]:
            if lower.endswith("." + ext):
                return ext
        return "text"

    def _score_pdf_doc(self, doc: ParsedDocument, baseline_content_len: Optional[int] = None) -> PdfParseQuality:
        headings = [block.text for block in doc.blocks if block.type == "heading"]
        body_blocks = [block for block in doc.blocks if block.type != "heading" and block.text.strip()]
        chunker = TypeAwareChunker(max_chars=1200, overlap=120)
        chunks = chunker.chunk(doc)
        chunk_types = {chunk.chunk_type for chunk in chunks}
        section_types = {block.metadata.get("section_type") or block.type for block in doc.blocks}
        paper_sections = section_types & {"abstract", "introduction", "related_work", "method", "experiment", "conclusion", "reference"}
        noise_headings = [heading for heading in headings if self._is_layout_noise_heading(heading)]
        long_heading_count = sum(1 for heading in headings if len(heading) > 70 and infer_section_type(heading) == "paragraph")
        list_heading_count = sum(1 for heading in headings if self._looks_like_list_item_heading(heading))
        body_lengths = [len(block.text.strip()) for block in body_blocks]
        content_len = sum(body_lengths)
        max_block_len = max(body_lengths, default=0)
        avg_block_len = float(mean(body_lengths)) if body_lengths else 0.0
        short_block_ratio = (sum(1 for value in body_lengths if value < 40) / len(body_lengths)) if body_lengths else 1.0
        max_chunk_len = max((len(chunk.content) for chunk in chunks), default=0)
        body_len_ratio = (content_len / baseline_content_len) if baseline_content_len else 1.0
        noise_density = (len(noise_headings) / len(headings)) if headings else 0.0
        section_order_score = self._pdf_section_order_score(section_types)
        heading_hierarchy_score = self._pdf_heading_hierarchy_score(headings)
        rejection_reasons: List[str] = []
        if baseline_content_len and content_len < baseline_content_len * 0.45:
            rejection_reasons.append("content too short compared with text parser")
        if noise_density > 0.15:
            rejection_reasons.append("noise heading density too high")
        if not chunks:
            rejection_reasons.append("no chunks generated")
        if max_chunk_len > 6000:
            rejection_reasons.append("max chunk too long")

        score = 0.0
        score += min(len(headings), 80) * 0.22
        score += len(paper_sections) * 2.2
        score += len(chunk_types & {"abstract", "related_work", "method", "experiment", "conclusion", "reference"}) * 1.2
        score += section_order_score
        score += heading_hierarchy_score
        if chunks:
            score += min(len(chunks), 40) * 0.08
        if avg_block_len >= 80:
            score += 1.0
        if 0.04 <= short_block_ratio <= 0.45:
            score += 1.0
        score -= len(noise_headings) * 6.0
        score -= long_heading_count * 2.0
        score -= list_heading_count * 4.0
        score -= max(0, len(headings) - 120) * 0.2
        if max_block_len > 6000:
            score -= (max_block_len - 6000) / 500
        if max_chunk_len > 1800:
            score -= min(8.0, (max_chunk_len - 1800) / 500)
        if short_block_ratio > 0.55:
            score -= (short_block_ratio - 0.55) * 8.0
        if baseline_content_len and body_len_ratio < 0.65:
            score -= (0.65 - body_len_ratio) * 12.0

        return PdfParseQuality(
            score=score,
            heading_count=len(headings),
            noise_heading_count=len(noise_headings),
            section_type_count=len(paper_sections),
            max_block_len=max_block_len,
            avg_block_len=avg_block_len,
            short_block_ratio=short_block_ratio,
            content_len=content_len,
            body_len_ratio=body_len_ratio,
            chunk_count=len(chunks),
            max_chunk_len=max_chunk_len,
            chunk_type_count=len(chunk_types),
            section_order_score=section_order_score,
            heading_hierarchy_score=heading_hierarchy_score,
            rejection_reasons=rejection_reasons,
        )

    def _pdf_doc_quality(self, doc: ParsedDocument) -> float:
        return self._score_pdf_doc(doc).score

    def _text_doc_good_enough_for_pdf(self, quality: PdfParseQuality) -> bool:
        return (
            quality.score >= 35.0
            and quality.noise_heading_count == 0
            and quality.section_type_count >= 4
            and quality.heading_count >= 8
            and quality.chunk_count >= 8
            and quality.max_chunk_len <= 1700
            and quality.short_block_ratio <= 0.50
            and quality.content_len >= 3000
        )

    def _layout_doc_decision(self, text_doc: ParsedDocument, layout_doc: ParsedDocument) -> Tuple[bool, Dict[str, Any]]:
        text_len = sum(len(block.text.strip()) for block in text_doc.blocks if block.type != "heading")
        text_quality = self._score_pdf_doc(text_doc)
        layout_quality = self._score_pdf_doc(layout_doc, baseline_content_len=text_len)
        reasons: List[str] = []
        if layout_quality.rejection_reasons:
            reasons.extend(layout_quality.rejection_reasons)
        threshold = 5.0
        if text_quality.noise_heading_count >= 3 or text_quality.short_block_ratio > 0.55:
            threshold = 2.5
        if text_quality.noise_heading_count == 0 and text_quality.section_type_count >= 4 and text_quality.heading_count >= 20:
            threshold = 8.0
        layout_better = layout_quality.score >= text_quality.score + threshold
        text_is_noisy = text_quality.noise_heading_count >= 3 and layout_quality.noise_heading_count == 0
        chunk_improved = layout_quality.chunk_count <= max(45, int(text_quality.chunk_count * 0.65)) and layout_quality.max_chunk_len <= max(1800, text_quality.max_chunk_len * 1.15)
        rescue_layout = text_is_noisy and chunk_improved and layout_quality.score >= text_quality.score + 2.0
        use_layout = not layout_quality.rejection_reasons and (layout_better or rescue_layout)
        if use_layout:
            reasons.append("layout selected by multidimensional score")
            decision = "layout better"
        else:
            if not reasons:
                reasons.append("text retained by multidimensional score")
            decision = "layout rejected" if layout_quality.rejection_reasons else "text fallback"
        return use_layout, {
            "text": asdict(text_quality),
            "layout": asdict(layout_quality),
            "threshold": threshold,
            "decision": decision,
            "reasons": reasons,
        }

    def _should_use_layout_doc(self, text_doc: ParsedDocument, layout_doc: ParsedDocument) -> bool:
        return self._layout_doc_decision(text_doc, layout_doc)[0]

    def _pdf_section_order_score(self, section_types: set[str]) -> float:
        order = ["abstract", "introduction", "related_work", "method", "experiment", "conclusion", "reference"]
        present = [index for index, item in enumerate(order) if item in section_types]
        if len(present) < 2:
            return 0.0
        inversions = sum(1 for left, right in zip(present, present[1:]) if right < left)
        return max(0.0, min(4.0, len(present) * 0.6 - inversions * 1.5))

    def _pdf_heading_hierarchy_score(self, headings: List[str]) -> float:
        numbers: List[str] = []
        for heading in headings:
            normalized = heading.strip().replace("（", "(").replace("）", ")")
            match = re.match(r"^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|(\d+(?:\.\s*\d+){0,3}))", normalized)
            if match:
                numbers.append((match.group(1) or "chapter").replace(" ", ""))
        if not numbers:
            return 0.0
        nested = sum(1 for number in numbers if "." in number)
        single = sum(1 for number in numbers if number != "chapter" and "." not in number)
        score = min(5.0, len(numbers) * 0.12 + nested * 0.22 + single * 0.08)
        return score

    def _is_layout_noise_heading(self, text: str) -> bool:
        stripped = (text or "").strip()
        if re.search(r"\b(issn|cn\s*\d|doi)\b", stripped, re.I):
            return True
        if re.search(r"\d{4}\s*年\s*\d+\s*月|第\s*\d+\s*[卷期]|总第\s*\d+\s*期", stripped):
            return True
        if re.match(r"^\d+(?:\.\d+)?\s*万", stripped):
            return True
        if re.match(r"^\d{4}\s+", stripped):
            return True
        if re.match(r"^\d+(?:\.\s*\d+)+\s*文献", stripped):
            return True
        if re.match(r"^(?:19|20)\d{2}\s*评测任务", stripped):
            return True
        if re.search(r"\b10\.\d{4,9}\s*/", stripped):
            return True
        if re.match(r"^\d+[*＊]?\s*[，,]", stripped):
            return True
        if re.match(r"^\d{5,6}\s*[;；,，]?\s*\d*\.?\s*", stripped) and re.search(r"(?:大学|学院|医院|研究院|省|市|区|县)", stripped):
            return True
        if re.search(r"[<>≤≥]|\d+\s*%", stripped):
            return True
        if re.fullmatch(r"[A-Z][A-Z0-9.\s]{2,}", stripped) and stripped.lower() not in {"abstract", "references"}:
            return True
        if stripped.endswith(("。", ".")) and not re.match(r"^(?:\d+(?:\.\d+){0,3}|[一二三四五六七八九十]+[、.])\s*", stripped):
            return True
        if re.match(r"^[（(]\d+[）)]", stripped):
            return True
        if re.match(r"^\d+\.\s*[^\d\s].{0,120}\d{6}(?:[;；,，]|$)", stripped):
            return True
        if re.match(r"^\d+\.\s*(?:[^\d\s].{0,120})?(?:大学|学院|研究院|自治区|省|市|区|县|镇)", stripped):
            return True
        if re.search(r"(?:大学|学院|研究院|自治区|省|市|区|县|镇).{0,60}\d{6}", stripped):
            return True
        if stripped.lower() in {"model", "models", "模型", "method", "methods", "results", "experiments", "evaluation"}:
            return True
        if re.fullmatch(r"\d+\s+[A-Za-z][A-Za-z\s]+", stripped):
            return True
        if re.fullmatch(r"\[?\d+\]?\s+[A-Z][A-Z\s]+", stripped):
            return True
        if re.fullmatch(r"[-—·\s]*\d+\s*[-—·\s]*", stripped):
            return True
        if re.search(r"\b\d+(?:\.\d+)?\s*[kK万%％]\b|^[%％，,。.)）]", stripped):
            return True
        if re.match(r"^\d{1,3}[］\]]\.\s*(?:https?[:：]//|www\.|[A-Za-z]+\.)", stripped, re.I):
            return True
        if re.match(r"^\d+(?:\.\s*\d+)?\s*[，,、%％]", stripped):
            return True
        if re.match(r"^\d+\s*本[、，,]", stripped):
            return True
        if re.match(r"^\d+[^\s]*(?:试验箱|环境|系统|方法|模型|算法)", stripped):
            return True
        if self._looks_like_list_item_heading(stripped):
            return True
        if "\x02" in stripped:
            return True
        return False

    def _looks_like_list_item_heading(self, text: str) -> bool:
        stripped = (text or "").strip()
        if re.match(r"^(?:[（(]?\d+[）)]|\d+\.)\s*", stripped) and re.search(r"[，。：；,;:]", stripped):
            return True
        if re.match(r"^\d+\.\s*", stripped) and len(stripped) > 35 and infer_section_type(stripped) == "paragraph":
            return True
        return False

    def _should_use_layout_text(self, text: str, layout_text: str) -> bool:
        if not layout_text.strip():
            return False
        text_len = len((text or "").strip())
        layout_len = len(layout_text.strip())
        if text_len and layout_len < text_len * 0.45:
            return False
        text_heading_count = len(re.findall(r"(?m)^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|\d+(?:\.\d+){0,3}\s+|摘要|Abstract|参考文献)", text or ""))
        layout_heading_count = len(re.findall(r"\n\s*\n(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|\d+(?:\.\d+){0,3}\s+|摘要|Abstract|参考文献)", layout_text))
        if layout_heading_count >= max(3, int(text_heading_count * 0.6)):
            return True
        return bool(layout_heading_count and layout_len >= text_len * 0.8)

    def _looks_like_markdown(self, content: str) -> bool:
        return bool(re.search(r"^#{1,6}\s+", content or "", flags=re.M) or "```" in (content or ""))

    def _looks_like_html(self, content: str) -> bool:
        return bool(re.search(r"<\s*(html|body|h[1-6]|p|table|pre|div)\b", content or "", flags=re.I))

    def _plain_heading(self, text: str, toc_headings: Optional[List[Tuple[str, int]]] = None) -> str:
        if "\n" in text:
            return ""
        stripped = text.strip().strip("#")
        toc_match = self._match_toc_heading(stripped, toc_headings or [])
        if toc_match:
            return toc_match
        if self._looks_like_pdf_heading(stripped):
            return stripped
        if len(stripped) <= 80 and infer_section_type(stripped) != "paragraph":
            return stripped
        return ""

    def _looks_like_pdf_heading(self, text: str) -> bool:
        if not text or len(text) > 90:
            return False
        if re.match(r"^%PDF", text) or text == "%%EOF" or re.match(r"^\d+\s+\d+\s+obj\b", text):
            return False
        if re.search(r"[=+{}\\]|\b(return|function|if|for|while)\b", text, re.I):
            return False
        if re.match(r"^page\s+\d+\b", text, re.I):
            return False
        if re.search(r"\b(issn|cn|doi)\b", text, re.I):
            return False
        if re.search(r"\d{4}\s*年\s*\d+\s*月\s*\d+\s*日|第\s*\d+\s*[卷期]|总第\s*\d+\s*期", text):
            return False
        if text.strip().lower() in {"模型", "model", "models", "method", "methods", "results", "experiments", "evaluation"}:
            return False
        if re.match(r"^(figure|fig\.|table|图|表)\s*\d+", text, re.I):
            return False
        if "•" in text or re.search(r"\bCHAPTER\b", text, re.I):
            return False
        if self._looks_like_numbered_heading(text):
            return True
        if re.match(r"^(?:abstract|introduction|related work|background|preliminaries|materials and methods|methodology|methods?|experiments?|evaluation|results(?: and discussions)?|discussion|conclusions?|references|bibliography)\b", text, re.I):
            return True
        if re.match(r"^(?:摘要|中文摘要|英文摘要|引言|绪论|选题背景|研究意义|研究背景|研究内容|研究内容与方法|技术路线图|可能的创新点|相关工作|文献综述|国内外研究现状|研究现状|理论基础|概念界定|文献述评|方法|研究方法|方法设计|模型|模型构建|模型设计|算法|算法设计|系统设计|总体设计|方案设计|指标构建|样本选取|数据预处理|测算过程|模型设定|变量选择|直接效应|间接效应|研究假设|机制检验|调节效应|实验|实验设计|实验结果|实验分析|结果|结果分析|结果与分析|实验结果与分析|消融实验|性能评估|实证分析|实证结果分析|变量描述性统计|多重共线性检验|基准回归|稳健性检验|异质性分析|测算结果分析|出口规模|产品结构|区域结构|结论|总结|总结与展望|结论与展望|参考文献|参考资料|致谢)\b", text):
            return True
        if text.isupper() and 4 <= len(text) <= 70 and re.search(r"[A-Z]", text) and len(text.split()) >= 2:
            return True
        return False

    def _looks_like_numbered_heading(self, text: str) -> bool:
        stripped = text.strip().replace("（", "(").replace("）", ")")
        if re.match(r"^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|[一二三四五六七八九十百]+[、.]|\([一二三四五六七八九十百]+\)|\d+(?:\.\d+){0,3}[.)、]?)\s*(.{2,80})$", stripped):
            title = re.sub(r"^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|[一二三四五六七八九十百]+[、.]|\([一二三四五六七八九十百]+\)|\d+(?:\.\d+){0,3}[.)、]?)\s*", "", stripped)
            if re.search(r"[=+∑σ−∞≤≥]|\b(otherwise|if|where)\b", title, re.I):
                return False
            if re.search(r"^\s*[%％，,。.)）]|\b\d+(?:\.\d+)?\s*[kK万%％]\b|[，,）。)]\s*$", title):
                return False
            if re.search(r"\b\d+(?:\.\s*\d+)+\s*文献", title):
                return False
            if re.search(r"\b\w+\.(?:com|org|net|edu|cn)\b", title, re.I):
                return False
            if re.search(r"[一-鿿]", title):
                return 2 <= len(title) <= 40
            words = re.findall(r"[A-Za-z][A-Za-zÀ-ɏﬀ-ﬆ-]*", title)
            if len(words) < 1 or len(words) > 12:
                return False
            if len(words) == 1 and infer_section_type(title) == "paragraph":
                return False
            number = re.match(r"^(\d+(?:\.\d+){0,3})", stripped)
            if number and "." not in number.group(1) and int(number.group(1)) > 99:
                return False
            return True
        return False

    def _normalize_pdf_text(self, text: str, toc_headings: Optional[List[Tuple[str, int]]] = None) -> str:
        lines = [line.strip() for line in (text or "").splitlines()]
        normalized: List[str] = []
        toc_headings = toc_headings or []
        for index, line in enumerate(lines):
            if not line:
                normalized.append("")
                continue
            if self._is_toc_line(line):
                continue
            prev_blank = not any(item.strip() for item in lines[max(0, index - 2):index])
            next_blank = not any(item.strip() for item in lines[index + 1:index + 3])
            is_numbered_heading = self._looks_like_numbered_heading(line)
            toc_heading = self._match_toc_heading(line, toc_headings)
            heading_line = toc_heading or line
            if toc_headings and not toc_heading and self._looks_like_numbered_heading(line) and infer_section_type(line) == "paragraph":
                normalized.append(line)
                continue
            if toc_heading or (self._looks_like_pdf_heading(line) and (prev_blank or next_blank or is_numbered_heading or infer_section_type(line) != "paragraph")):
                if normalized and normalized[-1] != "":
                    normalized.append("")
                normalized.append(heading_line)
                normalized.append("")
            else:
                normalized.append(line)
        return "\n".join(normalized)

    def _extract_toc_headings(self, text: str) -> List[Tuple[str, int]]:
        lines = [line.strip() for line in (text or "").splitlines()]
        toc_indexes = [i for i, line in enumerate(lines) if re.fullmatch(r"目\s*录|contents", line, re.I)]
        candidates: List[Tuple[str, int]] = []
        for start in toc_indexes[:2]:
            for line in lines[start + 1:start + 180]:
                if re.match(r"^(摘\s*要|abstract|插图索引|表格索引|附录|致谢)$", line, re.I):
                    title = re.sub(r"\s+", "", line) if re.search(r"[一-鿿]", line) else line.strip()
                    candidates.append((title, 0))
                    continue
                item = self._parse_toc_line(line)
                if item:
                    candidates.append(item)
        seen = set()
        unique: List[Tuple[str, int]] = []
        for heading, level in candidates:
            key = self._heading_key(heading)
            if key and key not in seen and len(heading) <= 90:
                seen.add(key)
                unique.append((heading, level))
        return unique

    def _parse_toc_line(self, line: str) -> Optional[Tuple[str, int]]:
        if not line or len(line) > 180:
            return None
        compact = re.sub(r"[·.。．…\s]{2,}\d+\s*$", "", line).strip()
        compact = re.sub(r"\s+\d+\s*$", "", compact).strip()
        compact = compact.replace("（", "(").replace("）", ")")
        if not self._looks_like_numbered_heading(compact):
            return None
        level = 1
        number = re.match(r"^(?:第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]|(\d+(?:\.\d+)*))", compact)
        if number and number.group(1):
            level = number.group(1).count(".") + 1
        return compact, level

    def _is_toc_line(self, line: str) -> bool:
        if re.fullmatch(r"目\s*录|contents", line.strip(), re.I):
            return True
        if re.search(r"[·.。．…]{4,}\s*\d+\s*$", line):
            return True
        return False

    def _is_toc_block(self, text: str) -> bool:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return False
        joined = "\n".join(lines)
        if re.search(r"目\s*录|插图索引|附表索引|表格索引", joined) and re.search(r"[·.。．…]{4,}|\.{4,}", joined):
            return True
        toc_lines = sum(1 for line in lines if self._is_toc_line(line) or self._parse_toc_line(line))
        dot_leader_lines = sum(1 for line in lines if re.search(r"[·.。．…]{4,}\s*\d+\s*$", line))
        numbered_lines = sum(1 for line in lines if self._parse_toc_line(line))
        if len(lines) >= 2 and dot_leader_lines >= 1 and numbered_lines >= 1:
            return True
        return len(lines) >= 3 and toc_lines / len(lines) >= 0.45

    def _match_toc_heading(self, text: str, toc_headings: List[Tuple[str, int]]) -> str:
        if not text or not toc_headings:
            return ""
        if len(text) > 120 or self._is_toc_line(text):
            return ""
        best_heading = ""
        best_score = 0.0
        for heading, _ in toc_headings:
            score = self._heading_similarity(text, heading)
            if score > best_score:
                best_heading = heading
                best_score = score
        return best_heading if best_score >= 0.82 else ""

    def _should_keep_pdf_heading(self, original: str, heading: str, toc_headings: List[Tuple[str, int]]) -> bool:
        if self._match_toc_heading(original, toc_headings):
            return True
        if infer_section_type(heading) != "paragraph":
            return True
        if re.fullmatch(r"摘\s*要|abstract|参考文献|references|bibliography", heading.strip(), re.I):
            return True
        return False

    def _heading_similarity(self, left: str, right: str) -> float:
        left_key = self._heading_key(left)
        right_key = self._heading_key(right)
        if not left_key or not right_key:
            return 0.0
        if left_key == right_key:
            return 1.0
        shorter, longer = sorted([left_key, right_key], key=len)
        if len(shorter) >= 8 and longer.startswith(shorter):
            return len(shorter) / len(longer)
        left_tokens = set(re.findall(r"[A-Za-z0-9]+|[一-鿿]", left_key))
        right_tokens = set(re.findall(r"[A-Za-z0-9]+|[一-鿿]", right_key))
        if not left_tokens or not right_tokens:
            return 0.0
        return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)

    def _heading_key(self, value: str) -> str:
        value = (value or "").lower().replace("（", "(").replace("）", ")")
        value = re.sub(r"[·.。．…\s]+\d+$", "", value)
        value = re.sub(r"[^0-9a-z一-鿿]+", "", value)
        return value


    def _is_markdown_table_line(self, line: str) -> bool:
        return bool(line.startswith("|") and line.endswith("|") and line.count("|") >= 2)

    def _decode_maybe_bytes(self, content: str) -> str:
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="ignore")
        return str(content or "")

    def _content_to_bytes(self, content: str) -> bytes:
        if isinstance(content, bytes):
            return content
        if isinstance(content, bytearray):
            return bytes(content)
        return str(content or "").encode("latin1", errors="ignore")

    def _rows_to_markdown(self, rows: List[List[Any]]) -> str:
        cleaned_rows = [["" if cell is None else str(cell).strip() for cell in row] for row in rows]
        if not cleaned_rows:
            return ""
        width = max(len(row) for row in cleaned_rows)
        normalized = [row + [""] * (width - len(row)) for row in cleaned_rows]
        output = ["| " + " | ".join(normalized[0]) + " |"]
        output.append("| " + " | ".join(["---"] * width) + " |")
        for row in normalized[1:]:
            output.append("| " + " | ".join(row) + " |")
        return "\n".join(output)

    def _docx_to_markdown(self, data: bytes) -> str:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                document_xml = package.read("word/document.xml")
        except Exception:
            return ""
        root = ET.fromstring(document_xml)
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        lines: List[str] = []
        for child in root.findall(".//w:body/*", ns):
            if child.tag.endswith("}p"):
                text = self._docx_paragraph_text(child, ns)
                if not text:
                    continue
                style = child.find(".//w:pStyle", ns)
                style_value = style.attrib.get(f"{{{ns['w']}}}val", "") if style is not None else ""
                heading_match = re.search(r"Heading([1-6])", style_value, re.I)
                if heading_match:
                    lines.append("#" * int(heading_match.group(1)) + " " + text)
                else:
                    lines.append(text)
                    lines.append("")
            elif child.tag.endswith("}tbl"):
                rows = []
                for row in child.findall(".//w:tr", ns):
                    rows.append([self._docx_paragraph_text(cell, ns) for cell in row.findall("./w:tc", ns)])
                if rows:
                    lines.append(self._rows_to_markdown(rows))
                    lines.append("")
        return "\n".join(lines).strip()

    def _docx_paragraph_text(self, element: ET.Element, ns: Dict[str, str]) -> str:
        texts = [node.text or "" for node in element.findall(".//w:t", ns)]
        return re.sub(r"\s+", " ", "".join(texts)).strip()

    def _xlsx_to_markdown(self, data: bytes, title: str) -> tuple[str, int]:
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as package:
                shared_strings = self._xlsx_shared_strings(package)
                workbook_xml = ET.fromstring(package.read("xl/workbook.xml"))
                rels_xml = ET.fromstring(package.read("xl/_rels/workbook.xml.rels"))
                sheets = self._xlsx_sheets(package, workbook_xml, rels_xml, shared_strings)
        except Exception:
            return f"# {title}", 0
        parts = [f"# {title}"]
        for sheet_name, rows in sheets:
            if not rows:
                continue
            parts.append(f"## {sheet_name}")
            parts.append(self._rows_to_markdown(rows))
        return "\n\n".join(parts), len(sheets)

    def _xlsx_shared_strings(self, package: zipfile.ZipFile) -> List[str]:
        try:
            root = ET.fromstring(package.read("xl/sharedStrings.xml"))
        except KeyError:
            return []
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        strings = []
        for item in root.findall("s:si", ns):
            texts = [node.text or "" for node in item.findall(".//s:t", ns)]
            strings.append("".join(texts))
        return strings

    def _xlsx_sheets(self, package: zipfile.ZipFile, workbook_xml: ET.Element, rels_xml: ET.Element, shared_strings: List[str]) -> List[tuple[str, List[List[str]]]]:
        ns = {
            "s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
            "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        }
        rels_ns = {"rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rels = {
            rel.attrib.get("Id"): rel.attrib.get("Target", "")
            for rel in rels_xml.findall("rel:Relationship", rels_ns)
        }
        sheets = []
        for sheet in workbook_xml.findall(".//s:sheet", ns):
            name = sheet.attrib.get("name", "Sheet")
            rel_id = sheet.attrib.get(f"{{{ns['r']}}}id")
            target = rels.get(rel_id, "")
            path = "xl/" + target.lstrip("/")
            if not path.endswith(".xml"):
                continue
            try:
                sheet_xml = ET.fromstring(package.read(path))
            except KeyError:
                continue
            rows = self._xlsx_rows(sheet_xml, shared_strings)
            sheets.append((name, rows))
        return sheets

    def _xlsx_rows(self, sheet_xml: ET.Element, shared_strings: List[str]) -> List[List[str]]:
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rows: List[List[str]] = []
        for row in sheet_xml.findall(".//s:row", ns):
            values = [self._xlsx_cell_value(cell, shared_strings, ns) for cell in row.findall("s:c", ns)]
            if any(value for value in values):
                rows.append(values)
        return rows

    def _xlsx_cell_value(self, cell: ET.Element, shared_strings: List[str], ns: Dict[str, str]) -> str:
        value_node = cell.find("s:v", ns)
        inline_node = cell.find(".//s:t", ns)
        if inline_node is not None and inline_node.text:
            return inline_node.text.strip()
        if value_node is None or value_node.text is None:
            return ""
        value = value_node.text.strip()
        if cell.attrib.get("t") == "s":
            index = int(value) if value.isdigit() else -1
            return shared_strings[index] if 0 <= index < len(shared_strings) else ""
        return value

    def _pdf_to_text(self, data: bytes) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(data))
            pages = []
            for index, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                if page_text.strip():
                    pages.append(f"Page {index}\n{page_text.strip()}")
            return "\n\n".join(pages)
        except Exception:
            return self._decode_maybe_bytes(data)

    def _strip_html(self, value: str) -> str:
        text = re.sub(r"<br\s*/?>", "\n", value or "", flags=re.I)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(text)
        return re.sub(r"[ \t]+", " ", text).strip()

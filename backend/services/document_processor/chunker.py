from typing import List, Optional

from services.document_processor.models import ChunkBlock, ParsedBlock, ParsedDocument
from services.document_processor.normalizer import compact_whitespace


class TypeAwareChunker:
    """按论文结构和内容类型生成可检索 chunk。"""

    def __init__(self, max_chars: int = 1200, overlap: int = 120):
        self.max_chars = max_chars
        self.overlap = overlap

    def chunk(self, parsed_doc: ParsedDocument) -> List[ChunkBlock]:
        chunks: List[ChunkBlock] = []
        buffer: List[ParsedBlock] = []
        order = 0

        def flush_buffer():
            nonlocal order, buffer
            if not buffer:
                return
            groups = self._group_buffer_by_section(buffer)
            for group in groups:
                text = "\n\n".join(block.text for block in group if block.text.strip())
                if not text.strip():
                    continue
                for piece in self._split_long_text(text):
                    meta = dict(parsed_doc.metadata)
                    meta.update(group[-1].metadata)
                    chunk_type = self._chunk_type_for_buffer(group)
                    chunks.append(self._make_chunk(parsed_doc, chunk_type, piece, order, group[-1], meta))
                    order += 1
            buffer = []

        for block in parsed_doc.blocks:
            if block.type == "heading":
                flush_buffer()
                continue
            if block.type in {"table", "code", "equation", "reference", "abstract", "method", "experiment", "related_work", "conclusion"}:
                flush_buffer()
                for piece in self._split_special_block(block):
                    chunks.append(self._make_chunk(parsed_doc, block.type, piece, order, block, {**parsed_doc.metadata, **block.metadata}))
                    order += 1
                continue
            current_len = sum(len(item.text) for item in buffer) + len(block.text)
            if buffer and current_len > self.max_chars:
                flush_buffer()
            buffer.append(block)
        flush_buffer()
        return chunks

    def _group_buffer_by_section(self, buffer: List[ParsedBlock]) -> List[List[ParsedBlock]]:
        groups: List[List[ParsedBlock]] = []
        current: List[ParsedBlock] = []
        current_key: Optional[tuple[str, str]] = None
        for block in buffer:
            key = (block.section_path, str(block.metadata.get("section_type") or block.type))
            if current and key != current_key:
                groups.append(current)
                current = []
            current.append(block)
            current_key = key
        if current:
            groups.append(current)
        return groups

    def _chunk_type_for_buffer(self, blocks: List[ParsedBlock]) -> str:
        section_type = str(blocks[-1].metadata.get("section_type") or "paragraph")
        return section_type if section_type in {"abstract", "method", "experiment", "related_work", "conclusion"} else "paragraph"

    def _split_special_block(self, block: ParsedBlock) -> List[str]:
        if block.type in {"table", "code", "equation"}:
            return [block.text.strip()] if block.text.strip() else []
        return self._split_long_text(block.text)

    def _split_long_text(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []
        if len(text) <= self.max_chars:
            return [text]
        pieces = []
        start = 0
        while start < len(text):
            end = min(len(text), start + self.max_chars)
            cut = self._best_cut(text, start, end)
            piece = text[start:cut].strip()
            if piece:
                pieces.append(piece)
            if cut >= len(text):
                break
            start = max(cut - self.overlap, start + 1)
        return pieces

    def _best_cut(self, text: str, start: int, end: int) -> int:
        if end >= len(text):
            return len(text)
        window = text[start:end]
        for sep in ["\n\n", "。", ". ", "；", "; ", "，", ", "]:
            pos = window.rfind(sep)
            if pos > self.max_chars * 0.55:
                return start + pos + len(sep)
        return end

    def _make_chunk(self, parsed_doc: ParsedDocument, chunk_type: str, text: str, order: int, block: ParsedBlock, metadata: dict) -> ChunkBlock:
        content = self._format_content(parsed_doc, chunk_type, text, block, metadata)
        return ChunkBlock(
            chunk_type=chunk_type,
            content=content,
            order=order,
            page_start=block.page,
            page_end=block.page,
            section_path=block.section_path,
            metadata=metadata,
        )

    def _format_content(self, parsed_doc: ParsedDocument, chunk_type: str, text: str, block: ParsedBlock, metadata: dict) -> str:
        paper_title = metadata.get("paper_title") or parsed_doc.title
        authors = metadata.get("authors") or ""
        year = metadata.get("year") or ""
        section = block.section_path or metadata.get("section_path") or ""
        if chunk_type == "table":
            return f"【论文】{paper_title}\n【章节】{section}\n【类型】table\n【内容】\n{text}".strip()
        if chunk_type == "code":
            lang = metadata.get("code_language") or ""
            return f"【论文】{paper_title}\n【章节】{section}\n【类型】code\n【语言】{lang}\n【代码】\n{text}".strip()
        if chunk_type == "equation":
            return f"【论文】{paper_title}\n【章节】{section}\n【类型】equation\n【公式】\n{text}".strip()
        if chunk_type == "experiment":
            task = metadata.get("task") or ""
            dataset = metadata.get("dataset") or ""
            metric = metadata.get("metric") or ""
            return f"【论文】{paper_title}\n【章节】{section}\n【类型】experiment\n【任务】{task}\n【数据集】{dataset}\n【指标】{metric}\n【内容】\n{text}".strip()
        if chunk_type == "method":
            method = metadata.get("method_name") or ""
            return f"【论文】{paper_title}\n【作者】{authors}\n【年份】{year}\n【章节】{section}\n【类型】method\n【方法】{method}\n【正文】\n{text}".strip()
        if chunk_type == "reference":
            citation = metadata.get("citation_key") or ""
            return f"【论文】{paper_title}\n【章节】References\n【类型】reference\n【引用】{citation}\n【内容】\n{text}".strip()
        label = chunk_type if chunk_type != "paragraph" else metadata.get("section_type", "paragraph")
        if label not in {"abstract", "method", "experiment", "related_work", "conclusion"}:
            label = "paragraph"
        return f"【论文】{paper_title}\n【作者】{authors}\n【年份】{year}\n【章节】{section}\n【类型】{label}\n【正文】\n{text}".strip()

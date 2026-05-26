"""参考文献解析工具。"""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class ParsedReference:
    raw_text: str
    title: str = ""
    authors: str = ""
    year: str = ""
    venue: str = ""
    doi: str = ""
    arxiv_id: str = ""
    citation_key: str = ""


class ReferenceParser:
    """从 reference chunk 或 References 原文中拆分单条引用。"""

    DOI_RE = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)
    ARXIV_RE = re.compile(r"arXiv[:\s]*(\d{4}\.\d{4,5}(?:v\d+)?)", re.I)
    YEAR_RE = re.compile(r"\b(19\d{2}|20\d{2})\b")
    NUMBERED_RE = re.compile(r"(?m)^\s*(?:\[(\d+)\]|(\d+)[.)])\s+")

    def parse(self, text: str) -> List[ParsedReference]:
        body = self._reference_body(text)
        entries = self._split_entries(body)
        references = [self._parse_entry(entry) for entry in entries if entry.strip()]
        return [ref for ref in references if ref.raw_text]

    def _reference_body(self, text: str) -> str:
        if not text:
            return ""
        match = re.search(r"^【内容】\s*$", text, re.M)
        if match:
            return text[match.end():].strip()
        return text.strip()

    def _split_entries(self, text: str) -> List[str]:
        text = text.strip()
        if not text:
            return []

        matches = list(self.NUMBERED_RE.finditer(text))
        if len(matches) >= 2:
            entries = []
            for index, match in enumerate(matches):
                start = match.start()
                end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
                entries.append(text[start:end].strip())
            return entries
        if len(matches) == 1:
            return [text]

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if len(lines) > 1:
            return lines
        return [text]

    def _parse_entry(self, entry: str) -> ParsedReference:
        raw = self._compact(entry)
        label, body = self._strip_label(raw)
        doi = self._first(self.DOI_RE.findall(body))
        arxiv_id = self._first(self.ARXIV_RE.findall(body))
        years = self.YEAR_RE.findall(body)
        year = years[-1] if years else ""
        authors, title, venue = self._parse_authors_title_venue(body, year)
        citation_key = self._citation_key(label, authors, title, year, arxiv_id)
        return ParsedReference(
            raw_text=raw,
            title=title[:512],
            authors=authors[:512],
            year=year,
            venue=venue[:512],
            doi=doi.rstrip(".,;"),
            arxiv_id=arxiv_id,
            citation_key=citation_key,
        )

    def _strip_label(self, text: str) -> tuple[str, str]:
        match = re.match(r"^\s*(?:\[(\d+)\]|(\d+)[.)])\s+(.*)$", text, re.S)
        if not match:
            return "", text.strip()
        return match.group(1) or match.group(2) or "", match.group(3).strip()

    def _parse_authors_title_venue(self, body: str, year: str) -> tuple[str, str, str]:
        cleaned = body.strip()
        if year:
            cleaned = re.sub(rf"\b{re.escape(year)}\b", year, cleaned, count=1)
        parts = [part.strip() for part in re.split(r"\.\s+", cleaned) if part.strip()]
        if not parts:
            return "", cleaned[:255], ""

        authors = ""
        title = ""
        venue = ""

        if len(parts) == 1:
            title = self._remove_identifiers(parts[0])
        elif self._looks_like_authors(parts[0]):
            authors = parts[0]
            title = self._remove_identifiers(parts[1])
            venue = self._remove_identifiers(". ".join(parts[2:]))
        else:
            title = self._remove_identifiers(parts[0])
            venue = self._remove_identifiers(". ".join(parts[1:]))

        if not title and len(parts) >= 2:
            title = self._remove_identifiers(parts[1])
        return authors.strip(), title.strip(" .。"), venue.strip(" .。")

    def _looks_like_authors(self, text: str) -> bool:
        lowered = text.lower()
        if ":" in text:
            return False
        if " et al" in lowered:
            return True
        if "," in text and len(text.split()) <= 12:
            return True
        if re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", text) and len(text.split()) <= 10:
            return True
        return False

    def _remove_identifiers(self, text: str) -> str:
        text = self.DOI_RE.sub("", text)
        text = re.sub(r"arXiv[:\s]*\d{4}\.\d{4,5}(?:v\d+)?", "", text, flags=re.I)
        return self._compact(text)

    def _citation_key(self, label: str, authors: str, title: str, year: str, arxiv_id: str) -> str:
        if label:
            return f"ref-{label}"
        base = authors or title or arxiv_id or "reference"
        first = re.split(r"\s+|,", base.strip())[0].lower()
        first = re.sub(r"[^a-z0-9]+", "", first) or "ref"
        return f"{first}{year}" if year else first

    def _compact(self, text: str) -> str:
        return re.sub(r"\s+", " ", text or "").strip()

    def _first(self, values: List[str]) -> str:
        return values[0] if values else ""

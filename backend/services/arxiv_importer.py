"""arXiv 论文导入服务。"""

import html
import re
import urllib.error
import urllib.request
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from services.ingest import IngestService


class ArxivImporter:
    """通过 arXiv ID 或 URL 导入摘要页 / HTML 全文。"""

    USER_AGENT = "Mozilla/5.0 kg-paper-assistant-arxiv-importer/1.0"

    def __init__(self, db: Session):
        self.db = db

    def import_paper(self, arxiv_id_or_url: str, prefer_html: bool = True) -> Dict[str, object]:
        arxiv_id = self.extract_arxiv_id(arxiv_id_or_url)
        if not arxiv_id:
            raise ValueError("无法识别 arXiv ID")

        abs_meta = self.fetch_abs_metadata(arxiv_id)
        content = ""
        source = f"arxiv-abs:{arxiv_id}"
        imported_from = "abs"

        if prefer_html:
            html_text = self.fetch_optional(f"https://arxiv.org/html/{arxiv_id}")
            if html_text and len(html_text) >= 500:
                try:
                    content = self.html_to_markdown(html_text, fallback_title=abs_meta.get("title") or arxiv_id, min_length=1000)
                    source = f"arxiv-html:{arxiv_id}"
                    imported_from = "html"
                except ValueError:
                    content = ""

        if not content:
            content = self.abs_to_markdown(abs_meta)

        result = IngestService(self.db).ingest_text(
            title=abs_meta.get("title") or arxiv_id,
            content=content,
            source=source,
            tags=["paper", "arxiv", imported_from],
        )
        result.update({
            "arxiv_id": arxiv_id,
            "title": abs_meta.get("title") or arxiv_id,
            "source": source,
            "imported_from": imported_from,
            "url": f"https://arxiv.org/abs/{arxiv_id}",
        })
        return result

    def fetch_abs_metadata(self, arxiv_id: str) -> Dict[str, str]:
        url = f"https://arxiv.org/abs/{arxiv_id}"
        raw = self.fetch(url)
        title = self.clean_html(self.search_one(r'<h1 class="title mathjax">\s*<span[^>]*>Title:</span>(.*?)</h1>', raw, "title"))
        authors = self.clean_html(self.search_one(r'<div class="authors">\s*<span[^>]*>Authors:</span>(.*?)</div>', raw, "authors"))
        abstract = self.clean_html(self.search_one(r'<blockquote class="abstract mathjax">\s*<span[^>]*>Abstract:</span>(.*?)</blockquote>', raw, "abstract"))
        date = self.clean_html(self.search_one(r'<div class="dateline">\s*\[(.*?)\]\s*</div>', raw, "dateline"))
        comments = self.clean_html(self.search_optional(r'<td class="tablecell comments mathjax">(.*?)</td>', raw))
        subjects = self.clean_html(self.search_optional(r'<td class="tablecell subjects">(.*?)</td>', raw))
        year_match = re.search(r"\b(19\d{2}|20\d{2})\b", date)
        return {
            "id": arxiv_id,
            "url": url,
            "title": title,
            "authors": authors,
            "abstract": abstract,
            "year": year_match.group(1) if year_match else "",
            "comments": comments,
            "subjects": subjects,
        }

    def abs_to_markdown(self, paper: Dict[str, str]) -> str:
        return f"""# {paper.get('title', '')}
{paper.get('authors', '')}
{paper.get('year', '')}
arXiv: {paper.get('id', '')}

## Abstract
{paper.get('abstract', '')}

## Method
This paper proposes or studies the core method described in the abstract. The method details are summarized from the public arXiv metadata and abstract.

## Experiments
The public arXiv page reports subjects and comments. Subjects: {paper.get('subjects', '')}. Comments: {paper.get('comments', '')}.

## References
[1] arXiv:{paper.get('id', '')} {paper.get('title', '')}.
"""

    def html_to_markdown(self, html_text: str, fallback_title: str = "", min_length: int = 1000) -> str:
        title = self.extract_title(html_text) or fallback_title
        body = re.sub(
            r"<dialog[\s\S]*?</dialog>|<header[\s\S]*?</header>|<script[\s\S]*?</script>|<style[\s\S]*?</style>|<nav[\s\S]*?</nav>|<footer[\s\S]*?</footer>",
            "\n",
            html_text,
            flags=re.I,
        )
        article_match = re.search(r"<article[\s\S]*?</article>", body, flags=re.I)
        if article_match:
            body = article_match.group(0)
        tokens = re.findall(
            r"<h[1-6][\s\S]*?</h[1-6]>|<blockquote[^>]*class=[\"'][^\"']*ltx_abstract[^\"']*[\"'][\s\S]*?</blockquote>|<table[\s\S]*?</table>|<pre[\s\S]*?</pre>|<p[\s\S]*?</p>|<li[\s\S]*?</li>",
            body,
            flags=re.I,
        )
        lines = [f"# {title}"] if title else []
        for token in tokens:
            lower = token.lower()
            if lower.startswith("<h"):
                level_match = re.match(r"<h([1-6])", lower)
                heading = self.normalize_heading(self.clean_html(token))
                if heading and level_match:
                    lines.append("#" * int(level_match.group(1)) + " " + heading)
            elif "ltx_abstract" in lower:
                abstract = re.sub(r"^abstract\s*", "", self.clean_html(token), flags=re.I).strip()
                if abstract:
                    lines.append("## Abstract")
                    lines.append(abstract)
            elif lower.startswith("<table"):
                table_text = self.clean_html(token)
                if table_text:
                    lines.append("## Table")
                    lines.append(table_text)
            elif lower.startswith("<pre"):
                code = self.clean_html(token)
                if code:
                    lines.append("```")
                    lines.append(code)
                    lines.append("```")
            else:
                paragraph = self.clean_html(token)
                if paragraph and len(paragraph) >= 20:
                    lines.append(paragraph)
        markdown = "\n\n".join(lines)
        if len(markdown) < min_length:
            raise ValueError(f"arXiv HTML 转 Markdown 后文本过短: len={len(markdown)}")
        return markdown

    def extract_arxiv_id(self, value: str) -> str:
        text = (value or "").strip()
        match = re.search(r"(?:arxiv\.org/(?:abs|html|pdf)/)?([0-9]{4}\.[0-9]{4,5})(?:v\d+)?", text, re.I)
        return match.group(1) if match else ""

    def fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={"User-Agent": self.USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as response:
            return response.read().decode("utf-8", errors="ignore")

    def fetch_optional(self, url: str) -> str:
        try:
            return self.fetch(url)
        except (urllib.error.URLError, TimeoutError, ValueError):
            return ""

    def extract_title(self, html_text: str) -> str:
        for pattern in [r"<h1[^>]*class=[\"'][^\"']*ltx_title[^\"']*[\"'][^>]*>([\s\S]*?)</h1>", r"<title>([\s\S]*?)</title>"]:
            match = re.search(pattern, html_text, flags=re.I)
            if match:
                title = self.clean_html(match.group(1))
                title = re.sub(r"\s*\|\s*arXiv.*$", "", title, flags=re.I).strip()
                if title:
                    return title
        return ""

    def normalize_heading(self, heading: str) -> str:
        heading = re.sub(r"^(\d+(?:\.\d+)*|[IVX]+)\s*", "", heading.strip(), flags=re.I)
        heading = re.sub(r"\s+", " ", heading).strip()
        aliases = {
            "intro": "Introduction",
            "introduction": "Introduction",
            "background": "Related Work",
            "model architecture": "Method",
            "model": "Method",
            "experiments": "Experiments",
            "conclusions": "Conclusion",
            "refs": "References",
            "bibliography": "References",
        }
        return aliases.get(heading.lower(), heading)

    def search_one(self, pattern: str, text: str, field: str) -> str:
        match = re.search(pattern, text, re.S | re.I)
        if not match:
            raise ValueError(f"arXiv 页面缺少字段: {field}")
        return match.group(1)

    def search_optional(self, pattern: str, text: str) -> str:
        match = re.search(pattern, text, re.S | re.I)
        return match.group(1) if match else ""

    def clean_html(self, value: str) -> str:
        value = re.sub(r"<math[\s\S]*?</math>", " ", value or "", flags=re.I)
        value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
        value = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", html.unescape(value)).strip()

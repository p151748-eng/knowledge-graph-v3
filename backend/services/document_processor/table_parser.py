import html
import re
from typing import List


def html_table_to_markdown(table_html: str) -> str:
    rows = []
    for row_html in re.findall(r"<tr[\s\S]*?</tr>", table_html or "", flags=re.I):
        cells = re.findall(r"<t[dh][^>]*>([\s\S]*?)</t[dh]>", row_html, flags=re.I)
        if cells:
            rows.append([clean_cell(cell) for cell in cells])
    return rows_to_markdown(rows)


def markdown_table_lines(lines: List[str]) -> str:
    return "\n".join(line.rstrip() for line in lines if line.strip())


def rows_to_markdown(rows: List[List[str]]) -> str:
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    normalized = [row + [""] * (width - len(row)) for row in rows]
    output = ["| " + " | ".join(normalized[0]) + " |"]
    output.append("| " + " | ".join(["---"] * width) + " |")
    for row in normalized[1:]:
        output.append("| " + " | ".join(row) + " |")
    return "\n".join(output)


def clean_cell(cell: str) -> str:
    text = re.sub(r"<[^>]+>", " ", cell or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

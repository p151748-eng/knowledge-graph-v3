"""
复杂文件解析回归测试。

验证目标：
1. CSV 能生成 table chunk，并保留列名、数据集和指标。
2. DOCX 能解析标题、段落和表格。
3. XLSX 能按 sheet 生成表格 chunk。
4. PDF 在无可选解析依赖时至少能稳定降级，不阻断导入链路。

运行方式：
    python backend/tests/test_file_parsers.py
"""

import sys
import zipfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.document_processor import DocumentProcessor, TypeAwareChunker


def zip_bytes(files):
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in files.items():
            package.writestr(name, data)
    return buffer.getvalue().decode("latin1")


def make_docx_fixture():
    return zip_bytes({
        "word/document.xml": """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>GraphRAG Experiment Report</w:t></w:r></w:p>
    <w:p><w:r><w:t>This report evaluates hybrid retrieval for scientific papers.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Experiments</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Model</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Dataset</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Metric</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>GraphRAG</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>S2ORC</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>F1</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
  </w:body>
</w:document>""",
    })


def make_xlsx_fixture():
    return zip_bytes({
        "xl/workbook.xml": """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Results" sheetId="1" r:id="rId1"/></sheets>
</workbook>""",
        "xl/_rels/workbook.xml.rels": """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        "xl/worksheets/sheet1.xml": """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    <row r="1"><c t="inlineStr"><is><t>Method</t></is></c><c t="inlineStr"><is><t>Dataset</t></is></c><c t="inlineStr"><is><t>Score</t></is></c></row>
    <row r="2"><c t="inlineStr"><is><t>RAG</t></is></c><c t="inlineStr"><is><t>Natural Questions</t></is></c><c><v>88.5</v></c></row>
  </sheetData>
</worksheet>""",
    })


def chunk_text(doc):
    chunks = TypeAwareChunker(max_chars=500).chunk(doc)
    return chunks, "\n".join(chunk.content for chunk in chunks)


def test_csv_parser_keeps_table():
    csv_content = "Model,Dataset,Metric\nHybridRAG,S2ORC,F1\nBM25,NQ,Accuracy\n"
    doc = DocumentProcessor().process("retrieval_results.csv", csv_content, source="retrieval_results.csv")
    chunks, text = chunk_text(doc)
    assert doc.file_type == "csv"
    assert "table" in [chunk.chunk_type for chunk in chunks]
    assert "| Model | Dataset | Metric |" in text
    assert "HybridRAG" in text and "S2ORC" in text


def test_docx_parser_keeps_headings_paragraphs_and_table():
    doc = DocumentProcessor().process("report.docx", make_docx_fixture(), source="report.docx")
    chunks, text = chunk_text(doc)
    assert doc.file_type == "docx"
    assert "GraphRAG Experiment Report" in text
    assert "hybrid retrieval" in text
    assert "table" in [chunk.chunk_type for chunk in chunks]
    assert "S2ORC" in text and "F1" in text


def test_xlsx_parser_keeps_sheet_table():
    doc = DocumentProcessor().process("results.xlsx", make_xlsx_fixture(), source="results.xlsx")
    chunks, text = chunk_text(doc)
    assert doc.file_type == "xlsx"
    assert doc.metadata["sheet_count"] == 1
    assert "Results" in text
    assert "Natural Questions" in text
    assert "table" in [chunk.chunk_type for chunk in chunks]


def test_pdf_parser_degrades_to_text_safely():
    fake_pdf = b"%PDF-1.4\n1 0 obj\nScientific paper PDF fallback text about retrieval and experiments.\n%%EOF".decode("latin1")
    doc = DocumentProcessor().process("paper.pdf", fake_pdf, source="paper.pdf")
    chunks, text = chunk_text(doc)
    assert doc.file_type == "pdf"
    assert chunks
    assert "retrieval" in text.lower()


if __name__ == "__main__":
    test_csv_parser_keeps_table()
    test_docx_parser_keeps_headings_paragraphs_and_table()
    test_xlsx_parser_keeps_sheet_table()
    test_pdf_parser_degrades_to_text_safely()
    print("=== 复杂文件解析回归测试通过 ===")

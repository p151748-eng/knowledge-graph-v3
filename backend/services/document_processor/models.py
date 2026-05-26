from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ParsedBlock:
    block_id: str
    type: str
    text: str
    order: int
    page: Optional[int] = None
    section_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    title: str
    source: str = "manual"
    file_type: str = "text"
    metadata: Dict[str, Any] = field(default_factory=dict)
    blocks: List[ParsedBlock] = field(default_factory=list)


@dataclass
class ChunkBlock:
    chunk_type: str
    content: str
    order: int
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    section_path: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

import re
from typing import Any, Dict, Tuple


HEADING_SECTION_MAP = {
    "abstract": "abstract",
    "摘要": "abstract",
    "中文摘要": "abstract",
    "英文摘要": "abstract",
    "introduction": "introduction",
    "intro": "introduction",
    "引言": "introduction",
    "绪论": "introduction",
    "选题背景": "introduction",
    "研究意义": "introduction",
    "研究背景": "introduction",
    "研究内容": "introduction",
    "研究内容与方法": "introduction",
    "技术路线图": "introduction",
    "可能的创新点": "introduction",
    "related work": "related_work",
    "background": "related_work",
    "preliminaries": "related_work",
    "相关工作": "related_work",
    "文献综述": "related_work",
    "国内外研究现状": "related_work",
    "研究现状": "related_work",
    "理论基础": "related_work",
    "概念界定": "related_work",
    "概念界定与相关理论基础": "related_work",
    "文献述评": "related_work",
    "method": "method",
    "methods": "method",
    "methodology": "method",
    "materials and methods": "method",
    "approach": "method",
    "optimization models": "method",
    "naive bayes classifier": "method",
    "model": "method",
    "models": "method",
    "svm classification technique": "method",
    "naive bayes classifier": "method",
    "classification with logistic regression": "method",
    "sentiment classification": "method",
    "classification tasks and features": "method",
    "softmax": "method",
    "learning in logistic regression": "experiment",
    "gradient descent": "experiment",
    "stochastic gradient descent algorithm": "experiment",
    "mini-batch training": "experiment",
    "numerical experiments": "experiment",
    "results and discussion": "experiment",
    "feature modeling": "method",
    "feature classification": "method",
    "方法": "method",
    "研究方法": "method",
    "方法设计": "method",
    "模型": "method",
    "模型构建": "method",
    "模型设计": "method",
    "算法": "method",
    "算法设计": "method",
    "系统设计": "method",
    "总体设计": "method",
    "方案设计": "method",
    "指标构建": "method",
    "评价指标体系构建原则": "method",
    "数字经济发展水平指标构建": "method",
    "指标选取": "method",
    "样本选取": "method",
    "数据预处理": "method",
    "测算过程": "method",
    "模型设定": "method",
    "变量选择与数据来源": "method",
    "模型、变量及数据说明": "method",
    "直接效应": "method",
    "间接效应": "method",
    "研究假设": "method",
    "机制检验": "method",
    "调节效应": "method",
    "experiment": "experiment",
    "experiments": "experiment",
    "experimental setup": "experiment",
    "evaluation": "experiment",
    "results": "experiment",
    "result": "experiment",
    "results and discussions": "experiment",
    "discussion": "experiment",
    "training": "experiment",
    "实验": "experiment",
    "实验设计": "experiment",
    "实验结果": "experiment",
    "实验分析": "experiment",
    "结果": "experiment",
    "结果分析": "experiment",
    "结果与分析": "experiment",
    "实验结果与分析": "experiment",
    "消融实验": "experiment",
    "性能评估": "experiment",
    "实证分析": "experiment",
    "实证结果分析": "experiment",
    "变量描述性统计": "experiment",
    "多重共线性检验": "experiment",
    "基准回归结果分析": "experiment",
    "稳健性检验": "experiment",
    "异质性分析": "experiment",
    "收入水平异质性": "experiment",
    "产品异质性": "experiment",
    "区域异质性": "experiment",
    "测算结果分析": "experiment",
    "国家层面分析": "experiment",
    "区域层面分析": "experiment",
    "出口规模": "experiment",
    "产品结构": "experiment",
    "贸易现状分析": "experiment",
    "系统架构与关键技术": "method",
    "相关研究": "related_work",
    "多智能体作文评分系统框架设计": "method",
    "系统整体架构": "method",
    "基于 agent 协作机制": "method",
    "基于agent协作机制": "method",
    "问题描述与方法概述": "method",
    "多智能体强化学习控制方法": "method",
    "多智能体协调控制与流程设计": "method",
    "多智能体状态空间与协调策略": "method",
    "物理信息神经网络": "method",
    "试验结果与分析": "experiment",
    "试验设置": "experiment",
    "性能对比分析": "experiment",
    "传统pid 方法": "experiment",
    "模糊pid 方法": "experiment",
    "系统整体架构": "method",
    "实验设计与结 果分析": "experiment",
    "数据集": "experiment",
    "实验环境与配置": "experiment",
    "评价指标": "experiment",
    "实验结果与分析": "experiment",
    "结束语": "conclusion",
    "结语": "conclusion",
    "参考文献": "reference",
    "conclusions": "conclusion",
    "结论": "conclusion",
    "总结": "conclusion",
    "总结与展望": "conclusion",
    "结论与展望": "conclusion",
    "references": "reference",
    "reference": "reference",
    "bibliography": "reference",
    "参考文献": "reference",
    "参考资料": "reference",
    "致谢": "reference",
}

BODY_SECTION_PATTERNS = [
    (r"^(abstract|摘要|中文摘要|英文摘要)[:：]?", "abstract"),
    (r"^(introduction|intro|引言|绪论|选题背景|研究意义|研究背景|研究内容|研究内容与方法|技术路线图|可能的创新点)[:：]?", "introduction"),
    (r"^(related work|background|preliminaries|相关工作|相关研究|文献综述|国内外研究现状|研究现状|理论基础|概念界定|文献述评)[:：]?", "related_work"),
    (r"^(method|methods|methodology|materials and methods|方法|研究方法|方法设计|问题描述与方法概述|多智能体强化学习控制方法|多智能体协调控制与流程设计|多智能体状态空间与协调策略|物理信息神经网络|多智能体作文评分系统框架设计|模型构建|模型设计|算法设计|系统设计|系统架构|系统整体架构|关键技术|基于 agent 协作机制|方案设计|指标构建|样本选取|数据预处理|测算过程|模型设定|变量选择|直接效应|间接效应|研究假设|机制检验|调节效应)[:：]?", "method"),
    (r"^(experiment|experiments|evaluation|results?|results and discussions|实验|试验|实验设计|实验设计与分析|试验结果与分析|试验设置|性能对比分析|传统pid 方法|模糊pid 方法|实验环境|评价指标|数据集|实验结果|实验分析|结果|结果分析|结果与分析|实验结果与分析|消融实验|性能评估|实证分析|实证结果分析|变量描述性统计|多重共线性检验|基准回归|稳健性检验|异质性分析|测算结果分析|出口规模|产品结构|区域结构)[:：]?", "experiment"),
    (r"^(conclusions?|结论|总结|结束语|结语|总结与展望|结论与展望)[:：]?", "conclusion"),
    (r"^(references|bibliography|参考文献|参考资料|致谢)[:：]?", "reference"),
]


def infer_section_type(section_path: str, text: str = "") -> str:
    section = _normalize_heading((section_path or "").split("/")[-1])
    section = _fix_extracted_heading(section)
    if section:
        for key, section_type in sorted(HEADING_SECTION_MAP.items(), key=lambda item: len(item[0]), reverse=True):
            key_norm = _normalize_heading(key)
            if section == key_norm:
                return section_type
            if re.match(rf"^(?:\d+(?:\.\d+)*|[ivxlcdm]+)[.)]?\s+{re.escape(key_norm)}(?:$|\b)", section, re.I):
                return section_type
            if key_norm in {"model", "models"} and section != key_norm:
                continue
            if section.endswith(" " + key_norm) and re.match(r"^\d+(?:\.\d+)*\s+", section):
                return section_type
    sample = (text or "").strip().lower()[:160]
    for pattern, section_type in BODY_SECTION_PATTERNS:
        if re.search(pattern, sample, re.I):
            return section_type
    return "paragraph"


def _normalize_heading(value: str) -> str:
    value = (value or "").strip().lower()
    value = value.replace("（", "(").replace("）", ")")
    value = re.sub(r"^第\s*[\d一二三四五六七八九十百]+\s*[章节篇部分]\s*", "", value)
    value = re.sub(r"^[\s\d.ivxlcdm一二三四五六七八九十百]+[.)、:-]?\s*", "", value, flags=re.I)
    value = re.sub(r"^\([\s\d一二三四五六七八九十百]+\)\s*", "", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def _fix_extracted_heading(value: str) -> str:
    fixes = {
        "classiﬁcation with logistic regression": "classification with logistic regression",
        "sentiment classiﬁcation": "sentiment classification",
        "other classiﬁcation tasks and features": "classification tasks and features",
        "applying softmax in logistic regression": "softmax",
        "features in multinomial logistic regression": "classification tasks and features",
        "learning in multinomial logistic regression": "learning in logistic regression",
        "stochastic gradient descent algorithm": "stochastic gradient descent algorithm",
        "interpreting models": "method",
        "naive bayes classiﬁer": "naive bayes classifier",
        "results and discussion": "results and discussion",
    }
    normalized = value.replace("ﬁ", "fi").replace("ﬂ", "fl")
    if normalized in fixes:
        return fixes[normalized]
    for fragment, replacement in fixes.items():
        if normalized.startswith(fragment) or fragment in normalized:
            return replacement
    return normalized


def extract_paper_metadata(title: str, content: str) -> Dict[str, Any]:
    metadata: Dict[str, Any] = {"paper_title": title}
    lines = [line.strip() for line in (content or "").splitlines() if line.strip()]
    if lines:
        first_heading = next((line.lstrip("# ").strip() for line in lines if line.startswith("#")), None)
        if first_heading:
            metadata["paper_title"] = first_heading
    joined = "\n".join(lines[:30])
    arxiv = re.search(r"arXiv[:：]?\s*([0-9]{4}\.[0-9]{4,5}(?:v\d+)?)", joined, re.I)
    if arxiv:
        metadata["arxiv_id"] = arxiv.group(1)
    doi = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", joined)
    if doi:
        metadata["doi"] = doi.group(0)
    year = re.search(r"\b(19\d{2}|20\d{2})\b", joined)
    if year:
        metadata["year"] = year.group(1)
    authors = _extract_authors(lines)
    if authors:
        metadata["authors"] = authors
    metadata["citation_key"] = _citation_key(metadata)
    return metadata


def enrich_block_metadata(section_path: str, text: str, inherited: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    section_type = infer_section_type(section_path, text)
    metadata = dict(inherited)
    metadata["section_type"] = section_type
    method = _extract_method_name(section_path, text)
    if method:
        metadata["method_name"] = method
    metric = _extract_metric(text)
    if metric:
        metadata["metric"] = metric
    dataset = _extract_dataset(text)
    if dataset:
        metadata["dataset"] = dataset
    return section_type, metadata


def _extract_authors(lines: list[str]) -> str:
    for i, line in enumerate(lines[:8]):
        lower = line.lower()
        if line.startswith("#") or any(key in lower for key in ["abstract", "摘要", "arxiv", "doi"]):
            continue
        if re.search(r"[,，]|\band\b|等|et al", line, re.I) and len(line) <= 220:
            return line
        if i in {1, 2} and 4 <= len(line) <= 180 and not line.endswith(("。", ".")):
            return line
    return ""


def _citation_key(metadata: Dict[str, Any]) -> str:
    title = str(metadata.get("paper_title") or "paper").lower()
    author = str(metadata.get("authors") or "anon").split(",")[0].split(" and ")[0].strip().split(" ")[-1]
    year = str(metadata.get("year") or "")
    words = re.findall(r"[a-zA-Z0-9]+", title)[:3]
    return "".join([author.lower(), year] + words)[:80]


def _extract_method_name(section_path: str, text: str) -> str:
    sample = f"{section_path}\n{text[:300]}"
    patterns = [
        r"(?:method|model|approach)[:：]\s*([A-Za-z][A-Za-z0-9_\- ]{2,60})",
        r"(?:提出|采用|使用)([A-Za-z][A-Za-z0-9_\- ]{2,60})(?:方法|模型|框架)",
    ]
    for pattern in patterns:
        match = re.search(pattern, sample, re.I)
        if match:
            return match.group(1).strip()
    return ""


def _extract_metric(text: str) -> str:
    metrics = re.findall(r"\b(BLEU|ROUGE(?:-[L12])?|F1|Accuracy|AUC|MRR|Recall|Precision|Perplexity|困惑度|准确率|召回率)\b", text or "", re.I)
    return ", ".join(dict.fromkeys(metrics))


def _extract_dataset(text: str) -> str:
    patterns = [r"(?:dataset|数据集)[:：]?\s*([A-Za-z0-9_\- /,，]{2,80})", r"\b(ImageNet|COCO|SQuAD|GLUE|SuperGLUE|WMT\d{2}|CIFAR-?10|CIFAR-?100)\b"]
    for pattern in patterns:
        match = re.search(pattern, text or "", re.I)
        if match:
            return match.group(1).strip()
    return ""

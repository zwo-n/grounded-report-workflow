"""
docx_builder.py - Word 문서 생성 모듈

라우팅 결과와 LLM 응답을 기반으로 .docx 파일을 생성합니다.

주요 기능:
- 문서 템플릿 로드 및 초기화
- 섹션별 콘텐츠 삽입 (제목, 본문, 표, 이미지 등)
- 출처 정보 및 참고문헌 추가
- 스타일 적용 및 포맷팅
"""

from docx import Document
from docx.shared import Pt

from pipeline.router import Route


def _format_internal_sources(sources: list[dict]) -> tuple[str, str]:
    """
    내부 RAG 출처를 포맷팅합니다.

    Args:
        sources: 검색 결과 리스트

    Returns:
        (인라인 출처 문자열, 참고문서 목록 문자열)
    """
    if not sources:
        return "", ""

    titles = [s.get("source_title", "문서") for s in sources]
    unique_titles = list(dict.fromkeys(titles))  # 중복 제거, 순서 유지

    inline = f"[출처: {', '.join(unique_titles)}]"

    ref_lines = []
    for s in sources:
        title = s.get("source_title", "문서")
        url = s.get("source_url", "")
        if url:
            ref_lines.append(f"- {title} ({url})")
        else:
            ref_lines.append(f"- {title}")

    ref_list = "참고문서:\n" + "\n".join(ref_lines)

    return inline, ref_list


def _format_web_sources(sources: list[dict]) -> str:
    """
    웹 검색 출처를 포맷팅합니다.

    Args:
        sources: 검색 결과 리스트

    Returns:
        인라인 출처 문자열
    """
    if not sources:
        return ""

    parts = []
    for s in sources:
        title = s.get("source_title", "웹페이지")
        url = s.get("source_url", "")
        if url:
            parts.append(f"{title} ({url})")
        else:
            parts.append(title)

    return f"[출처: {', '.join(parts)}]"


def add_section(
    doc: Document,
    section_title: str,
    llm_result: dict,
    decision: Route,
    sources: list[dict],
) -> None:
    """
    문서에 섹션을 추가합니다.

    Args:
        doc: python-docx Document 객체
        section_title: 섹션 제목
        llm_result: LLM 응답 결과 (answer, source_type, source_count 등)
        decision: 라우팅 결과 (Route.AUTO_APPROVE 또는 Route.NEEDS_REVIEW)
        sources: 검색 결과 리스트 (source_title, source_url 포함)
    """
    # 섹션 제목 추가 (Heading 2)
    doc.add_heading(section_title, level=2)

    answer = llm_result.get("answer", "")
    source_type = llm_result.get("source_type", "none")
    source_count = llm_result.get("source_count", 0)

    if decision == Route.AUTO_APPROVE:
        _add_approved_section(doc, answer, source_type, sources)
    else:
        _add_review_section(doc, answer, source_count, decision)


def _add_approved_section(
    doc: Document,
    answer: str,
    source_type: str,
    sources: list[dict],
) -> None:
    """
    자동 승인된 섹션을 추가합니다.

    Args:
        doc: Document 객체
        answer: LLM 생성 답변
        source_type: 출처 유형 ("internal", "web", "none")
        sources: 검색 결과 리스트
    """
    if source_type == "internal":
        # 본문 + 인라인 출처
        inline_ref, ref_list = _format_internal_sources(sources)
        if answer and inline_ref:
            doc.add_paragraph(f"{answer} {inline_ref}")
        elif answer:
            doc.add_paragraph(answer)

        # 참고문서 목록 (섹션 하단)
        if ref_list:
            ref_para = doc.add_paragraph(ref_list)
            ref_para.runs[0].font.size = Pt(9)

    elif source_type == "web":
        # 본문 + 웹 출처 (내부와 구분되는 형식)
        inline_ref = _format_web_sources(sources)
        if answer and inline_ref:
            doc.add_paragraph(f"{answer} {inline_ref}")
        elif answer:
            doc.add_paragraph(answer)

    else:
        # source_type == "none": 출처 표기 없이 본문만
        if answer:
            doc.add_paragraph(answer)


def _add_review_section(
    doc: Document,
    answer: str,
    source_count: int,
    decision: Route,
) -> None:
    """
    검토 필요 섹션을 추가합니다.

    Args:
        doc: Document 객체
        answer: LLM 생성 답변 (참고용)
        source_count: 출처 개수
        decision: 라우팅 결과
    """
    # 검토 필요 표시 (Intense Quote 스타일)
    review_label = f"[{decision.label}]"
    if source_count == 0:
        reason = "근거 문서 없음"
    else:
        reason = "근거 부족 또는 신뢰도 낮음"

    notice = doc.add_paragraph(f"{review_label} {reason}")
    notice.style = "Intense Quote"

    # 참고용 답변 삽입 (있는 경우)
    if answer:
        doc.add_paragraph("(참고용 초안)")
        draft_para = doc.add_paragraph(answer)
        draft_para.runs[0].font.italic = True


def create_document() -> Document:
    """
    새 Document 객체를 생성합니다.

    Returns:
        빈 Document 객체
    """
    return Document()


def save_document(doc: Document, filepath: str) -> None:
    """
    Document를 파일로 저장합니다.

    Args:
        doc: Document 객체
        filepath: 저장 경로
    """
    doc.save(filepath)

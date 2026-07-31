"""
docx_builder.py - Word 문서 생성 모듈

라우팅 결과와 LLM 응답을 기반으로 .docx 파일을 생성합니다.
콘텐츠 판단은 하지 않으며, 서식만 책임집니다.

주요 기능:
- 한글 폰트 정확한 지정 (w:eastAsia XML 레벨 설정)
- Heading 스타일 기반 목차 자동 삽입
- 실제 bullet/numbering 리스트 처리
- 표 헤더 행 음영 처리 (필요시만)
- 출처 정보 및 참고문헌 추가
- Gamba Labs 브랜드 스타일 적용
"""

from docx import Document
from docx.shared import Pt, RGBColor, Inches, Twips
from docx.oxml.ns import qn, nsmap
from docx.oxml import OxmlElement
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.table import Table

from pipeline.router import Route


# =============================================================================
# Gamba Labs 브랜드 컬러 시스템
# =============================================================================
# 주요 색상 (Primary)
COLOR_PRIMARY = RGBColor(0x00, 0x38, 0x99)       # #003899 - 진한 파랑
COLOR_PRIMARY_DARK = RGBColor(0x0c, 0x13, 0x31)  # #0c1331 - 거의 검은 남색

# 보조 색상 (Secondary)
COLOR_ACCENT = RGBColor(0x20, 0xae, 0xe5)        # #20aee5 - 밝은 시안

# 중성 색상 (Neutral)
COLOR_LIGHT_BG = RGBColor(0xf7, 0xf7, 0xfa)      # #f7f7fa - 밝은 회색 배경
COLOR_TEXT_GRAY = RGBColor(0x3c, 0x3c, 0x3c)     # #3c3c3c - 진한 회색 텍스트
COLOR_TEXT_MUTED = RGBColor(0x6c, 0x6c, 0x6c)    # #6c6c6c - 연한 회색 텍스트

# 경고/알림 색상
COLOR_WARNING_BG = RGBColor(0xff, 0xf3, 0xcd)    # #fff3cd - 경고 배경 (연한 노랑)
COLOR_WARNING_TEXT = RGBColor(0x85, 0x6d, 0x04)  # #856d04 - 경고 텍스트 (진한 노랑)
COLOR_WARNING_BORDER = "E0A800"                   # 경고 테두리 (HEX)

# =============================================================================
# 폰트 및 레이아웃 설정
# =============================================================================
DEFAULT_FONT_NAME = "맑은 고딕"
DEFAULT_FONT_SIZE = Pt(11)

# 헤딩 스타일 설정 (크기, 굵기, 색상)
HEADING_STYLES = {
    1: {"size": Pt(24), "bold": True, "color": COLOR_PRIMARY_DARK, "space_before": Pt(0), "space_after": Pt(12)},
    2: {"size": Pt(16), "bold": True, "color": COLOR_PRIMARY, "space_before": Pt(18), "space_after": Pt(8)},
    3: {"size": Pt(13), "bold": True, "color": COLOR_PRIMARY, "space_before": Pt(12), "space_after": Pt(6)},
}

# 본문 줄간격 설정
LINE_SPACING = 1.5  # 1.5줄
PARAGRAPH_SPACE_AFTER = Pt(8)

# 목차 삽입 기준 섹션 수
TOC_THRESHOLD = 5


# =============================================================================
# 폰트 설정 헬퍼 함수
# =============================================================================
def _set_korean_font(run, font_name: str = DEFAULT_FONT_NAME) -> None:
    """
    Run에 한글 폰트를 정확하게 설정합니다.

    w:eastAsia 속성까지 XML 레벨에서 설정하여
    run.font.name만으로는 한글 폰트가 적용되지 않는 문제를 해결합니다.

    Args:
        run: python-docx Run 객체
        font_name: 적용할 폰트명
    """
    run.font.name = font_name
    # w:rFonts 요소의 w:eastAsia 속성 설정
    r = run._element
    rPr = r.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), font_name)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)


def _set_style_korean_font(style, font_name: str = DEFAULT_FONT_NAME) -> None:
    """
    스타일에 한글 폰트를 설정합니다.

    Args:
        style: python-docx Style 객체
        font_name: 폰트명
    """
    style.font.name = font_name
    rPr = style._element.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.insert(0, rFonts)
    rFonts.set(qn('w:eastAsia'), font_name)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)


def _set_paragraph_shading(paragraph, fill_color: str) -> None:
    """
    문단에 배경색(shading)을 설정합니다.

    Args:
        paragraph: python-docx Paragraph 객체
        fill_color: HEX 색상 코드 (# 제외)
    """
    pPr = paragraph._element.get_or_add_pPr()
    shd = OxmlElement('w:shd')
    shd.set(qn('w:val'), 'clear')
    shd.set(qn('w:color'), 'auto')
    shd.set(qn('w:fill'), fill_color)
    pPr.append(shd)


def _set_paragraph_borders(paragraph, color: str, size: int = 4) -> None:
    """
    문단에 테두리를 설정합니다.

    Args:
        paragraph: python-docx Paragraph 객체
        color: HEX 색상 코드 (# 제외)
        size: 테두리 두께 (8분의 1 포인트 단위)
    """
    pPr = paragraph._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')

    for border_name in ['top', 'left', 'bottom', 'right']:
        border = OxmlElement(f'w:{border_name}')
        border.set(qn('w:val'), 'single')
        border.set(qn('w:sz'), str(size))
        border.set(qn('w:space'), '4')
        border.set(qn('w:color'), color)
        pBdr.append(border)

    pPr.append(pBdr)


def _apply_body_paragraph_format(paragraph) -> None:
    """
    본문 문단에 표준 서식(줄간격, 여백)을 적용합니다.

    Args:
        paragraph: python-docx Paragraph 객체
    """
    pf = paragraph.paragraph_format
    pf.line_spacing = LINE_SPACING
    pf.space_after = PARAGRAPH_SPACE_AFTER


# =============================================================================
# 목차(TOC) 관련 함수
# =============================================================================
def _create_toc_paragraph() -> OxmlElement:
    """
    목차 필드를 포함한 문단 XML 요소를 생성합니다.

    Returns:
        목차 필드가 포함된 w:p 요소
    """
    p = OxmlElement('w:p')
    r = OxmlElement('w:r')

    fldChar_begin = OxmlElement('w:fldChar')
    fldChar_begin.set(qn('w:fldCharType'), 'begin')

    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'

    fldChar_separate = OxmlElement('w:fldChar')
    fldChar_separate.set(qn('w:fldCharType'), 'separate')

    fldChar_end = OxmlElement('w:fldChar')
    fldChar_end.set(qn('w:fldCharType'), 'end')

    r.append(fldChar_begin)
    r.append(instrText)
    r.append(fldChar_separate)
    r.append(fldChar_end)

    p.append(r)
    return p


def _create_toc_title_paragraph(font_name: str = DEFAULT_FONT_NAME) -> OxmlElement:
    """
    "목차" 제목 문단 XML 요소를 생성합니다.

    Args:
        font_name: 폰트명

    Returns:
        "목차" 제목이 포함된 w:p 요소
    """
    p = OxmlElement('w:p')

    # 문단 속성 (가운데 정렬, 상하 여백)
    pPr = OxmlElement('w:pPr')
    jc = OxmlElement('w:jc')
    jc.set(qn('w:val'), 'center')
    pPr.append(jc)

    # 상단 여백
    spacing = OxmlElement('w:spacing')
    spacing.set(qn('w:before'), '240')  # 12pt
    spacing.set(qn('w:after'), '120')   # 6pt
    pPr.append(spacing)

    p.append(pPr)

    # Run
    r = OxmlElement('w:r')
    rPr = OxmlElement('w:rPr')

    b = OxmlElement('w:b')
    rPr.append(b)

    rFonts = OxmlElement('w:rFonts')
    rFonts.set(qn('w:eastAsia'), font_name)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rPr.append(rFonts)

    sz = OxmlElement('w:sz')
    sz.set(qn('w:val'), '32')  # 16pt
    rPr.append(sz)

    # 색상 적용 (브랜드 컬러)
    color = OxmlElement('w:color')
    color.set(qn('w:val'), '003899')
    rPr.append(color)

    r.append(rPr)

    t = OxmlElement('w:t')
    t.text = "목차"
    r.append(t)

    p.append(r)
    return p


def _add_toc(doc: Document) -> None:
    """
    문서에 목차(TOC)를 삽입합니다.

    Args:
        doc: python-docx Document 객체
    """
    paragraph = doc.add_paragraph()
    run = paragraph.add_run()

    fldChar_begin = OxmlElement('w:fldChar')
    fldChar_begin.set(qn('w:fldCharType'), 'begin')

    instrText = OxmlElement('w:instrText')
    instrText.set(qn('xml:space'), 'preserve')
    instrText.text = 'TOC \\o "1-3" \\h \\z \\u'

    fldChar_separate = OxmlElement('w:fldChar')
    fldChar_separate.set(qn('w:fldCharType'), 'separate')

    fldChar_end = OxmlElement('w:fldChar')
    fldChar_end.set(qn('w:fldCharType'), 'end')

    r_element = run._r
    r_element.append(fldChar_begin)
    r_element.append(instrText)
    r_element.append(fldChar_separate)
    r_element.append(fldChar_end)


def _insert_toc_after_title(doc: Document) -> None:
    """
    문서 제목(Heading 1) 바로 다음에 목차를 삽입합니다.

    Args:
        doc: python-docx Document 객체
    """
    body = doc._body._element

    insert_index = 0
    for i, child in enumerate(body):
        if child.tag == qn('w:p'):
            pPr = child.find(qn('w:pPr'))
            if pPr is not None:
                pStyle = pPr.find(qn('w:pStyle'))
                if pStyle is not None and pStyle.get(qn('w:val')) == 'Heading1':
                    insert_index = i + 1
                    break

    toc_title = _create_toc_title_paragraph()
    body.insert(insert_index, toc_title)

    toc_field = _create_toc_paragraph()
    body.insert(insert_index + 1, toc_field)

    empty_p = OxmlElement('w:p')
    body.insert(insert_index + 2, empty_p)


def _count_heading2(doc: Document) -> int:
    """
    문서 내 Heading 2 수를 카운트합니다.

    Args:
        doc: python-docx Document 객체

    Returns:
        Heading 2 개수
    """
    count = 0
    for para in doc.paragraphs:
        if para.style and para.style.name == 'Heading 2':
            count += 1
    return count


# =============================================================================
# 리스트 관련 함수
# =============================================================================
def _add_bullet_list(doc: Document, items: list[str]) -> None:
    """
    실제 bullet 리스트를 문서에 추가합니다.

    Args:
        doc: python-docx Document 객체
        items: 리스트 아이템 문자열 리스트
    """
    for item in items:
        para = doc.add_paragraph(item, style='List Bullet')
        para.paragraph_format.space_after = Pt(4)
        for run in para.runs:
            run.font.size = DEFAULT_FONT_SIZE
            run.font.color.rgb = COLOR_TEXT_GRAY
            _set_korean_font(run)


def _add_numbered_list(doc: Document, items: list[str]) -> None:
    """
    실제 numbered 리스트를 문서에 추가합니다.

    Args:
        doc: python-docx Document 객체
        items: 리스트 아이템 문자열 리스트
    """
    for item in items:
        para = doc.add_paragraph(item, style='List Number')
        para.paragraph_format.space_after = Pt(4)
        for run in para.runs:
            run.font.size = DEFAULT_FONT_SIZE
            run.font.color.rgb = COLOR_TEXT_GRAY
            _set_korean_font(run)


# =============================================================================
# 표(Table) 관련 함수
# =============================================================================
def _add_table_with_header(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
) -> Table:
    """
    헤더 행에 브랜드 스타일이 적용된 표를 추가합니다.

    Args:
        doc: python-docx Document 객체
        headers: 헤더 열 리스트
        rows: 데이터 행 리스트

    Returns:
        생성된 Table 객체
    """
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.style = 'Table Grid'
    table.alignment = WD_TABLE_ALIGNMENT.CENTER

    # 헤더 행 설정 (브랜드 컬러 적용)
    header_row = table.rows[0]
    for i, header_text in enumerate(headers):
        cell = header_row.cells[i]
        cell.text = header_text

        # 헤더 셀 음영 (브랜드 Primary Dark 색상)
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), '003899')  # 브랜드 주요 색상
        cell._tc.get_or_add_tcPr().append(shading)

        for para in cell.paragraphs:
            para.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in para.runs:
                run.bold = True
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)  # 흰색 텍스트
                run.font.size = Pt(10)
                _set_korean_font(run)

    # 데이터 행 설정
    for row_idx, row_data in enumerate(rows):
        row = table.rows[row_idx + 1]
        for col_idx, cell_text in enumerate(row_data):
            cell = row.cells[col_idx]
            cell.text = cell_text

            # 짝수 행 배경색 (zebra stripe)
            if row_idx % 2 == 1:
                shading = OxmlElement('w:shd')
                shading.set(qn('w:fill'), 'F7F7FA')
                cell._tc.get_or_add_tcPr().append(shading)

            for para in cell.paragraphs:
                for run in para.runs:
                    run.font.size = Pt(10)
                    run.font.color.rgb = COLOR_TEXT_GRAY
                    _set_korean_font(run)

    return table


# =============================================================================
# 콘텐츠 파싱 및 구조화
# =============================================================================
def _parse_content_structure(text: str) -> list[dict]:
    """
    텍스트를 파싱하여 구조화된 콘텐츠로 변환합니다.

    Args:
        text: 원본 텍스트

    Returns:
        구조화된 콘텐츠 리스트
    """
    if not text:
        return []

    lines = text.strip().split('\n')
    result = []
    current_list = []
    current_list_type = None

    for line in lines:
        stripped = line.strip()

        # Bullet 리스트
        if stripped.startswith('- ') or stripped.startswith('* '):
            if current_list_type != 'bullet':
                if current_list:
                    result.append({
                        "type": current_list_type + "_list",
                        "items": current_list
                    })
                current_list = []
                current_list_type = 'bullet'
            current_list.append(stripped[2:])
            continue

        # Numbered 리스트
        if len(stripped) > 2 and stripped[0].isdigit() and stripped[1] == '.':
            if current_list_type != 'numbered':
                if current_list:
                    result.append({
                        "type": current_list_type + "_list",
                        "items": current_list
                    })
                current_list = []
                current_list_type = 'numbered'
            current_list.append(stripped[2:].strip())
            continue

        # 리스트 종료
        if current_list:
            result.append({
                "type": current_list_type + "_list",
                "items": current_list
            })
            current_list = []
            current_list_type = None

        if not stripped:
            continue

        result.append({"type": "paragraph", "content": stripped})

    if current_list:
        result.append({
            "type": current_list_type + "_list",
            "items": current_list
        })

    return result


def _add_structured_content(doc: Document, text: str) -> None:
    """
    구조화된 콘텐츠를 문서에 추가합니다.

    Args:
        doc: python-docx Document 객체
        text: 원본 텍스트
    """
    structures = _parse_content_structure(text)

    for item in structures:
        if item["type"] == "paragraph":
            para = doc.add_paragraph(item["content"])
            _apply_body_paragraph_format(para)
            for run in para.runs:
                run.font.size = DEFAULT_FONT_SIZE
                run.font.color.rgb = COLOR_TEXT_GRAY
                _set_korean_font(run)
        elif item["type"] == "bullet_list":
            _add_bullet_list(doc, item["items"])
        elif item["type"] == "numbered_list":
            _add_numbered_list(doc, item["items"])


# =============================================================================
# 출처 포맷팅
# =============================================================================
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
    unique_titles = list(dict.fromkeys(titles))

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


# =============================================================================
# 섹션 추가 함수
# =============================================================================
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
        llm_result: LLM 응답 결과
        decision: 라우팅 결과
        sources: 검색 결과 리스트
    """
    # 섹션 제목 (Heading 2) - 브랜드 스타일 적용
    heading = doc.add_heading(section_title, level=2)
    style_config = HEADING_STYLES[2]

    heading.paragraph_format.space_before = style_config["space_before"]
    heading.paragraph_format.space_after = style_config["space_after"]

    for run in heading.runs:
        run.font.size = style_config["size"]
        run.font.bold = style_config["bold"]
        run.font.color.rgb = style_config["color"]
        _set_korean_font(run)

    answer = llm_result.get("answer", "")
    source_type = llm_result.get("source_type", "none")

    if decision == Route.AUTO_APPROVE:
        _add_approved_section(doc, answer, source_type, sources)
    else:
        _add_review_section(doc, answer, llm_result.get("source_count", 0), decision)


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
        source_type: 출처 유형
        sources: 검색 결과 리스트
    """
    if answer:
        _add_structured_content(doc, answer)

    # 출처 추가 (브랜드 Accent 색상 적용)
    if source_type == "internal":
        inline_ref, ref_list = _format_internal_sources(sources)
        if inline_ref:
            ref_para = doc.add_paragraph(inline_ref)
            ref_para.paragraph_format.space_before = Pt(8)
            for run in ref_para.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = COLOR_ACCENT  # 브랜드 시안 색상
                _set_korean_font(run)

        if ref_list:
            ref_para = doc.add_paragraph(ref_list)
            for run in ref_para.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = COLOR_TEXT_MUTED
                _set_korean_font(run)

    elif source_type == "web":
        inline_ref = _format_web_sources(sources)
        if inline_ref:
            ref_para = doc.add_paragraph(inline_ref)
            ref_para.paragraph_format.space_before = Pt(8)
            for run in ref_para.runs:
                run.font.size = Pt(9)
                run.font.color.rgb = COLOR_ACCENT
                _set_korean_font(run)


def _add_review_section(
    doc: Document,
    answer: str,
    source_count: int,
    decision: Route,
) -> None:
    """
    검토 필요 섹션을 추가합니다.
    배지/박스 스타일로 눈에 띄게 표시합니다.

    Args:
        doc: Document 객체
        answer: LLM 생성 답변 (참고용)
        source_count: 출처 개수
        decision: 라우팅 결과
    """
    # 경고 배지 스타일 (배경색 + 테두리)
    if source_count == 0:
        reason = "근거 문서 없음"
    else:
        reason = "근거 부족 또는 신뢰도 낮음"

    notice_text = f"  {decision.label}  |  {reason}"
    notice = doc.add_paragraph(notice_text)

    # 배지 스타일 적용
    notice.paragraph_format.space_before = Pt(8)
    notice.paragraph_format.space_after = Pt(8)
    notice.paragraph_format.left_indent = Inches(0.2)
    notice.paragraph_format.right_indent = Inches(0.2)

    # 배경색 (연한 노랑)
    _set_paragraph_shading(notice, 'FFF3CD')
    # 테두리 (진한 노랑)
    _set_paragraph_borders(notice, 'E0A800', size=6)

    for run in notice.runs:
        run.bold = True
        run.font.size = Pt(10)
        run.font.color.rgb = COLOR_WARNING_TEXT
        _set_korean_font(run)

    # 참고용 초안
    if answer:
        draft_label = doc.add_paragraph("참고용 초안")
        draft_label.paragraph_format.space_before = Pt(12)
        draft_label.paragraph_format.space_after = Pt(4)
        for run in draft_label.runs:
            run.font.size = Pt(9)
            run.bold = True
            run.font.color.rgb = COLOR_TEXT_MUTED
            _set_korean_font(run)

        _add_structured_content(doc, answer)

        # 초안 영역 시각적 구분 (연한 배경)
        # 마지막 추가된 문단들에 이탤릭 적용
        for para in doc.paragraphs[-1:]:
            for run in para.runs:
                run.italic = True


# =============================================================================
# 문서 생성 및 저장
# =============================================================================
def create_document(
    title: str | None = None,
    include_toc: bool = False,
) -> Document:
    """
    새 Document 객체를 생성합니다.

    Args:
        title: 문서 제목 (None이면 제목 없음)
        include_toc: 목차 포함 여부

    Returns:
        초기화된 Document 객체
    """
    doc = Document()

    # 기본 스타일 설정
    style = doc.styles['Normal']
    _set_style_korean_font(style)
    style.font.size = DEFAULT_FONT_SIZE
    style.font.color.rgb = COLOR_TEXT_GRAY
    style.paragraph_format.line_spacing = LINE_SPACING

    # Heading 스타일에 브랜드 컬러 적용
    for level, config in HEADING_STYLES.items():
        heading_style_name = f'Heading {level}'
        if heading_style_name in doc.styles:
            h_style = doc.styles[heading_style_name]
            _set_style_korean_font(h_style)
            h_style.font.size = config["size"]
            h_style.font.bold = config["bold"]
            h_style.font.color.rgb = config["color"]

    if title:
        heading = doc.add_heading(title, level=1)
        style_config = HEADING_STYLES[1]
        heading.paragraph_format.space_after = style_config["space_after"]

        for run in heading.runs:
            run.font.size = style_config["size"]
            run.font.bold = style_config["bold"]
            run.font.color.rgb = style_config["color"]
            _set_korean_font(run)

    if include_toc:
        toc_title = doc.add_paragraph("목차")
        toc_title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        toc_title.paragraph_format.space_before = Pt(12)
        toc_title.paragraph_format.space_after = Pt(6)
        for run in toc_title.runs:
            run.bold = True
            run.font.size = Pt(16)
            run.font.color.rgb = COLOR_PRIMARY
            _set_korean_font(run)
        _add_toc(doc)
        doc.add_paragraph()

    return doc


def build_document(
    sections: list[dict],
    section_results: list[tuple[dict, Route, list[dict]]],
    title: str = "Grounded Report",
    output_path: str = "output.docx",
) -> None:
    """
    섹션 계획과 결과를 받아 문서를 조립합니다.

    Args:
        sections: 섹션 계획 리스트
        section_results: 섹션별 결과
        title: 문서 제목
        output_path: 출력 파일 경로
    """
    include_toc = len(sections) >= TOC_THRESHOLD
    doc = create_document(title=title, include_toc=include_toc)

    for section, (llm_result, decision, sources) in zip(sections, section_results):
        add_section(doc, section["title"], llm_result, decision, sources)

    save_document(doc, output_path)


def save_document(doc: Document, filepath: str, auto_toc: bool = True) -> None:
    """
    Document를 파일로 저장합니다.

    Args:
        doc: Document 객체
        filepath: 저장 경로
        auto_toc: 자동 목차 삽입 여부
    """
    if auto_toc:
        heading2_count = _count_heading2(doc)
        if heading2_count >= TOC_THRESHOLD:
            _insert_toc_after_title(doc)

    doc.save(filepath)


# =============================================================================
# 유틸리티 함수
# =============================================================================
def add_table(
    doc: Document,
    headers: list[str],
    rows: list[list[str]],
) -> Table:
    """
    표를 문서에 추가합니다.

    Args:
        doc: python-docx Document 객체
        headers: 헤더 열 리스트
        rows: 데이터 행 리스트

    Returns:
        생성된 Table 객체
    """
    return _add_table_with_header(doc, headers, rows)

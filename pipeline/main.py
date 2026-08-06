"""
main.py - 파이프라인 메인 모듈

전체 grounded-report-workflow 파이프라인을 조립하고 실행합니다.

실행 흐름:
1. classify_source_type으로 섹션 분류
2. 분류 결과에 따라 검색 전략 결정 (none/internal/web/provided_data)
3. generate_section_draft로 LLM 초안 생성
4. router.route로 승인 결정
5. docx_builder로 문서 삽입

사용법:
    python -m pipeline.main

provided_data 모드:
    from pipeline.data_ingest import ingest_tabular
    chunks = ingest_tabular("data.csv")
    run_pipeline("보고서", template_hint="gambarlabs_report", provided_chunks=chunks)
"""

from typing import Callable

from pipeline.classifier import classify_source_type
from pipeline.rag_tool import search_internal_knowledge
from pipeline.web_search import search_web, _extract_topic_keywords
from pipeline.llm_writer import generate_section_draft
from pipeline.router import route, Route
from pipeline.docx_builder import (
    create_document,
    build_cover_page,
    build_toc_page,
    start_body_content,
    add_section,
    add_references_section,
    collect_references,
    save_document,
    build_from_template,
    get_template_path,
    TOC_THRESHOLD,
)
from pipeline.section_planner import plan_sections
from pipeline.templates import is_fixed_template
from pipeline.data_ingest import ProvidedChunk, filter_chunks_by_keywords

from docx import Document
from pathlib import Path


# 섹션 제목 → 템플릿 플레이스홀더 매핑
_SECTION_TO_PLACEHOLDER = {
    "개요": "OVERVIEW",
    "주요내용": "MAIN_CONTENT",
    "결론및제언": "CONCLUSION",
}


def _build_document_from_template(
    template_path: Path,
    document_title: str,
    section_results: list[tuple],
    unique_sources: list[dict],
) -> Document:
    """
    템플릿 파일을 사용하여 문서를 생성합니다.

    Args:
        template_path: 템플릿 파일 경로
        document_title: 문서 제목
        section_results: 섹션 처리 결과 리스트
        unique_sources: 중복 제거된 출처 리스트

    Returns:
        생성된 Document 객체
    """
    from datetime import date

    # 플레이스홀더 딕셔너리 준비
    placeholders = {
        "{{TITLE}}": document_title,
        "{{PERIOD}}": "[보고 기간]",
        "{{PROJECT}}": "[프로젝트명]",
        "{{REVIEWER}}": "[검토자]",
        "{{REVIEW_DATE}}": "[검토일]",
    }

    # 섹션 내용 매핑
    for section, llm_result, decision, sources, _ in section_results:
        title = section["title"]
        answer = llm_result.get("answer", "")

        # 섹션 제목을 플레이스홀더 키로 변환
        placeholder_key = _SECTION_TO_PLACEHOLDER.get(title)
        if placeholder_key:
            placeholders[f"{{{{{placeholder_key}}}}}"] = answer

    # 참고 자료 목록 생성
    if unique_sources:
        ref_lines = []
        for i, source in enumerate(unique_sources, 1):
            title = source.get("source_title", "출처")
            url = source.get("source_url", "")
            if url:
                ref_lines.append(f"{i}. {title}\n   {url}")
            else:
                ref_lines.append(f"{i}. {title}")
        placeholders["{{REFERENCES}}"] = "\n".join(ref_lines)
    else:
        placeholders["{{REFERENCES}}"] = "(참고 자료 없음)"

    # 템플릿에서 문서 생성
    doc = build_from_template(template_path, placeholders)
    return doc


def process_section(
    section: dict,
    llm_client: Callable[[list[dict]], str] | None = None,
    classifier_client: Callable[[list[dict]], str] | None = None,
    document_title: str | None = None,
) -> tuple[dict, Route, list[dict], str]:
    """
    단일 섹션을 처리합니다.

    Args:
        section: 섹션 정보 (title, query)
        llm_client: LLM 클라이언트 (None이면 실제 Groq API 호출)
        classifier_client: 분류용 LLM 클라이언트 (None이면 실제 Groq API 호출)
        document_title: 문서 제목 (검색 쿼리에 topic 키워드 추가용)

    Returns:
        (llm_result, decision, sources, classified_type)
    """
    title = section["title"]
    query = section["query"]

    # 검색 쿼리에 topic 키워드 포함 (검색 범위 확장 방지)
    search_query = query
    if document_title and document_title not in query:
        search_query = f"{document_title} - {query}"

    # 1. classify_source_type으로 1차 분류
    classified_type = classify_source_type(
        section_title=title,
        section_query=query,
        llm_client=classifier_client,
    )

    # 2. 분류 결과에 따른 처리
    if classified_type == "none":
        # 검색 없이 LLM 호출 (llm_writer가 none 타입 전용 프롬프트 사용)
        llm_result = generate_section_draft(
            section_query=query,
            sources=[],
            source_type="none",
            llm_client=llm_client,
            topic=document_title,
        )
        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, [], classified_type

    elif classified_type == "web":
        # 바로 웹 검색 수행 (topic 포함 쿼리)
        web_results = search_web(search_query, topic=document_title)["results"]
        sources = web_results
        llm_result = generate_section_draft(
            section_query=query,
            sources=sources,
            source_type="web",
            llm_client=llm_client,
            topic=document_title,
        )
        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, sources, classified_type

    else:
        # classified_type == "internal"
        # 내부 RAG 검색 수행 (topic 포함 쿼리)
        internal_results = search_internal_knowledge(search_query)["results"]
        sources = internal_results
        llm_result = generate_section_draft(
            section_query=query,
            sources=sources,
            source_type="internal",
            llm_client=llm_client,
            topic=document_title,
        )

        # 결과가 없거나 source_relevance가 "low"면 웹 폴백
        if len(sources) == 0 or llm_result.get("source_relevance") == "low":
            web_results = search_web(search_query, topic=document_title)["results"]
            if web_results:
                sources = web_results
                llm_result = generate_section_draft(
                    section_query=query,
                    sources=sources,
                    source_type="web",
                    llm_client=llm_client,
                    topic=document_title,
                )

        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, sources, classified_type


def process_section_with_provided_data(
    section: dict,
    provided_chunks: list[ProvidedChunk],
    llm_client: Callable[[list[dict]], str] | None = None,
    document_title: str | None = None,
) -> tuple[dict, Route, list[dict], str]:
    """
    제공 데이터를 사용하여 섹션을 처리합니다.

    Args:
        section: 섹션 정보 (title, query, match_keywords)
        provided_chunks: 전체 chunk 리스트 (1회성 데이터, RAG와 분리)
        llm_client: LLM 클라이언트
        document_title: 문서 제목

    Returns:
        (llm_result, decision, sources, classified_type)
    """
    title = section["title"]
    query = section["query"]

    # 1. 섹션 키워드 추출 (템플릿 정의 + 동적 추출)
    section_keywords = section.get("match_keywords", []).copy()

    # title과 query에서 추가 키워드 추출
    combined_text = f"{title} {query}"
    dynamic_keywords = _extract_topic_keywords(combined_text)
    section_keywords.extend(dynamic_keywords)

    # 중복 제거
    section_keywords = list(dict.fromkeys(section_keywords))

    # 2. 매칭되는 chunk 필터링
    matched_chunks = filter_chunks_by_keywords(
        chunks=provided_chunks,
        section_keywords=section_keywords,
        min_match=1,
    )

    print(f"  키워드: {section_keywords[:5]}{'...' if len(section_keywords) > 5 else ''} -> {len(matched_chunks)}개 매칭")

    # 3. 매칭 결과에 따른 처리
    if not matched_chunks:
        # 매칭 없음 → 근거 부족 처리
        llm_result = {
            "answer": "[근거 부족] 제공된 데이터에서 이 섹션에 해당하는 내용을 찾을 수 없습니다.",
            "source_type": "provided_data",
            "source_count": 0,
            "source_relevance": "low",
            "has_fabrication_risk": False,
        }
        decision = route(
            source_type="provided_data",
            source_count=0,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        return llm_result, decision, [], "provided_data"

    # 4. LLM 호출 (매칭된 chunk를 sources로 전달)
    # chunk를 기존 sources 형식으로 변환
    sources = [
        {
            "content": chunk["content"],
            "source_title": chunk["source_title"],
            "source_url": chunk["source_url"],
            "score": chunk["score"],
        }
        for chunk in matched_chunks[:5]  # 최대 5개
    ]

    llm_result = generate_section_draft(
        section_query=query,
        sources=sources,
        source_type="provided_data",
        llm_client=llm_client,
        topic=document_title,
    )

    decision = route(
        source_type=llm_result["source_type"],
        source_count=llm_result["source_count"],
        source_relevance=llm_result["source_relevance"],
        has_fabrication_risk=llm_result["has_fabrication_risk"],
    )

    return llm_result, decision, sources, "provided_data"


def run_pipeline(
    user_request: str,
    output_path: str = "output.docx",
    template_hint: str | None = None,
    llm_client: Callable[[list[dict]], str] | None = None,
    classifier_client: Callable[[list[dict]], str] | None = None,
    planner_client: Callable[[list[dict]], str] | None = None,
    provided_chunks: list[ProvidedChunk] | None = None,
    force_fixed_template: bool = False,
) -> None:
    """
    전체 파이프라인을 실행합니다.

    Args:
        user_request: 사용자 요청 (예: "클라우드 비용 최적화 제안서 작성해줘")
        output_path: 출력 파일 경로
        template_hint: 문서 유형 힌트 (예: "제안서", "기술 보고서")
        llm_client: LLM 클라이언트 (None이면 실제 Groq API 호출)
        classifier_client: 분류용 LLM 클라이언트 (None이면 실제 Groq API 호출)
        planner_client: 섹션 계획용 LLM 클라이언트 (None이면 실제 Groq API 호출)
        provided_chunks: 제공 데이터 chunk 리스트 (1회성, 메모리 한정, RAG와 분리)
        force_fixed_template: True면 고정 템플릿 강제 사용 (LLM 섹션 계획 스킵)

    Note:
        provided_chunks가 제공되면:
        - source_type="provided_data"로 분류됨
        - 기존 RAG 인덱스(rag_tool.py)와 절대 섞이지 않음
        - 실행 종료 시 메모리에서 자동 폐기됨 (GC)
    """
    print("=" * 60)
    print("Grounded Report Workflow 실행")
    print(f"요청: {user_request}")
    if template_hint:
        print(f"지정된 템플릿: {template_hint}")
    if provided_chunks:
        print(f"제공 데이터: {len(provided_chunks)}개 chunk (1회성, RAG 분리)")
    print("=" * 60)

    # 고정 템플릿 + 제공 데이터 모드 판단
    use_fixed = force_fixed_template or (
        template_hint
        and provided_chunks
        and is_fixed_template(template_hint)
    )

    # 섹션 구성 생성 (단일 LLM 호출로 문서 제목 + 유형 감지 + 섹션 생성)
    # 고정 템플릿이면 LLM 호출 스킵
    print("\n[섹션 계획 생성 중...]")
    sections, document_title, detected_hint = plan_sections(
        user_request,
        template_hint=template_hint,
        llm_client=planner_client,
        force_fixed=use_fixed,
    )
    if document_title:
        print(f"문서 제목: {document_title}")
    if document_title:
        print(f"문서 제목: {document_title}")
    if template_hint is None and detected_hint:
        print(f"감지된 문서 유형: {detected_hint}")
    print(f"생성된 섹션: {[s['title'] for s in sections]}")

    # 문서 제목 fallback
    if not document_title:
        document_title = user_request
        for suffix in ["를 작성해줘", "을 작성해줘", "작성해줘", "해줘", "해주세요"]:
            if document_title.endswith(suffix):
                document_title = document_title[:-len(suffix)].strip()
                break

    # 템플릿 파일 경로 확인 (고정 템플릿이면서 docx_template_path가 있는 경우)
    template_file_path = get_template_path(template_hint) if template_hint else None
    use_template_file = template_file_path is not None and use_fixed

    if use_template_file:
        print(f"[템플릿 문서] {template_file_path} 사용")

    # 섹션별 처리 (출처 수집)
    all_sources = []
    section_results = []  # (section, llm_result, decision, sources, classified_type)

    for section in sections:
        title = section["title"]
        print(f"\n[처리 중] {title}...")

        # 분기: provided_data 모드 vs 기존 모드
        if provided_chunks:
            llm_result, decision, sources, classified_type = process_section_with_provided_data(
                section, provided_chunks, llm_client, document_title
            )
        else:
            llm_result, decision, sources, classified_type = process_section(
                section, llm_client, classifier_client, document_title
            )

        # 출처 수집 (참고 자료 섹션용)
        if sources:
            all_sources.append(sources)

        # 결과 저장
        section_results.append((section, llm_result, decision, sources, classified_type))

        # 진행 상황 출력
        final_source_type = llm_result.get("source_type", "unknown")
        if classified_type != final_source_type:
            print(f"[{title}] 분류: {classified_type} -> 최종: {final_source_type} -> {decision.label}")
        else:
            print(f"[{title}] -> {decision.label} ({final_source_type})")

    # 참고 자료 수집
    unique_sources = collect_references(all_sources)

    # 문서 생성 분기: 템플릿 파일 vs 일반 생성
    if use_template_file:
        # 템플릿 기반 문서 생성
        doc = _build_document_from_template(
            template_file_path,
            document_title,
            section_results,
            unique_sources,
        )
    else:
        # 일반 문서 생성
        doc = create_document()  # 빈 문서 (스타일만 적용)

        # 페이지 1: 표지
        build_cover_page(doc, title=document_title)

        # 페이지 2: 목차 (섹션 수가 충분하면)
        include_toc = len(sections) >= TOC_THRESHOLD
        if include_toc:
            build_toc_page(doc, sections=sections)

        # 페이지 3+: 본문 시작
        start_body_content(doc)

        # 섹션별 문서 추가
        for section, llm_result, decision, sources, _ in section_results:
            add_section(doc, section["title"], llm_result, decision, sources, include_inline_sources=False)

        # 참고 자료 섹션 추가
        if unique_sources:
            add_references_section(doc, unique_sources)

    if unique_sources:
        print(f"\n[참고 자료] {len(unique_sources)}건 추가됨")

    # 문서 저장
    save_document(doc, output_path)
    print("\n" + "=" * 60)
    print(f"문서 생성 완료: {output_path}")
    if provided_chunks:
        print("[제공 데이터] 1회성 데이터 메모리에서 폐기됨 (RAG 오염 없음)")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    # 명령줄 인자가 있으면 사용, 없으면 기본값
    if len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
    else:
        request = "RAG 기반 문서 자동화 기술 역량 보고서를 작성해줘"

    run_pipeline(user_request=request)

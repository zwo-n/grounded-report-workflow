"""
main.py - 파이프라인 메인 모듈

전체 grounded-report-workflow 파이프라인을 조립하고 실행합니다.

실행 흐름:
1. classify_source_type으로 섹션 분류
2. 분류 결과에 따라 검색 전략 결정 (none/internal/web)
3. generate_section_draft로 LLM 초안 생성
4. router.route로 승인 결정
5. docx_builder로 문서 삽입

사용법:
    python -m pipeline.main
"""

from typing import Callable

from pipeline.classifier import classify_source_type
from pipeline.rag_tool import search_internal_knowledge
from pipeline.web_search import search_web
from pipeline.llm_writer import generate_section_draft
from pipeline.router import route, Route
from pipeline.docx_builder import create_document, add_section, save_document
from pipeline.section_planner import plan_sections


def process_section(
    section: dict,
    llm_client: Callable[[list[dict]], str] | None = None,
    classifier_client: Callable[[list[dict]], str] | None = None,
) -> tuple[dict, Route, list[dict], str]:
    """
    단일 섹션을 처리합니다.

    Args:
        section: 섹션 정보 (title, query)
        llm_client: LLM 클라이언트 (None이면 실제 Ollama API 호출)
        classifier_client: 분류용 LLM 클라이언트 (None이면 실제 Ollama API 호출)

    Returns:
        (llm_result, decision, sources, classified_type)
    """
    title = section["title"]
    query = section["query"]

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
        )
        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, [], classified_type

    elif classified_type == "web":
        # 바로 웹 검색 수행
        web_results = search_web(query)["results"]
        sources = web_results
        llm_result = generate_section_draft(
            section_query=query,
            sources=sources,
            source_type="web",
            llm_client=llm_client,
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
        # 내부 RAG 검색 수행
        internal_results = search_internal_knowledge(query)["results"]
        sources = internal_results
        llm_result = generate_section_draft(
            section_query=query,
            sources=sources,
            source_type="internal",
            llm_client=llm_client,
        )

        # 결과가 없거나 source_relevance가 "low"면 웹 폴백
        if len(sources) == 0 or llm_result.get("source_relevance") == "low":
            web_results = search_web(query)["results"]
            if web_results:
                sources = web_results
                llm_result = generate_section_draft(
                    section_query=query,
                    sources=sources,
                    source_type="web",
                    llm_client=llm_client,
                )

        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, sources, classified_type


def run_pipeline(
    user_request: str,
    output_path: str = "output.docx",
    template_hint: str | None = None,
    llm_client: Callable[[list[dict]], str] | None = None,
    classifier_client: Callable[[list[dict]], str] | None = None,
    planner_client: Callable[[list[dict]], str] | None = None,
) -> None:
    """
    전체 파이프라인을 실행합니다.

    Args:
        user_request: 사용자 요청 (예: "클라우드 비용 최적화 제안서 작성해줘")
        output_path: 출력 파일 경로
        template_hint: 문서 유형 힌트 (예: "제안서", "기술 보고서")
        llm_client: LLM 클라이언트 (None이면 실제 Ollama API 호출)
        classifier_client: 분류용 LLM 클라이언트 (None이면 실제 Ollama API 호출)
        planner_client: 섹션 계획용 LLM 클라이언트 (None이면 실제 Ollama API 호출)
    """
    print("=" * 60)
    print("Grounded Report Workflow 실행")
    print(f"요청: {user_request}")
    if template_hint:
        print(f"템플릿 힌트: {template_hint}")
    print("=" * 60)

    # 섹션 구성 동적 생성
    print("\n[섹션 계획 생성 중...]")
    sections = plan_sections(
        user_request, template_hint=template_hint, llm_client=planner_client
    )
    print(f"생성된 섹션: {[s['title'] for s in sections]}")

    # 문서 생성
    doc = create_document()
    doc.add_heading("Grounded Report", level=1)

    # 섹션별 처리
    for section in sections:
        title = section["title"]
        print(f"\n[처리 중] {title}...")

        llm_result, decision, sources, classified_type = process_section(
            section, llm_client, classifier_client
        )

        # 문서에 섹션 추가
        add_section(doc, title, llm_result, decision, sources)

        # 진행 상황 출력
        final_source_type = llm_result.get("source_type", "unknown")
        if classified_type != final_source_type:
            print(f"[{title}] 분류: {classified_type} -> 최종: {final_source_type} -> {decision.label}")
        else:
            print(f"[{title}] -> {decision.label} ({final_source_type})")

    # 문서 저장
    save_document(doc, output_path)
    print("\n" + "=" * 60)
    print(f"문서 생성 완료: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    import sys

    # 명령줄 인자가 있으면 사용, 없으면 기본값
    if len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
    else:
        request = "RAG 기반 문서 자동화 기술 역량 보고서를 작성해줘"

    run_pipeline(user_request=request)

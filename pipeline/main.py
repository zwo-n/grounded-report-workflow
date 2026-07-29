"""
main.py - 파이프라인 메인 모듈

전체 grounded-report-workflow 파이프라인을 조립하고 실행합니다.

실행 흐름:
1. 섹션별 source_type 확인
2. source_type == "none"이면 검색 없이 바로 처리
3. 그 외는 search_internal_knowledge로 내부 검색
4. 결과 부족 시 search_web으로 폴백
5. generate_section_draft로 LLM 초안 생성
6. router.route로 승인 결정
7. docx_builder로 문서 삽입

사용법:
    python -m pipeline.main
"""

from typing import Callable

from pipeline.rag_tool import search_internal_knowledge
from pipeline.web_search import search_web
from pipeline.llm_writer import generate_section_draft
from pipeline.router import route, Route
from pipeline.docx_builder import create_document, add_section, save_document


# 섹션 정의: (제목, 쿼리, source_type)
# source_type이 "none"이면 검색 불필요
SECTIONS = [
    {
        "title": "서론",
        "query": "보고서 서론을 작성해주세요",
        "source_type": "none",
    },
    {
        "title": "회사 기술 역량",
        "query": "회사의 주요 기술 역량과 프로젝트 경험을 설명해주세요",
        "source_type": "internal",  # 내부 RAG에서 충분한 결과 예상
    },
    {
        "title": "차별화 전략",
        "query": "회사의 차별화 전략과 경쟁 우위를 설명해주세요",
        "source_type": "internal",  # 내부 결과 부족 시 웹 폴백 예상
    },
    {
        "title": "시장 동향",
        "query": "RAG 기반 문서 자동화 시장 동향을 설명해주세요",
        "source_type": "web",  # 외부 정보가 필요한 섹션
    },
]


def process_section(
    section: dict,
    llm_client: Callable[[list[dict]], str] | None = None,
) -> tuple[dict, Route, list[dict]]:
    """
    단일 섹션을 처리합니다.

    Args:
        section: 섹션 정보 (title, query, source_type)
        llm_client: LLM 클라이언트 (None이면 실제 Ollama API 호출,
                    테스트 시 mock 함수 주입 가능)

    Returns:
        (llm_result, decision, sources)
    """
    query = section["query"]
    expected_source_type = section["source_type"]

    # 1. source_type == "none"인 섹션은 검색 없이 바로 처리
    if expected_source_type == "none":
        llm_result = {
            "answer": "본 보고서는 회사의 기술 역량과 시장 내 차별화 전략을 종합적으로 정리한 문서입니다. 2024년 주요 프로젝트 성과와 향후 발전 방향을 함께 다루고 있습니다.",
            "source_type": "none",
            "source_count": 0,
            "source_relevance": "low",
            "has_fabrication_risk": False,
        }
        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, []

    # 2. source_type == "web"인 섹션은 바로 웹 검색
    if expected_source_type == "web":
        web_results = search_web(query)["results"]
        sources = web_results
        source_type = "web"
        llm_result = generate_section_draft(
            section_query=query,
            sources=sources,
            source_type=source_type,
            llm_client=llm_client,
        )
        decision = route(
            source_type=llm_result["source_type"],
            source_count=llm_result["source_count"],
            source_relevance=llm_result["source_relevance"],
            has_fabrication_risk=llm_result["has_fabrication_risk"],
        )
        return llm_result, decision, sources

    # 3. source_type == "internal"인 섹션: 내부 RAG 검색
    internal_results = search_internal_knowledge(query)["results"]
    sources = internal_results
    source_type = "internal"

    # 4. 내부 검색으로 LLM 호출
    llm_result = generate_section_draft(
        section_query=query,
        sources=sources,
        source_type=source_type,
        llm_client=llm_client,
    )

    # 5. 결과가 비어있거나 source_relevance가 "low"면 웹 폴백
    if len(sources) == 0 or llm_result.get("source_relevance") == "low":
        web_results = search_web(query)["results"]
        if web_results:
            sources = web_results
            source_type = "web"
            llm_result = generate_section_draft(
                section_query=query,
                sources=sources,
                source_type=source_type,
                llm_client=llm_client,
            )

    # 6. 라우팅 결정
    decision = route(
        source_type=llm_result["source_type"],
        source_count=llm_result["source_count"],
        source_relevance=llm_result["source_relevance"],
        has_fabrication_risk=llm_result["has_fabrication_risk"],
    )

    return llm_result, decision, sources


def run_pipeline(
    output_path: str = "output.docx",
    llm_client: Callable[[list[dict]], str] | None = None,
) -> None:
    """
    전체 파이프라인을 실행합니다.

    Args:
        output_path: 출력 파일 경로
        llm_client: LLM 클라이언트 (None이면 실제 Ollama API 호출,
                    테스트 시 mock 함수 주입 가능)
    """
    print("=" * 60)
    print("Grounded Report Workflow 실행")
    print("=" * 60)

    # 문서 생성
    doc = create_document()
    doc.add_heading("Grounded Report", level=1)

    # 섹션별 처리
    for section in SECTIONS:
        title = section["title"]
        print(f"\n[처리 중] {title}...")

        llm_result, decision, sources = process_section(section, llm_client)

        # 문서에 섹션 추가
        add_section(doc, title, llm_result, decision, sources)

        # 진행 상황 출력
        source_type = llm_result.get("source_type", "unknown")
        print(f"[{title}] -> {decision.label} ({source_type})")

    # 문서 저장
    save_document(doc, output_path)
    print("\n" + "=" * 60)
    print(f"문서 생성 완료: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    run_pipeline()

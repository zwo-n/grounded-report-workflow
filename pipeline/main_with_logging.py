"""
main_with_logging.py - 로깅이 적용된 파이프라인 실행

기존 파이프라인 함수들을 수정하지 않고 런타임에 데코레이터를 적용합니다.

사용법:
    python -m pipeline.main_with_logging "클라우드 비용 최적화 제안서"
"""

from typing import Callable

from pipeline.pipeline_logger import PipelineContext, log_step, print_summary

# 기존 모듈 임포트
from pipeline import classifier
from pipeline import rag_tool
from pipeline import web_search
from pipeline import llm_writer
from pipeline import router
from pipeline import docx_builder
from pipeline import section_planner


def run_pipeline_with_logging(
    user_request: str,
    output_path: str = "output/report.docx",
    template_hint: str | None = None,
    author: str | None = None,
    date: str | None = None,
    llm_client: Callable[[list[dict]], str] | None = None,
    classifier_client: Callable[[list[dict]], str] | None = None,
    planner_client: Callable[[list[dict]], str] | None = None,
    verbose: bool = True,
) -> dict:
    """
    로깅이 적용된 파이프라인 실행

    Args:
        user_request: 사용자 요청
        output_path: 출력 파일 경로
        template_hint: 문서 유형 힌트
        author: 작성자
        date: 작성일
        llm_client: LLM 클라이언트
        classifier_client: 분류용 LLM 클라이언트
        planner_client: 섹션 계획용 LLM 클라이언트
        verbose: 상세 로그 출력 여부

    Returns:
        파이프라인 실행 결과 요약
    """
    # 파이프라인 컨텍스트 생성 (JSON 스트리밍)
    ctx = PipelineContext(
        pipeline_name="grounded_report",
        stream_to_console=verbose,
    )

    # 기존 함수들을 데코레이터로 래핑
    plan_sections = log_step(ctx, "섹션 계획 생성")(section_planner.plan_sections)
    classify_source_type = log_step(ctx, "소스 유형 분류")(classifier.classify_source_type)
    search_internal = log_step(ctx, "내부 RAG 검색")(rag_tool.search_internal_knowledge)
    search_web_fn = log_step(ctx, "웹 검색")(web_search.search_web)
    generate_draft = log_step(ctx, "LLM 초안 생성")(llm_writer.generate_section_draft)
    route_decision = log_step(ctx, "라우팅 결정")(router.route)
    create_doc = log_step(ctx, "문서 생성")(docx_builder.create_document)
    add_section = log_step(ctx, "섹션 추가")(docx_builder.add_section)
    save_doc = log_step(ctx, "문서 저장")(docx_builder.save_document)

    try:
        # 1. 섹션 계획 생성 (문서 제목 포함)
        sections, document_title, detected_hint = plan_sections(
            user_request,
            template_hint=template_hint,
            llm_client=planner_client,
        )

        # 2. 문서 생성 (LLM이 생성한 문서 제목 사용)
        # document_title이 없으면 user_request에서 명령어 어미 제거 시도
        if not document_title:
            # 간단한 fallback: "~해줘", "작성해줘" 등 제거
            document_title = user_request
            for suffix in ["를 작성해줘", "을 작성해줘", "작성해줘", "해줘", "해주세요"]:
                if document_title.endswith(suffix):
                    document_title = document_title[:-len(suffix)].strip()
                    break
            # 여전히 너무 길면 자르기
            if len(document_title) > 50:
                document_title = document_title[:50] + "..."

        include_toc = len(sections) >= docx_builder.TOC_THRESHOLD
        doc = create_doc(
            title=document_title,
            include_toc=include_toc,
            author=author,
            date=date,
        )

        # 3. 섹션별 처리
        for section in sections:
            title = section["title"]
            query = section["query"]

            # 소스 유형 분류
            classified_type = classify_source_type(
                section_title=title,
                section_query=query,
                llm_client=classifier_client,
            )

            # 분류 결과에 따른 검색
            sources = []
            if classified_type == "internal":
                internal_results = search_internal(query)
                sources = internal_results.get("results", [])
            elif classified_type == "web":
                web_results = search_web_fn(query)
                sources = web_results.get("results", [])

            # LLM 초안 생성
            llm_result = generate_draft(
                section_query=query,
                sources=sources,
                source_type=classified_type,
                llm_client=llm_client,
            )

            # 라우팅 결정
            decision = route_decision(
                source_type=llm_result["source_type"],
                source_count=llm_result["source_count"],
                source_relevance=llm_result["source_relevance"],
                has_fabrication_risk=llm_result["has_fabrication_risk"],
            )

            # 섹션 추가
            add_section(doc, title, llm_result, decision, sources)

        # 4. 문서 저장
        save_doc(doc, output_path)

        ctx.finish()
        result = {
            "success": True,
            "output_path": output_path,
            "sections_count": len(sections),
        }

    except Exception as e:
        ctx.finish()
        result = {
            "success": False,
            "error": str(e),
        }

    # 요약 출력
    if verbose:
        print_summary(ctx, detailed=False)

    return {**result, "pipeline_summary": ctx.get_summary()}


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        request = " ".join(sys.argv[1:])
    else:
        request = "RAG 기반 문서 자동화 기술 역량 보고서를 작성해줘"

    result = run_pipeline_with_logging(
        user_request=request,
        author="테스트 작성자",
        date="2026-08-03",
    )

    print(f"\n최종 결과: {'성공' if result['success'] else '실패'}")

"""
rag_tool.py - 사내 RAG 검색 모듈

사내 문서 저장소에서 관련 정보를 검색합니다.
현재는 목업 구현이며, 실제 RAG API로 교체 가능하도록
함수 시그니처와 반환 타입을 계약에 맞춰 설계되었습니다.

요청/응답 계약:
- 입력: {"query": str, "top_k": int, "min_score": float}
- 출력: {"results": [{"content", "source_title", "source_url", "score"}]}

필터링:
- score < min_score인 결과는 제외됨
- 관련 문서가 없으면 빈 리스트 반환 (임의 추정 금지 원칙)

Mock 모드 필터링:
- 쿼리와 문서 내용의 키워드 매칭으로 관련성 시뮬레이션
- 실제 RAG API 연동 시 이 로직은 제거됨
"""

import re
from typing import TypedDict

# 최소 유사도 점수 (이 값 미만은 "관련 문서 없음"으로 처리)
MIN_SCORE_THRESHOLD = 0.7

# Mock 모드에서 쿼리-문서 관련성 체크용 키워드
# 이 키워드 중 하나라도 쿼리에 포함되어야 mock 결과 반환
MOCK_RELEVANT_KEYWORDS = [
    "aws", "bedrock", "langgraph", "rag", "통관", "관세", "문서 자동화",
    "클라우드 비용", "이상탐지", "에이전트", "파이프라인", "기술 역량",
    "프로젝트 경험", "기술스택", "python", "java", "eks",
]


def _is_query_relevant_to_mock(query: str) -> bool:
    """
    쿼리가 mock 데이터와 관련 있는지 확인합니다.

    Args:
        query: 검색 쿼리

    Returns:
        True: mock 데이터와 관련 있음
        False: 관련 없음 (빈 결과 반환해야 함)

    Note:
        실제 RAG API 연동 시 이 함수는 사용되지 않습니다.
        Mock 데이터가 무관한 쿼리에 대해 잘못된 결과를 반환하는 것을 방지합니다.
    """
    query_lower = query.lower()
    for keyword in MOCK_RELEVANT_KEYWORDS:
        if keyword.lower() in query_lower:
            return True
    return False


class SearchResult(TypedDict):
    content: str
    source_title: str
    source_url: str
    score: float


class SearchResponse(TypedDict):
    results: list[SearchResult]


def search_internal_knowledge(
    query: str,
    top_k: int = 3,
    min_score: float = MIN_SCORE_THRESHOLD,
) -> SearchResponse:
    """
    사내 RAG 시스템에서 관련 문서를 검색합니다.

    Args:
        query: 검색 쿼리
        top_k: 반환할 최대 결과 수
        min_score: 최소 유사도 점수 (기본값: 0.7, 미달 시 제외)

    Returns:
        SearchResponse: {"results": [{"content", "source_title", "source_url", "score"}]}

    Note:
        - score < min_score인 결과는 필터링되어 반환되지 않습니다.
        - 관련 문서가 없으면 빈 리스트가 반환됩니다.
        - 실제 RAG API 교체 시에도 동일한 필터링 로직을 적용해야 합니다.
    """
    # TODO: 실제 RAG API 호출로 교체
    # 현재는 mock 데이터이므로 쿼리와 관련 없이 고정 score가 반환됨
    # 실제 RAG 연동 시 query 기반 유사도 점수가 계산되어야 함

    # Mock 모드: 쿼리와 무관한 경우 빈 결과 반환
    if not _is_query_relevant_to_mock(query):
        print(f"[rag] mock 데이터와 무관한 쿼리 (query: {query[:30]}...)")
        return {"results": []}

    mock_results: list[SearchResult] = [
        {
            "content": (
                "2024년 관세 문서 자동화 프로젝트: AWS Bedrock Agent 기반 통관 서류 자동 생성 시스템 구축. "
                "python-docx 라이브러리를 활용한 템플릿 필러 구현으로 수작업 대비 처리 시간 80% 단축."
            ),
            "source_title": "2024_프로젝트_이력.docx",
            "source_url": "rag://internal/2024_프로젝트_이력.docx#section1",
            "score": 0.95,
        },
        {
            "content": (
                "클라우드 비용 이상탐지 프로젝트: LangGraph 기반 6단계 에이전트 파이프라인 설계 "
                "(Detection → Classification → Decision → Action → QA → Logging). "
                "Isolation Forest 및 Z-score 알고리즘으로 비정상 과금 패턴 실시간 탐지."
            ),
            "source_title": "2024_프로젝트_이력.docx",
            "source_url": "rag://internal/2024_프로젝트_이력.docx#section2",
            "score": 0.91,
        },
        {
            "content": (
                "기술스택: AWS Bedrock(Claude, Titan Embedding), LangGraph, RAG(OpenSearch), "
                "이상탐지(Isolation Forest, Z-score), Java/Python 백엔드, REST API 설계. "
                "인프라는 AWS EKS 기반 컨테이너 오케스트레이션 적용."
            ),
            "source_title": "기술스택_정리본.docx",
            "source_url": "rag://internal/기술스택_정리본.docx",
            "score": 0.88,
        },
    ]

    # 유사도 threshold 필터링
    filtered_results = [r for r in mock_results if r["score"] >= min_score]

    # 필터링 결과 로깅
    filtered_count = len(mock_results) - len(filtered_results)
    if filtered_count > 0:
        print(f"[rag] {filtered_count}건 필터링됨 (score < {min_score})")

    if not filtered_results:
        print(f"[rag] 관련 문서 없음 (query: {query[:30]}...)")
        return {"results": []}

    final_results = filtered_results[:top_k]
    print(f"[rag] 결과 {len(final_results)}건 반환")
    return {"results": final_results}

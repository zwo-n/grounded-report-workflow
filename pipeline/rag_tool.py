"""
rag_tool.py - 사내 RAG 검색 모듈

사내 문서 저장소에서 관련 정보를 검색합니다.
현재는 목업 구현이며, 실제 RAG API로 교체 가능하도록
함수 시그니처와 반환 타입을 계약에 맞춰 설계되었습니다.

요청/응답 계약:
- 입력: {"query": str, "top_k": int}
- 출력: {"results": [{"content", "source_title", "source_url", "score"}]}
"""

from typing import TypedDict


class SearchResult(TypedDict):
    content: str
    source_title: str
    source_url: str
    score: float


class SearchResponse(TypedDict):
    results: list[SearchResult]


def search_internal_knowledge(query: str, top_k: int = 3) -> SearchResponse:
    """
    사내 RAG 시스템에서 관련 문서를 검색합니다.

    Args:
        query: 검색 쿼리
        top_k: 반환할 최대 결과 수

    Returns:
        SearchResponse: {"results": [{"content", "source_title", "source_url", "score"}]}
    """
    # TODO: 실제 RAG API 호출로 교체
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

    return {"results": mock_results[:top_k]}

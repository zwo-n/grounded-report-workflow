"""
web_search.py - 웹 검색 모듈

외부 웹에서 관련 정보를 검색합니다.
사내 RAG에서 충분한 근거를 찾지 못했을 때 폴백으로 사용됩니다.

요청/응답 계약 (rag_tool.py와 동일한 필드명 사용):
- 입력: {"query": str, "max_results": int}
- 출력: {"results": [{"content", "source_title", "source_url", "score"}]}

Note: llm_writer.py에서 internal/web 결과를 동일한 코드로 처리하기 위해
rag_tool.py와 필드명을 통일했습니다.
"""

from typing import TypedDict


class SearchResult(TypedDict):
    content: str
    source_title: str
    source_url: str
    score: float


class SearchResponse(TypedDict):
    results: list[SearchResult]


def search_web(query: str, max_results: int = 3) -> SearchResponse:
    """
    웹에서 관련 정보를 검색합니다.

    Args:
        query: 검색 쿼리
        max_results: 반환할 최대 결과 수

    Returns:
        SearchResponse: {"results": [{"content", "source_title", "source_url", "score"}]}
    """
    # TODO: 실제 웹 검색 API 호출로 교체 (Google, Bing, Tavily 등)
    mock_results: list[SearchResult] = [
        {
            "content": (
                "국내 RAG 기반 문서 자동화 시장이 급성장하고 있다. "
                "금융·물류·제조 업계를 중심으로 LLM과 사내 문서를 연동한 자동 리포트 생성 솔루션 도입이 확산되며, "
                "2024년 시장 규모는 전년 대비 2배 이상 성장한 것으로 추정된다."
            ),
            "source_title": "RAG 문서 자동화 시장 동향 - AI타임스",
            "source_url": "https://mock-news.example.com/rag-market-trend-2024",
            "score": 0.85,
        },
        {
            "content": (
                "주요 SaaS 기업들이 실시간 문서 연동 기능을 고도화하고 있다. "
                "A사는 Confluence·Notion 실시간 동기화를, B사는 SharePoint 양방향 연동을 출시하며 "
                "기업용 지식 관리 시장 경쟁이 심화되고 있다."
            ),
            "source_title": "SaaS 문서 연동 경쟁 심화 - 테크뉴스",
            "source_url": "https://mock-news.example.com/saas-document-sync-competition",
            "score": 0.79,
        },
        {
            "content": (
                "전문가들은 RAG 기반 문서 자동화의 핵심 과제로 '환각(hallucination) 방지'를 꼽는다. "
                "검색 결과 외 내용을 생성하지 않도록 출처 검증 파이프라인을 필수로 구축해야 한다는 의견이 지배적이다."
            ),
            "source_title": "RAG 환각 방지 전략 - AI인사이트",
            "source_url": "https://mock-news.example.com/rag-hallucination-prevention",
            "score": 0.72,
        },
    ]

    return {"results": mock_results[:max_results]}

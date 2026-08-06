"""
web_search.py - 통합 웹 검색 모듈

Tavily API (해외/글로벌)와 Naver API (국내) 검색 결과를 통합합니다.
사내 RAG에서 충분한 근거를 찾지 못했을 때 폴백으로 사용됩니다.

요청/응답 계약 (rag_tool.py와 동일한 필드명 사용):
- 입력: {"query": str, "max_results": int}
- 출력: {"results": [{"content", "source_title", "source_url", "score"}]}

환경변수:
- TAVILY_API_KEY: Tavily API 키
- NAVER_CLIENT_ID: NCP API Hub 클라이언트 ID
- NAVER_CLIENT_SECRET: NCP API Hub 클라이언트 시크릿
- USE_MOCK_SEARCH: true면 API 호출 없이 mock 데이터 반환 (기본값: false)

필터링:
- score < MIN_SCORE_THRESHOLD 결과 제외
- EXCLUDED_DOMAINS에 포함된 도메인 결과 제외

검색 전략:
- search_tavily(): 해외 기술 동향, 글로벌 사례, 학술 자료
- search_naver(): 국내 뉴스, 도입 사례, 시장 동향
- search_web(): 둘 다 호출해서 통합 (기본)
"""

import os
import re
from typing import TypedDict
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from tavily import TavilyClient

# .env 파일에서 환경변수 로드
load_dotenv()

# =============================================================================
# LLM 설정 (쿼리 번역용 - Groq)
# =============================================================================

from groq import Groq

MODEL_NAME = "openai/gpt-oss-20b"
_groq_client: Groq | None = None


def _get_groq_client() -> Groq:
    """Groq 클라이언트 싱글톤"""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client

# =============================================================================
# 필터링 설정
# =============================================================================

# 최소 관련성 점수 (이 값 미만은 제외)
MIN_SCORE_THRESHOLD = 0.4

# 텍스트 근거로 부적합한 도메인 (SNS, 영상 플랫폼 등)
EXCLUDED_DOMAINS = [
    "youtube.com",
    "youtu.be",
    "tiktok.com",
    "instagram.com",
    "twitter.com",
    "x.com",
    "facebook.com",
    "fb.com",
    "reddit.com",
    "pinterest.com",
    "threads.net",
]

# topic 무관 콘텐츠 패턴 (인물 기사, 부고, 인터뷰 등)
IRRELEVANT_PATTERNS = [
    r"(인터뷰|대담|만나다|취임|사퇴|퇴임|부고|별세|타계|사망)",
    r"(대표이사|CEO|회장|사장|이사).*?(취임|선임|연임)",
    r"(수상|시상|공로상|대상|표창)",
]

# Naver 검색 전용 제외 도메인 (품질 편차 큼)
NAVER_EXCLUDED_DOMAINS = EXCLUDED_DOMAINS + [
    "blog.naver.com",
    "cafe.naver.com",
]

# =============================================================================
# API 설정
# =============================================================================

# NCP API Hub 엔드포인트
NAVER_NEWS_SEARCH_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"

# =============================================================================
# 내부 상태
# =============================================================================

_tavily_client: TavilyClient | None = None
_tavily_call_count: int = 0
_naver_call_count: int = 0


def _is_mock_mode() -> bool:
    """USE_MOCK_SEARCH 환경변수 확인"""
    value = os.getenv("USE_MOCK_SEARCH", "false").strip().lower()
    result = value in ("true", "1", "yes")
    print(f"[DEBUG] USE_MOCK_SEARCH={value}, _is_mock_mode={result}", flush=True)
    return result


# =============================================================================
# 쿼리 번역 (한국어 → 영어)
# =============================================================================


def _translate_query_to_english(query: str) -> str:
    """
    한국어 검색 쿼리를 영어로 번역합니다.

    Args:
        query: 한국어 검색 쿼리

    Returns:
        영어로 번역된 검색 쿼리 (실패 시 원본 반환)
    """
    if _is_mock_mode():
        # Mock 모드에서는 번역 없이 원본 반환
        return query

    try:
        client = _get_groq_client()
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a translator. Translate the given Korean search query "
                        "to English. Output ONLY the translated query, nothing else. "
                        "Keep it concise and search-friendly. Do not add explanations."
                    ),
                },
                {"role": "user", "content": query},
            ],
            temperature=0.3,
            max_tokens=256,
        )

        translated = response.choices[0].message.content.strip() if response.choices[0].message.content else ""

        if translated:
            print(f"[translate] '{query}' → '{translated}'")
            return translated

        return query

    except Exception as e:
        print(f"[translate] ERROR: {type(e).__name__}: {e}, 원본 쿼리 사용")
        return query


# =============================================================================
# 공통 유틸리티
# =============================================================================


def _extract_domain(url: str) -> str:
    """URL에서 도메인을 추출합니다."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if domain.startswith("www."):
            domain = domain[4:]
        return domain
    except Exception:
        return ""


def _is_excluded_domain(url: str, excluded_list: list[str]) -> bool:
    """URL이 제외 대상 도메인인지 확인합니다."""
    domain = _extract_domain(url)
    for excluded in excluded_list:
        if domain == excluded or domain.endswith("." + excluded):
            return True
    return False


def _is_irrelevant_content(title: str, content: str) -> bool:
    """
    topic과 무관한 콘텐츠(인물 기사 등)인지 확인합니다.

    Args:
        title: 기사 제목
        content: 기사 내용

    Returns:
        True: 무관한 콘텐츠 (필터링 대상)
        False: 관련 있는 콘텐츠
    """
    import re

    text = f"{title} {content}"
    for pattern in IRRELEVANT_PATTERNS:
        if re.search(pattern, text):
            return True
    return False


def _check_topic_relevance(
    title: str, content: str, topic_keywords: list[str]
) -> bool:
    """
    검색 결과가 topic과 관련 있는지 확인합니다.

    매칭 전략: 키워드 중 1개 이상 포함되면 관련 있음으로 판단.
    (무관 콘텐츠는 _is_irrelevant_content에서 별도 필터링)

    Args:
        title: 기사 제목
        content: 기사 내용
        topic_keywords: topic에서 추출한 키워드 리스트

    Returns:
        True: topic과 관련 있음
        False: topic과 무관함
    """
    if not topic_keywords:
        return True  # 키워드 없으면 모두 허용

    text = f"{title} {content}".lower()

    # 키워드 중 1개라도 포함되면 관련 있음
    for keyword in topic_keywords:
        if keyword.lower() in text:
            return True
    return False


def _extract_topic_keywords(topic: str) -> list[str]:
    """
    topic에서 핵심 키워드를 추출합니다.

    Args:
        topic: 문서 주제 (예: "클라우드 비용 최적화 제안서")

    Returns:
        키워드 리스트 (예: ["클라우드", "비용", "최적화"])
    """
    import re

    if not topic:
        return []

    # 불용어 제거
    stopwords = {"제안서", "보고서", "분석", "관련", "대한", "위한", "통한"}

    # 한글/영문 단어 추출 (2글자 이상)
    words = re.findall(r"[가-힣a-zA-Z]{2,}", topic)
    keywords = [w for w in words if w not in stopwords]

    return keywords


def _clean_html(text: str) -> str:
    """HTML 태그를 제거합니다."""
    clean = re.sub(r"<[^>]+>", "", text)
    clean = clean.replace("&quot;", '"')
    clean = clean.replace("&amp;", "&")
    clean = clean.replace("&lt;", "<")
    clean = clean.replace("&gt;", ">")
    clean = clean.replace("&nbsp;", " ")
    return clean.strip()


# =============================================================================
# 타입 정의
# =============================================================================


class SearchResult(TypedDict):
    content: str
    source_title: str
    source_url: str
    score: float


class SearchResponse(TypedDict):
    results: list[SearchResult]


# =============================================================================
# Tavily 검색 (해외/글로벌)
# =============================================================================


def _get_tavily_client() -> TavilyClient | None:
    """Tavily 클라이언트를 반환합니다. API 키가 없으면 None."""
    global _tavily_client
    if _tavily_client is None:
        api_key = os.getenv("TAVILY_API_KEY", "").strip().strip('"')
        if api_key:
            _tavily_client = TavilyClient(api_key=api_key)
    return _tavily_client


def _filter_tavily_results(
    results: list[dict],
    topic_keywords: list[str] | None = None,
) -> tuple[list[dict], dict[str, int]]:
    """Tavily 검색 결과를 필터링합니다."""
    filtered = []
    stats = {"low_score": 0, "excluded_domain": 0, "irrelevant": 0, "off_topic": 0}

    for item in results:
        score = item.get("score", 0.0)
        url = item.get("source_url", "")
        title = item.get("source_title", "")
        content = item.get("content", "")

        if score < MIN_SCORE_THRESHOLD:
            stats["low_score"] += 1
            continue

        if _is_excluded_domain(url, EXCLUDED_DOMAINS):
            stats["excluded_domain"] += 1
            continue

        if _is_irrelevant_content(title, content):
            stats["irrelevant"] += 1
            continue

        if topic_keywords and not _check_topic_relevance(title, content, topic_keywords):
            stats["off_topic"] += 1
            continue

        filtered.append(item)

    return filtered, stats


def _get_tavily_mock_results(max_results: int) -> list[SearchResult]:
    """Tavily Mock 데이터를 반환합니다."""
    mock_data: list[SearchResult] = [
        {
            "content": (
                "Enterprise RAG adoption is accelerating globally. "
                "Financial services and manufacturing sectors lead in deploying "
                "LLM-based document automation solutions."
            ),
            "source_title": "Enterprise RAG Market Trends 2024 - TechInsights",
            "source_url": "https://mock-news.example.com/rag-market-trend-2024",
            "score": 0.85,
        },
        {
            "content": (
                "Major SaaS companies are enhancing real-time document integration. "
                "Confluence and Notion sync features are becoming standard."
            ),
            "source_title": "SaaS Document Integration - TechNews",
            "source_url": "https://mock-news.example.com/saas-document-sync",
            "score": 0.79,
        },
    ]
    return mock_data[:max_results]


def search_tavily(
    query: str,
    max_results: int = 5,
    topic_keywords: list[str] | None = None,
) -> SearchResponse:
    """
    Tavily API로 해외/글로벌 웹 검색을 수행합니다.

    Args:
        query: 검색 쿼리 (영어 권장)
        max_results: 반환할 최대 결과 수
        topic_keywords: topic 관련성 필터용 키워드 리스트

    Returns:
        SearchResponse: {"results": [...]}
    """
    global _tavily_call_count
    _tavily_call_count += 1

    if _is_mock_mode():
        print(f"[tavily] MOCK 모드 (호출 #{_tavily_call_count}): {query[:50]}...")
        return {"results": _get_tavily_mock_results(max_results)}

    print(f"[tavily] 호출 #{_tavily_call_count}: {query[:50]}...")

    client = _get_tavily_client()
    if client is None:
        print("[tavily] ERROR: TAVILY_API_KEY가 설정되지 않음")
        return {"results": []}

    try:
        fetch_count = min(max_results + 5, 10)
        response = client.search(
            query=query,
            max_results=fetch_count,
            search_depth="basic",
            include_answer=False,
            include_raw_content=False,
        )

        raw_results: list[SearchResult] = []
        for item in response.get("results", []):
            raw_results.append({
                "content": item.get("content", ""),
                "source_title": item.get("title", ""),
                "source_url": item.get("url", ""),
                "score": item.get("score", 0.0),
            })

        filtered_results, stats = _filter_tavily_results(raw_results, topic_keywords)

        total_filtered = sum(stats.values())
        if total_filtered > 0:
            reasons = []
            if stats["low_score"] > 0:
                reasons.append(f"score<{MIN_SCORE_THRESHOLD}: {stats['low_score']}건")
            if stats["excluded_domain"] > 0:
                reasons.append(f"제외도메인: {stats['excluded_domain']}건")
            if stats["irrelevant"] > 0:
                reasons.append(f"무관콘텐츠: {stats['irrelevant']}건")
            if stats["off_topic"] > 0:
                reasons.append(f"topic무관: {stats['off_topic']}건")
            print(f"[tavily] {total_filtered}건 필터링됨 ({', '.join(reasons)})")

        final_results = filtered_results[:max_results]
        print(f"[tavily] 결과 {len(final_results)}건 반환")
        return {"results": final_results}

    except Exception as e:
        print(f"[tavily] ERROR: {type(e).__name__}: {e}")
        return {"results": []}


# =============================================================================
# Naver 검색 (국내)
# =============================================================================


def _get_naver_credentials() -> tuple[str, str] | None:
    """네이버 API 인증 정보를 반환합니다."""
    client_id = os.getenv("NAVER_CLIENT_ID", "").strip().strip('"')
    client_secret = os.getenv("NAVER_CLIENT_SECRET", "").strip().strip('"')
    if client_id and client_secret:
        return (client_id, client_secret)
    return None


def _calculate_naver_score(rank: int, total: int) -> float:
    """순위 기반 점수를 계산합니다 (1위: 1.0, 마지막: 0.5)."""
    if total <= 1:
        return 1.0
    return 1.0 - (0.5 * (rank - 1) / (total - 1))


def _get_naver_mock_results(max_results: int) -> list[SearchResult]:
    """Naver Mock 데이터를 반환합니다."""
    mock_data: list[SearchResult] = [
        {
            "content": (
                "국내 주요 기업들이 RAG 기반 문서 자동화 솔루션 도입을 확대하고 있다. "
                "금융·제조·물류 업계를 중심으로 LLM 기반 보고서 생성 시스템 구축이 활발히 진행 중이다."
            ),
            "source_title": "국내 기업 RAG 도입 현황 - AI타임스",
            "source_url": "https://mock-news.example.com/korea-rag-adoption",
            "score": 1.0,
        },
        {
            "content": (
                "그리드원이 국내형 Agentic Automation 플랫폼 전략을 발표했다. "
                "AI Agent, RPA, RAG 기능을 통합한 GO;DO 플랫폼으로 기업 업무 자동화 시장 공략에 나선다."
            ),
            "source_title": "그리드원, 엔터프라이즈 AI 플랫폼 전략 발표",
            "source_url": "https://mock-news.example.com/gridone-platform",
            "score": 0.9,
        },
    ]
    return mock_data[:max_results]


def search_naver(
    query: str,
    max_results: int = 5,
    topic_keywords: list[str] | None = None,
) -> SearchResponse:
    """
    NCP API Hub로 네이버 뉴스 검색을 수행합니다.

    Args:
        query: 검색 쿼리 (한국어)
        max_results: 반환할 최대 결과 수
        topic_keywords: topic 관련성 필터용 키워드 리스트

    Returns:
        SearchResponse: {"results": [...]}
    """
    global _naver_call_count
    _naver_call_count += 1

    if _is_mock_mode():
        print(f"[naver] MOCK 모드 (호출 #{_naver_call_count}): {query[:50]}...")
        return {"results": _get_naver_mock_results(max_results)}

    print(f"[naver] 호출 #{_naver_call_count}: {query[:50]}...")

    credentials = _get_naver_credentials()
    if credentials is None:
        print("[naver] ERROR: NAVER_CLIENT_ID/SECRET이 설정되지 않음")
        return {"results": []}

    client_id, client_secret = credentials

    try:
        fetch_count = min(max_results + 5, 10)

        headers = {
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
        }

        params = {
            "query": query,
            "display": fetch_count,
            "start": 1,
            "sort": "sim",
        }

        response = requests.get(
            NAVER_NEWS_SEARCH_URL,
            headers=headers,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()

        items = data.get("items", [])
        raw_results: list[SearchResult] = []
        stats = {"excluded_domain": 0, "irrelevant": 0, "off_topic": 0}

        for rank, item in enumerate(items, 1):
            url = item.get("link", "")
            title = _clean_html(item.get("title", ""))
            content = _clean_html(item.get("description", ""))

            if _is_excluded_domain(url, NAVER_EXCLUDED_DOMAINS):
                stats["excluded_domain"] += 1
                continue

            if _is_irrelevant_content(title, content):
                stats["irrelevant"] += 1
                continue

            if topic_keywords and not _check_topic_relevance(title, content, topic_keywords):
                stats["off_topic"] += 1
                continue

            raw_results.append({
                "content": content,
                "source_title": title,
                "source_url": url,
                "score": _calculate_naver_score(rank, len(items)),
            })

        total_filtered = sum(stats.values())
        if total_filtered > 0:
            reasons = []
            if stats["excluded_domain"] > 0:
                reasons.append(f"제외도메인: {stats['excluded_domain']}건")
            if stats["irrelevant"] > 0:
                reasons.append(f"무관콘텐츠: {stats['irrelevant']}건")
            if stats["off_topic"] > 0:
                reasons.append(f"topic무관: {stats['off_topic']}건")
            print(f"[naver] {total_filtered}건 필터링됨 ({', '.join(reasons)})")

        final_results = raw_results[:max_results]
        print(f"[naver] 결과 {len(final_results)}건 반환")
        return {"results": final_results}

    except requests.exceptions.RequestException as e:
        print(f"[naver] ERROR: 요청 실패 - {type(e).__name__}: {e}")
        return {"results": []}
    except Exception as e:
        print(f"[naver] ERROR: {type(e).__name__}: {e}")
        return {"results": []}


# =============================================================================
# 통합 검색 (Tavily + Naver)
# =============================================================================


def search_web(
    query: str,
    query_global: str | None = None,
    max_results: int = 5,
    topic: str | None = None,
) -> SearchResponse:
    """
    Tavily (해외)와 Naver (국내) 검색 결과를 통합합니다.

    Args:
        query: 검색 쿼리 (한국어, Naver 검색에 사용)
        query_global: 영어 쿼리 (Tavily 검색에 사용, None이면 자동 번역)
        max_results: 반환할 최대 결과 수 (각 소스별 max_results/2 + 1)
        topic: 문서 주제 (관련성 필터링에 사용)

    Returns:
        SearchResponse: {"results": [...]} - 통합된 검색 결과

    Note:
        - query_global이 None이면 LLM을 통해 한국어 → 영어 자동 번역
        - Tavily 결과에는 [글로벌] 태그 추가
        - Naver 결과에는 [국내] 태그 추가
        - topic과 무관한 결과(인물 기사 등)는 필터링됨
        - score 기준 내림차순 정렬
    """
    print(f"[search_web] 통합 검색 시작: {query[:50]}...")

    # topic에서 키워드 추출
    topic_keywords = _extract_topic_keywords(topic) if topic else None
    if topic_keywords:
        print(f"[search_web] topic 키워드: {topic_keywords}")

    # 각 소스별 결과 수 계산
    per_source = max(max_results // 2 + 1, 2)

    # Tavily 검색 (해외) - 영어 쿼리 자동 번역
    tavily_query = query_global if query_global else _translate_query_to_english(query)
    tavily_results = search_tavily(tavily_query, max_results=per_source, topic_keywords=topic_keywords)

    # Naver 검색 (국내)
    naver_results = search_naver(query, max_results=per_source, topic_keywords=topic_keywords)

    # 결과 통합
    combined: list[SearchResult] = []

    for item in tavily_results["results"]:
        combined.append({
            "content": item["content"],
            "source_title": f"[글로벌] {item['source_title']}",
            "source_url": item["source_url"],
            "score": item["score"],
        })

    for item in naver_results["results"]:
        combined.append({
            "content": item["content"],
            "source_title": f"[국내] {item['source_title']}",
            "source_url": item["source_url"],
            "score": item["score"],
        })

    # score 기준 정렬
    combined.sort(key=lambda x: x["score"], reverse=True)

    # max_results까지만 반환
    final_results = combined[:max_results]

    print(
        f"[search_web] 통합 완료: Tavily {len(tavily_results['results'])}건 + "
        f"Naver {len(naver_results['results'])}건 → {len(final_results)}건"
    )

    return {"results": final_results}


# =============================================================================
# 호출 횟수 관리
# =============================================================================


def get_call_counts() -> dict[str, int]:
    """각 API별 호출 횟수를 반환합니다."""
    return {
        "tavily": _tavily_call_count,
        "naver": _naver_call_count,
    }


def reset_call_counts() -> None:
    """호출 횟수 카운터를 초기화합니다."""
    global _tavily_call_count, _naver_call_count
    _tavily_call_count = 0
    _naver_call_count = 0

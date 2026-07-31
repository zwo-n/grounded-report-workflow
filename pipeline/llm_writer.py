"""
llm_writer.py - LLM 기반 텍스트 생성 모듈

Ollama를 통해 qwen2.5:7b-instruct-q4_0 모델을 호출하여
구조화된 JSON 형식의 응답을 생성합니다.

주요 기능:
- Ollama API 호출 및 응답 파싱
- 프롬프트 구성 및 전송
- JSON 스키마 기반 구조화 출력
- 응답 언어 검증 및 이탈 감지 시 재생성 (구 lang_guard.py, 이 파일로 통합됨)

LLM 판단 영역:
- 데이터 소스 선택
- 출처 메타데이터 생성:
  - source_type: 사용한 출처 유형 (아래 3가지 값만 허용)
    - "internal": 사내 RAG 검색 결과를 근거로 사용
    - "web": 웹 검색 결과를 근거로 사용 (내부 근거 부족 시 폴백)
    - "none": 근거가 필요 없는 서술형 섹션
  - source_count: 참조한 출처 개수
  - source_relevance: 출처의 관련성 점수
  - has_fabrication_risk: 허위 생성 위험 여부

Note: 이 모듈에서 생성된 메타데이터는 router.py로 전달되어
최종 승인 여부(auto_approved/review_required)가 결정됩니다.
"""

import json
import re
import requests
from typing import Callable


OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:7b-instruct-q4_0"

# 언어 이탈(중국어 등) 감지 시 재생성 시도 횟수 상한.
# scripts/lang_guard_test.py 실측(source_type=none, N=30): 이탈률 23.3%.
# 시도가 독립이라 가정하면 5회 연속 이탈 확률은 0.233^5 ≈ 0.07%로
# 무한 루프 위험 없이 사실상 항상 정상 응답을 얻을 수 있는 수준.
MAX_LANG_RETRY = 5


def check_korean_ratio(text: str) -> float:
    """
    텍스트에서 한글 문자 비율을 계산합니다.

    Args:
        text: 검사할 텍스트

    Returns:
        한글 문자 비율 (0.0 ~ 1.0)
        공백, 숫자, 특수문자를 제외한 문자 중 한글의 비율
    """
    if not text:
        return 0.0

    # 공백, 숫자, 특수문자, 구두점 제외 (실제 "글자"만 카운트)
    # 한글: 가-힣 (완성형), ᄀ-ᇿ (자모)
    # 영문, 중국어 등 다른 문자도 포함해서 전체 문자 수 계산
    letters_only = re.sub(r'[\s\d\W]', '', text, flags=re.UNICODE)

    if not letters_only:
        return 0.0

    # 한글 문자 카운트 (완성형 + 자모)
    korean_pattern = re.compile(r'[가-힣ᄀ-ᇿ]')
    korean_chars = korean_pattern.findall(letters_only)

    return len(korean_chars) / len(letters_only)


def has_chinese(text: str, threshold: float = 0.0) -> bool:
    """
    텍스트에 중국어가 threshold 비율을 초과하여 포함되어 있는지 확인합니다.

    Args:
        text: 검사할 텍스트
        threshold: 중국어 비율 임계값 (기본값 0.0 = 0%, 중국어가 한 글자라도
                   있으면 감지. 하네스 우회 시 즉시 차단하기 위한 fallback이므로
                   허용 오차를 두지 않음)

    Returns:
        True: 중국어가 threshold를 초과하여 포함됨 (threshold=0.0이면 1글자라도 포함 시)
        False: 중국어가 없음 (threshold 이하)
    """
    if not text:
        return False

    letters_only = re.sub(r'[\s\d\W]', '', text, flags=re.UNICODE)
    if not letters_only:
        return False

    # 중국어 문자 범위 (CJK Unified Ideographs)
    # 한자는 한국어에서도 쓰이지만, qwen 이탈 시 중국어 간체자가 주로 나옴
    chinese_pattern = re.compile(r'[一-鿿]')
    chinese_chars = chinese_pattern.findall(letters_only)

    if not chinese_chars:
        return False

    return len(chinese_chars) / len(letters_only) > threshold


def is_language_valid(text: str, min_korean_ratio: float = 0.5) -> bool:
    """
    텍스트가 유효한 한국어인지 검증합니다.

    Args:
        text: 검사할 텍스트
        min_korean_ratio: 최소 한글 비율 (기본값 0.5 = 50%)
                          기술 용어(AWS, Bedrock, LangGraph 등)가 많이 포함된
                          정상적인 한국어 답변도 50% 이상을 유지함.
                          중국어 이탈은 has_chinese()에서 별도로 감지.

    Returns:
        True: 유효한 한국어 (비율 충족 또는 빈 문자열)
        False: 언어 이탈 (한글 비율 미달)

    Note:
        - 빈 문자열은 True를 반환합니다. (근거 없음 케이스)
        - 중국어가 한 글자라도 포함되면 has_chinese()에서 먼저 차단됩니다.
    """
    # 빈 문자열은 정상 케이스 (근거 없음 = answer가 빈 값)
    if not text or not text.strip():
        return True

    # 중국어가 한 글자라도 포함되면 언어 이탈로 판단 (0% 허용)
    if has_chinese(text):
        return False

    ratio = check_korean_ratio(text)
    return ratio >= min_korean_ratio


SYSTEM_PROMPT = """당신은 보고서 작성을 돕는 AI 어시스턴트입니다.

## 언어 규칙 (절대 준수)
- "answer" 필드는 반드시 한국어로만 작성하세요.
- 중국어(中文), 일본어 등 다른 언어로 절대 전환하지 마세요. 문장 중간에도 예외 없습니다.
- 영어 기술 용어(AWS, API, Bedrock, LangGraph 등)는 원문 그대로 사용 가능합니다.

중요한 규칙:
1. 반드시 제공된 검색 결과(source) 문서만을 근거로 답변하세요.
2. 검색 결과에 없는 내용은 절대 지어내지 마세요. 추측하거나 상상하지 마세요.
3. 근거가 부족하면 솔직하게 "제공된 자료에서 관련 내용을 찾을 수 없습니다"라고 답하세요.

응답 형식:
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

{
    "answer": "검색 결과를 바탕으로 작성한 답변 내용",
    "source_type": "internal 또는 web (제공된 source_type 값 사용)",
    "source_count": 실제로 참조한 출처 개수 (정수),
    "source_relevance": "high/medium/low 중 하나 (출처와 질문의 관련성)",
    "has_fabrication_risk": true 또는 false (근거 없이 생성한 내용이 있는지)
}

source_relevance 판단 기준:
- high: 질문에 직접적으로 답할 수 있는 명확한 근거가 있음
- medium: 관련 정보는 있으나 직접적인 답변은 아님
- low: 관련성이 낮거나 근거가 불충분함

has_fabrication_risk 판단 기준:
- false: 모든 내용이 제공된 출처에서 확인됨
- true: 출처에서 확인할 수 없는 내용이 포함됨

예시:
질문: AWS 기반 기술 역량을 설명해주세요.
검색 결과: [출처 1] 회사는 AWS Bedrock을 활용한 통관 서류 자동화 시스템을 구축함.

올바른 응답:
{
    "answer": "당사는 AWS Bedrock을 활용하여 통관 서류 자동화 시스템을 구축했습니다.",
    "source_type": "internal",
    "source_count": 1,
    "source_relevance": "high",
    "has_fabrication_risk": false
}"""


SYSTEM_PROMPT_NONE = """당신은 보고서 작성을 돕는 AI 어시스턴트입니다.

## 언어 규칙 (절대 준수)
- "answer" 필드는 반드시 한국어로만 작성하세요.
- 중국어(中文), 일본어 등 다른 언어로 절대 전환하지 마세요. 문장 중간에도 예외 없습니다.
- 영어 기술 용어(AWS, API, Bedrock, LangGraph 등)는 원문 그대로 사용 가능합니다.

이 섹션은 서론, 결론, 인사말 등 검색 결과 없이 작성하는 일반적인 섹션입니다.
문서의 맥락에 맞는 자연스럽고 전문적인 내용을 작성하세요.

중요한 규칙:
1. 구체적인 수치, 날짜, 고유명사 등 검증이 필요한 정보는 포함하지 마세요.
2. 일반적이고 보편적인 내용으로 작성하세요.
3. 문서의 도입부나 마무리에 적합한 톤으로 작성하세요.

응답 형식:
반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

{
    "answer": "작성한 내용",
    "source_type": "none",
    "source_count": 0,
    "source_relevance": "low",
    "has_fabrication_risk": false
}

has_fabrication_risk는 구체적인 사실을 지어낸 경우에만 true입니다.
일반적인 서술은 false로 설정하세요."""


def _call_ollama(messages: list[dict]) -> str:
    """
    Ollama API를 호출하여 응답을 받습니다.

    Args:
        messages: 대화 메시지 리스트 (role, content 포함)

    Returns:
        LLM 응답 텍스트

    Raises:
        requests.RequestException: API 호출 실패 시
    """
    url = f"{OLLAMA_BASE_URL}/api/chat"
    payload = {
        "model": MODEL_NAME,
        "messages": messages,
        "stream": False,
        "format": "json",
    }

    response = requests.post(url, json=payload, timeout=120)
    response.raise_for_status()

    result = response.json()
    return result.get("message", {}).get("content", "")


def _format_sources(sources: list[dict]) -> str:
    """
    검색 결과를 LLM에 전달할 형식으로 변환합니다.

    Args:
        sources: 검색 결과 리스트 (rag_tool/web_search의 results)
                 필드: source_title, content, source_url, score

    Returns:
        포맷팅된 문자열
    """
    if not sources:
        return "검색 결과 없음"

    formatted_parts = []
    for i, source in enumerate(sources, 1):
        # rag_tool/web_search 공통 스키마 필드명 사용
        title = source.get("source_title", f"문서 {i}")
        content = source.get("content", "")
        url = source.get("source_url", "")
        score = source.get("score", 0.0)

        part = f"[출처 {i}] {title} (관련도: {score:.2f})\n{content}"
        if url:
            part += f"\n출처: {url}"
        formatted_parts.append(part)

    return "\n\n".join(formatted_parts)


def _generate_none_section(
    section_query: str,
    llm_client: Callable[[list[dict]], str] | None = None,
) -> dict:
    """
    source_type="none"인 섹션(서론, 결론 등)을 생성합니다.

    검색 결과 없이 문서 맥락에 맞는 일반적인 내용을 작성합니다.

    Args:
        section_query: 섹션 질의
        llm_client: 테스트용 mock 함수 (None이면 실제 Ollama API 호출)

    Returns:
        생성된 결과 딕셔너리
    """
    user_message = f"""섹션 요청: {section_query}

위 요청에 맞는 내용을 작성해주세요.
검색 결과가 필요 없는 일반적인 섹션(서론, 결론 등)입니다."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT_NONE},
        {"role": "user", "content": user_message},
    ]

    # LLM 호출 (mock 또는 실제 API), 언어 이탈 시 자동 재시도
    client = llm_client if llm_client is not None else _call_ollama
    return _generate_with_lang_retry(messages, "none", 0, client)


def _parse_llm_response(
    raw_output: str, source_type: str, source_count: int
) -> dict:
    """
    LLM 응답을 파싱하여 딕셔너리로 변환합니다.

    Args:
        raw_output: LLM의 원시 응답
        source_type: 출처 유형
        source_count: 출처 개수

    Returns:
        파싱된 응답 딕셔너리
    """
    try:
        result = json.loads(raw_output)

        # 필수 필드 검증 및 기본값 설정
        return {
            "answer": result.get("answer", ""),
            "source_type": result.get("source_type", source_type),
            "source_count": result.get("source_count", source_count),
            "source_relevance": result.get("source_relevance", "low"),
            "has_fabrication_risk": result.get("has_fabrication_risk", False),
        }
    except (json.JSONDecodeError, TypeError):
        # JSON 파싱 실패 시 폴백
        return {
            "answer": raw_output,
            "source_type": source_type,
            "source_count": source_count,
            "source_relevance": "low",
            "has_fabrication_risk": True,
        }


def _generate_with_lang_retry(
    messages: list[dict],
    source_type: str,
    source_count: int,
    client: Callable[[list[dict]], str],
    max_retries: int = MAX_LANG_RETRY,
) -> dict:
    """
    언어 하네스(시스템 프롬프트)를 우회해 중국어 등으로 이탈한 응답이
    감지되면 최대 max_retries회까지 재생성을 시도합니다.

    마지막 시도까지 이탈이 지속되면 has_fabrication_risk=True로 표시해
    검토 큐로 넘깁니다 (is_language_valid가 최종 안전망 역할).

    Args:
        messages: LLM에 전달할 대화 메시지 (system/user)
        source_type: 출처 유형 (파싱 결과 기본값으로 사용)
        source_count: 출처 개수 (파싱 결과 기본값으로 사용)
        client: LLM 호출 함수 (mock 또는 _call_ollama)
        max_retries: 최대 재시도 횟수

    Returns:
        파싱된 응답 딕셔너리 (마지막 시도 결과)
    """
    result: dict = {}
    for _ in range(max_retries):
        raw_output = client(messages)
        result = _parse_llm_response(raw_output, source_type, source_count)
        if is_language_valid(result["answer"]):
            return result

    # 재시도를 모두 소진했는데도 언어 이탈이면 검토 필요로 표시
    result["has_fabrication_risk"] = True
    return result


def generate_section_draft(
    section_query: str,
    sources: list[dict],
    source_type: str,
    llm_client: Callable[[list[dict]], str] | None = None,
) -> dict:
    """
    섹션 초안을 생성합니다.

    Args:
        section_query: 섹션 질의 (예: "2024년 매출 현황을 작성해주세요")
        sources: 검색 결과 리스트 (rag_tool 또는 web_search의 results)
        source_type: 출처 유형 ("internal" 또는 "web")
        llm_client: 테스트용 mock 함수 (None이면 실제 Ollama API 호출)

    Returns:
        dict: {
            "answer": str,           # 생성된 답변
            "source_type": str,      # "internal" 또는 "web"
            "source_count": int,     # 참조한 출처 개수
            "source_relevance": str, # "high", "medium", "low"
            "has_fabrication_risk": bool  # 허위 생성 위험 여부
        }

    Note:
        source_type이 "none"이고 sources가 빈 리스트인 경우,
        별도의 프롬프트로 LLM을 호출하여 서론/결론 등을 생성합니다.
    """
    # source_type이 "none"이고 sources가 비어있으면 별도 프롬프트로 LLM 호출
    if source_type == "none" and not sources:
        return _generate_none_section(section_query, llm_client)

    # 빈 sources면 LLM 호출 생략 (internal/web인데 검색 결과가 없는 경우)
    if not sources:
        return {
            "answer": "",
            "source_type": source_type,
            "source_count": 0,
            "source_relevance": "low",
            "has_fabrication_risk": False,
        }

    # 메시지 구성
    formatted_sources = _format_sources(sources)
    user_message = f"""질문: {section_query}

검색 결과:
{formatted_sources}

위 검색 결과만을 근거로 질문에 답변해주세요.

[중요] source_type 필드는 반드시 아래 값을 그대로 사용하세요 (모델이 임의로 바꾸지 말 것): {source_type}"""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # LLM 호출 (mock 또는 실제 API), 언어 이탈 시 자동 재시도
    client = llm_client if llm_client is not None else _call_ollama
    return _generate_with_lang_retry(messages, source_type, len(sources), client)

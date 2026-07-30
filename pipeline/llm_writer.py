"""
llm_writer.py - LLM 기반 텍스트 생성 모듈

Ollama를 통해 qwen2.5:7b-instruct-q4_0 모델을 호출하여
구조화된 JSON 형식의 응답을 생성합니다.

주요 기능:
- Ollama API 호출 및 응답 파싱
- 프롬프트 구성 및 전송
- JSON 스키마 기반 구조화 출력

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
import requests
from typing import Callable

from pipeline.lang_guard import is_language_valid


OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:7b-instruct-q4_0"

SYSTEM_PROMPT = """당신은 보고서 작성을 돕는 AI 어시스턴트입니다.

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
- true: 출처에서 확인할 수 없는 내용이 포함됨"""


SYSTEM_PROMPT_NONE = """당신은 보고서 작성을 돕는 AI 어시스턴트입니다.

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

    # LLM 호출 (mock 또는 실제 API)
    client = llm_client if llm_client is not None else _call_ollama
    raw_output = client(messages)

    # 응답 파싱
    result = _parse_llm_response(raw_output, "none", 0)

    # 언어 검증 (한글 비율 체크)
    if not is_language_valid(result["answer"]):
        result["has_fabrication_risk"] = True

    return result


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

    # LLM 호출 (mock 또는 실제 API)
    client = llm_client if llm_client is not None else _call_ollama
    raw_output = client(messages)

    # 응답 파싱
    result = _parse_llm_response(raw_output, source_type, len(sources))

    # 언어 검증 (한글 비율 체크)
    if not is_language_valid(result["answer"]):
        result["has_fabrication_risk"] = True

    return result

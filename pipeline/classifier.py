"""
classifier.py - 섹션 분류 모듈

섹션 제목과 쿼리를 분석하여 필요한 데이터 소스 유형을 분류합니다.
LLM을 활용하여 섹션의 특성을 파악하고, 적절한 검색 전략을 결정합니다.

분류 결과:
- "none": 서론/결론처럼 검색 없이 일반적으로 작성 가능한 섹션
- "internal": 회사 내부 정보(기술 역량, 프로젝트 경험 등)가 필요한 섹션
- "web": 외부 시장 동향, 경쟁사 정보 등 외부 정보가 필요한 섹션
- "provided_data": 사용자가 직접 제공한 데이터(Excel/CSV 등)를 사용하는 섹션
  (이 타입은 LLM 분류가 아닌, provided_chunks 존재 여부로 결정됨)
"""

import json
import os
from typing import Callable, Literal

from dotenv import load_dotenv
from groq import Groq

load_dotenv()

MODEL_NAME = "openai/gpt-oss-20b"

# source_type 타입 별칭
SourceType = Literal["none", "internal", "web", "provided_data"]
_groq_client: Groq | None = None


def _get_groq_client() -> Groq:
    """Groq 클라이언트 싱글톤"""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client

CLASSIFICATION_PROMPT = """당신은 보고서 섹션 분류 전문가입니다.

## 절대 금지 사항
- 도구(tool)를 호출하지 마세요. browser.open, search 등 어떤 도구도 사용하지 마세요.
- 반드시 JSON 형식으로만 응답하세요.

주어진 섹션 제목과 쿼리를 분석하여, 이 섹션을 작성하기 위해 어떤 종류의 정보가 필요한지 분류하세요.

분류 기준:
1. "none": 서론, 결론, 인사말, 맺음말 등 검색 없이 일반적인 문구로 작성 가능한 섹션
   - 예: "서론", "보고서 개요", "결론", "맺음말", "감사의 글"

2. "internal": 회사 내부 정보가 필요한 섹션
   - 회사의 기술 역량, 프로젝트 경험, 내부 전략, 조직 구조, 인력 현황 등
   - 예: "회사 기술 역량", "프로젝트 수행 경험", "차별화 전략", "핵심 인력 소개"

3. "web": 회사 외부 정보가 필요한 섹션
   - 시장 동향, 경쟁사 분석, 업계 트렌드, 기술 동향, 규제 현황 등
   - 예: "시장 동향", "경쟁사 분석", "업계 전망", "기술 트렌드"

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

{"source_type": "none" 또는 "internal" 또는 "web"}"""


def _call_groq_for_classification(messages: list[dict]) -> str:
    """
    Groq API를 호출하여 분류 결과를 받습니다.

    Args:
        messages: 대화 메시지 리스트

    Returns:
        LLM 응답 텍스트
    """
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=MODEL_NAME,
        messages=messages,
        temperature=0.3,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


def _parse_classification_response(
    raw_output: str,
) -> SourceType:
    """
    LLM 응답을 파싱하여 source_type을 추출합니다.

    Args:
        raw_output: LLM의 원시 응답

    Returns:
        source_type ("none", "internal", "web", "provided_data")
        파싱 실패 시 기본값 "internal" 반환 (안전한 폴백)
    """
    try:
        result = json.loads(raw_output)
        source_type = result.get("source_type", "internal")

        # 유효한 값인지 검증 (provided_data 포함)
        if source_type in ("none", "internal", "web", "provided_data"):
            return source_type
        return "internal"  # 유효하지 않은 값이면 internal로 폴백

    except (json.JSONDecodeError, TypeError):
        return "internal"  # 파싱 실패 시 internal로 폴백


def classify_source_type(
    section_title: str,
    section_query: str,
    llm_client: Callable[[list[dict]], str] | None = None,
) -> SourceType:
    """
    섹션의 source_type을 분류합니다.

    Args:
        section_title: 섹션 제목 (예: "회사 기술 역량")
        section_query: 섹션 쿼리 (예: "회사의 주요 기술 역량을 설명해주세요")
        llm_client: 테스트용 mock 함수 (None이면 실제 Groq API 호출)

    Returns:
        "none": 검색 불필요
        "internal": 사내 RAG 검색 필요
        "web": 웹 검색 필요
    """
    user_message = f"""섹션 제목: {section_title}
섹션 쿼리: {section_query}

위 섹션을 작성하기 위해 어떤 종류의 정보가 필요한지 분류해주세요."""

    messages = [
        {"role": "system", "content": CLASSIFICATION_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # LLM 호출 (mock 또는 실제 API)
    client = llm_client if llm_client is not None else _call_groq_for_classification
    raw_output = client(messages)

    return _parse_classification_response(raw_output)



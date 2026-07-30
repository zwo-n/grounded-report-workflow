"""
section_planner.py - 섹션 구성 동적 생성 모듈

사용자 요청을 분석하여 보고서/제안서의 섹션 구성을 동적으로 생성합니다.
단일 LLM 호출로 섹션 제목, 쿼리, 순서를 함께 결정합니다.

사용 예:
    sections = plan_sections("클라우드 비용 최적화 제안서 작성해줘")
    # [{"title": "서론", "query": "...", "order": 1}, ...]
"""

import json
import requests
from typing import Callable

OLLAMA_BASE_URL = "http://localhost:11434"
MODEL_NAME = "qwen2.5:7b-instruct-q4_0"

PLANNER_SYSTEM_PROMPT = """당신은 보고서/제안서 구성 전문가입니다.

사용자의 요청을 분석하여 적절한 섹션 구성을 생성하세요.

섹션 구성 원칙:
1. 서론으로 시작하고 결론으로 마무리
2. 논리적 흐름에 따라 섹션 배치 (배경 → 현황 분석 → 제안/전략 → 기대효과)
3. 각 섹션은 명확한 목적을 가져야 함
4. 보통 4~7개 섹션이 적절함

각 섹션에 대해:
- title: 섹션 제목 (간결하게)
- query: 해당 섹션을 작성하기 위한 구체적인 질의문
- order: 섹션 순서 (1부터 시작)

반드시 아래 JSON 형식으로만 응답하세요. 다른 텍스트는 포함하지 마세요.

{
    "sections": [
        {"title": "서론", "query": "보고서 서론을 작성해주세요", "order": 1},
        {"title": "현황 분석", "query": "현재 상황을 분석해주세요", "order": 2},
        ...
    ]
}"""


def _call_ollama_for_planning(messages: list[dict]) -> str:
    """
    Ollama API를 호출하여 섹션 계획을 받습니다.

    Args:
        messages: 대화 메시지 리스트

    Returns:
        LLM 응답 텍스트
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


def _parse_sections_response(raw_output: str) -> list[dict]:
    """
    LLM 응답을 파싱하여 섹션 리스트를 추출합니다.

    Args:
        raw_output: LLM의 원시 응답

    Returns:
        섹션 리스트 [{"title": str, "query": str, "order": int}, ...]
        파싱 실패 시 기본 섹션 구성 반환
    """
    default_sections = [
        {"title": "서론", "query": "보고서 서론을 작성해주세요", "order": 1},
        {"title": "본론", "query": "주요 내용을 작성해주세요", "order": 2},
        {"title": "결론", "query": "보고서 결론을 작성해주세요", "order": 3},
    ]

    if not raw_output or not raw_output.strip():
        return default_sections

    try:
        result = json.loads(raw_output)

        # "sections" 키가 있으면 해당 값 사용
        sections = result.get("sections", result)

        # 리스트가 아니면 폴백
        if not isinstance(sections, list):
            return default_sections

        # 빈 리스트면 폴백
        if len(sections) == 0:
            return default_sections

        # 각 섹션 검증 및 정규화
        validated_sections = []
        for i, section in enumerate(sections):
            if not isinstance(section, dict):
                continue

            title = section.get("title", "")
            query = section.get("query", "")
            order = section.get("order", i + 1)

            # 필수 필드 확인
            if not title or not query:
                continue

            validated_sections.append({
                "title": str(title),
                "query": str(query),
                "order": int(order) if isinstance(order, (int, float)) else i + 1,
            })

        # 유효한 섹션이 없으면 폴백
        if len(validated_sections) == 0:
            return default_sections

        # order 기준으로 정렬
        validated_sections.sort(key=lambda x: x["order"])

        return validated_sections

    except (json.JSONDecodeError, TypeError, ValueError):
        return default_sections


def plan_sections(
    user_request: str,
    llm_client: Callable[[list[dict]], str] | None = None,
) -> list[dict]:
    """
    사용자 요청을 분석하여 섹션 구성을 생성합니다.

    Args:
        user_request: 사용자 요청 (예: "클라우드 비용 최적화 제안서 작성해줘")
        llm_client: 테스트용 mock 함수 (None이면 실제 Ollama API 호출)

    Returns:
        섹션 리스트: [{"title": str, "query": str, "order": int}, ...]
        order 기준 정렬되어 반환됨
    """
    user_message = f"""사용자 요청: {user_request}

위 요청에 맞는 보고서/제안서의 섹션 구성을 생성해주세요.
각 섹션의 제목, 작성 질의문, 순서를 JSON 형식으로 응답하세요."""

    messages = [
        {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    # LLM 호출 (mock 또는 실제 API)
    client = llm_client if llm_client is not None else _call_ollama_for_planning
    raw_output = client(messages)

    return _parse_sections_response(raw_output)

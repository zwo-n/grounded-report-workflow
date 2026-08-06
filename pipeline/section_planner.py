"""
section_planner.py - 섹션 구성 동적 생성 모듈

사용자 요청을 분석하여 보고서/제안서의 섹션 구성을 동적으로 생성합니다.
단일 LLM 호출로 문서 유형 판단과 섹션 구성을 함께 결정합니다.

사용 예:
    # 자동 감지 + 섹션 생성 (단일 LLM 호출)
    sections, detected_hint = plan_sections("클라우드 비용 최적화 제안서 작성해줘")

    # 템플릿 힌트 명시적 제공 (few-shot 예시로 활용)
    sections, _ = plan_sections("AWS 비용 절감 방안", template_hint="제안서")
"""

import json
import os
from typing import Callable

from dotenv import load_dotenv
from groq import Groq

from pipeline.templates import (
    get_template,
    format_template_as_example,
    format_templates_for_detection,
    TEMPLATES,
    is_fixed_template,
    get_fixed_sections,
)

load_dotenv()

MODEL_NAME = "openai/gpt-oss-20b"
_groq_client: Groq | None = None


def _get_groq_client() -> Groq:
    """Groq 클라이언트 싱글톤"""
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client

# 사용 가능한 템플릿 목록 (동적으로 생성)
AVAILABLE_TEMPLATES = list(TEMPLATES.keys())

# 템플릿 자동 감지 + 섹션 생성 통합 프롬프트
PLANNER_SYSTEM_PROMPT_WITH_DETECTION = """당신은 보고서/제안서 구성 전문가입니다.

## 1단계: 문서 제목 생성
사용자 요청을 분석하여 문서의 공식 제목을 생성하세요.
- 사용자가 입력한 명령어 원문이 아닌, 문서 주제를 나타내는 제목이어야 함
- "~해줘", "작성해줘" 같은 명령어 어미 제거
- 간결하고 명확하게 (15~30자 내외)
- 예: "AWS 클라우드 비용 최적화 방안" (O), "AWS 클라우드 비용 최적화 방안에 대한 기술 보고서를 작성해줘" (X)

## 2단계: 문서 유형 판단
사용자 요청에 가장 적합한 문서 유형을 아래 목록에서 선택하세요.
해당하는 유형이 없으면 null로 설정하세요.

사용 가능한 문서 유형:
{template_descriptions}

## 3단계: 섹션 구성 생성
판단한 문서 유형을 참고하여 적절한 섹션 구성을 생성하세요.

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

{{
    "document_title": "문서 제목",
    "template_hint": "문서유형" 또는 null,
    "sections": [
        {{"title": "서론", "query": "보고서 서론을 작성해주세요", "order": 1}},
        {{"title": "현황 분석", "query": "현재 상황을 분석해주세요", "order": 2}},
        ...
    ]
}}"""

# 템플릿 명시적 제공 시 사용하는 프롬프트
PLANNER_SYSTEM_PROMPT_WITH_TEMPLATE = """당신은 보고서/제안서 구성 전문가입니다.

## 1단계: 문서 제목 생성
사용자 요청을 분석하여 문서의 공식 제목을 생성하세요.
- 사용자가 입력한 명령어 원문이 아닌, 문서 주제를 나타내는 제목이어야 함
- "~해줘", "작성해줘" 같은 명령어 어미 제거
- 간결하고 명확하게 (15~30자 내외)

## 2단계: 섹션 구성 생성
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

{{
    "document_title": "문서 제목",
    "sections": [
        {{"title": "서론", "query": "보고서 서론을 작성해주세요", "order": 1}},
        {{"title": "현황 분석", "query": "현재 상황을 분석해주세요", "order": 2}},
        ...
    ]
}}"""


def _call_groq_for_planning(messages: list[dict]) -> str:
    """
    Groq API를 호출하여 섹션 계획을 받습니다.

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
        max_tokens=2048,
        response_format={"type": "json_object"},
    )
    return response.choices[0].message.content or ""


def _parse_plan_response(raw_output: str) -> tuple[list[dict], str | None, str | None]:
    """
    LLM 응답을 파싱하여 섹션 리스트, 문서 제목, 템플릿 힌트를 추출합니다.

    Args:
        raw_output: LLM의 원시 응답

    Returns:
        (섹션 리스트, 문서 제목 또는 None, 감지된 template_hint 또는 None)
        파싱 실패 시 기본 섹션 구성 반환
    """
    default_sections = [
        {"title": "서론", "query": "보고서 서론을 작성해주세요", "order": 1},
        {"title": "본론", "query": "주요 내용을 작성해주세요", "order": 2},
        {"title": "결론", "query": "보고서 결론을 작성해주세요", "order": 3},
    ]

    if not raw_output or not raw_output.strip():
        return default_sections, None, None

    try:
        result = json.loads(raw_output)

        # document_title 추출
        document_title = result.get("document_title")
        if document_title and isinstance(document_title, str):
            document_title = document_title.strip()
            # 빈 문자열이면 None으로
            if not document_title:
                document_title = None
        else:
            document_title = None

        # template_hint 추출
        detected_hint = result.get("template_hint")
        if detected_hint is not None and detected_hint not in AVAILABLE_TEMPLATES:
            detected_hint = None

        # sections 추출
        sections = result.get("sections", result)

        # 리스트가 아니면 폴백
        if not isinstance(sections, list):
            return default_sections, document_title, detected_hint

        # 빈 리스트면 폴백
        if len(sections) == 0:
            return default_sections, document_title, detected_hint

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
            return default_sections, document_title, detected_hint

        # order 기준으로 정렬
        validated_sections.sort(key=lambda x: x["order"])

        return validated_sections, document_title, detected_hint

    except (json.JSONDecodeError, TypeError, ValueError):
        return default_sections, None, None


def _extract_title_from_request(user_request: str) -> str:
    """
    사용자 요청에서 문서 제목을 추출합니다.
    고정 템플릿 모드에서 LLM 호출 없이 사용.

    Args:
        user_request: 사용자 요청

    Returns:
        추출된 문서 제목
    """
    title = user_request

    # 명령어 어미 제거
    suffixes = [
        "를 작성해줘",
        "을 작성해줘",
        "를 작성해주세요",
        "을 작성해주세요",
        "작성해줘",
        "작성해주세요",
        "해줘",
        "해주세요",
        "부탁해",
        "부탁해요",
    ]
    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break

    # 너무 길면 자르기
    if len(title) > 50:
        title = title[:50] + "..."

    return title if title else "활동 보고서"


def plan_sections(
    user_request: str,
    template_hint: str | None = None,
    llm_client: Callable[[list[dict]], str] | None = None,
    force_fixed: bool = False,
) -> tuple[list[dict], str | None, str | None]:
    """
    사용자 요청을 분석하여 섹션 구성을 생성합니다.

    단일 LLM 호출로 문서 제목, 유형 판단, 섹션 구성을 함께 수행합니다.
    template_hint가 명시적으로 제공되면 유형 판단 단계를 건너뛰고 해당 템플릿을
    few-shot 예시로 사용합니다.

    Args:
        user_request: 사용자 요청 (예: "클라우드 비용 최적화 제안서 작성해줘")
        template_hint: 문서 유형 힌트 (예: "제안서", "기술 보고서")
                       None이면 LLM이 자동 감지
        llm_client: 테스트용 mock 함수 (None이면 실제 Groq API 호출)
        force_fixed: True면 고정 템플릿 섹션을 LLM 호출 없이 반환
                     (provided_data 모드에서 사용)

    Returns:
        (섹션 리스트, 문서 제목, 감지된 template_hint)
        - 섹션 리스트: [{"title": str, "query": str, "order": int}, ...]
        - 문서 제목: LLM이 생성한 공식 문서 제목 또는 None
        - template_hint: 명시적 제공 시 해당 값, 자동 감지 시 감지된 값 또는 None
    """
    # Case 0: 고정 템플릿 분기 (LLM 호출 스킵)
    if template_hint and (force_fixed or is_fixed_template(template_hint)):
        fixed_sections = get_fixed_sections(template_hint)
        if fixed_sections:
            # 문서 제목은 사용자 요청에서 추출 (간단한 규칙)
            document_title = _extract_title_from_request(user_request)
            print(f"[section_planner] 고정 템플릿 사용: {template_hint}")
            return fixed_sections, document_title, template_hint

    # Case 1: template_hint가 명시적으로 제공된 경우
    if template_hint is not None:
        template = get_template(template_hint)
        if template:
            example_text = format_template_as_example(template)
            user_message = f"""사용자 요청: {user_request}

아래는 "{template_hint}" 유형 문서의 일반적인 섹션 구성 예시입니다.
이를 참고하되, 사용자 요청 내용에 맞게 섹션을 조정하세요.

--- 참고 예시 ---
{example_text}
--- 참고 예시 끝 ---

위 요청에 맞는 문서 제목과 섹션 구성을 생성해주세요.
문서 제목, 각 섹션의 제목, 작성 질의문, 순서를 JSON 형식으로 응답하세요."""
            applied_hint = template_hint
        else:
            # 알 수 없는 템플릿이면 기본 메시지 (few-shot 미적용)
            user_message = f"""사용자 요청: {user_request}

위 요청에 맞는 보고서/제안서의 문서 제목과 섹션 구성을 생성해주세요.
문서 제목, 각 섹션의 제목, 작성 질의문, 순서를 JSON 형식으로 응답하세요."""
            applied_hint = None  # 템플릿이 실제로 적용되지 않았으므로 None

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT_WITH_TEMPLATE},
            {"role": "user", "content": user_message},
        ]

        client = llm_client if llm_client is not None else _call_groq_for_planning
        raw_output = client(messages)

        sections, document_title, _ = _parse_plan_response(raw_output)
        return sections, document_title, applied_hint

    # Case 2: template_hint가 None인 경우 - 자동 감지 + 섹션 생성 통합
    template_descriptions = format_templates_for_detection()
    system_prompt = PLANNER_SYSTEM_PROMPT_WITH_DETECTION.format(
        template_descriptions=template_descriptions
    )

    user_message = f"""사용자 요청: {user_request}

위 요청에 맞는 문서 제목, 문서 유형을 판단하고, 적절한 섹션 구성을 생성해주세요."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ]

    client = llm_client if llm_client is not None else _call_groq_for_planning
    raw_output = client(messages)

    sections, document_title, detected_hint = _parse_plan_response(raw_output)
    return sections, document_title, detected_hint

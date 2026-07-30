"""
templates.py - 문서 유형별 섹션 구성 템플릿

template_hint에 따른 few-shot 예시를 제공합니다.
LLM이 참고하여 사용자 요청에 맞게 조정합니다.

확장 방법:
    TEMPLATES 딕셔너리에 새로운 유형 추가
    키: 템플릿 힌트 문자열 (예: "제안서", "기술 보고서")
    값: 딕셔너리 {"description": str, "sections": list[dict]}
"""

TEMPLATES: dict[str, dict] = {
    "제안서": {
        "description": "고객/경영진에게 특정 방안을 제안하는 문서",
        "sections": [
            {"title": "서론", "query": "제안 배경과 목적을 설명해주세요", "order": 1},
            {"title": "현황 분석", "query": "현재 상황과 문제점을 분석해주세요", "order": 2},
            {"title": "제안 내용", "query": "구체적인 제안 방안을 설명해주세요", "order": 3},
            {"title": "기대 효과", "query": "제안 실행 시 기대되는 효과를 설명해주세요", "order": 4},
            {"title": "실행 계획", "query": "제안 실행을 위한 단계별 계획을 제시해주세요", "order": 5},
            {"title": "결론", "query": "제안서의 핵심 내용을 요약하고 마무리해주세요", "order": 6},
        ],
    },
    "기술 보고서": {
        "description": "기술적 내용을 체계적으로 정리한 문서",
        "sections": [
            {"title": "서론", "query": "보고서의 배경과 목적을 설명해주세요", "order": 1},
            {"title": "기술 개요", "query": "다루는 기술의 개요를 설명해주세요", "order": 2},
            {"title": "상세 분석", "query": "기술의 상세 내용과 특징을 분석해주세요", "order": 3},
            {"title": "적용 사례", "query": "기술의 실제 적용 사례를 소개해주세요", "order": 4},
            {"title": "결론", "query": "분석 결과를 요약하고 시사점을 제시해주세요", "order": 5},
        ],
    },
}


def get_template(hint: str) -> dict | None:
    """
    템플릿 힌트에 해당하는 템플릿을 반환합니다.

    Args:
        hint: 템플릿 힌트 (예: "제안서", "기술 보고서")

    Returns:
        템플릿 딕셔너리 또는 None (해당 템플릿 없음)
    """
    return TEMPLATES.get(hint)


def format_template_as_example(template: dict) -> str:
    """
    템플릿을 LLM 프롬프트용 few-shot 예시 문자열로 변환합니다.

    Args:
        template: 템플릿 딕셔너리

    Returns:
        포맷팅된 예시 문자열
    """
    description = template.get("description", "")
    sections = template.get("sections", [])

    lines = [f"문서 유형: {description}", "섹션 구성 예시:"]
    for section in sections:
        lines.append(f"  {section['order']}. {section['title']} - {section['query']}")

    return "\n".join(lines)

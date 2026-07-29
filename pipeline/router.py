"""
router.py - 승인 결정 모듈

LLM이 생성한 메타데이터를 기반으로 최종 승인 상태를 결정합니다.
순수 함수로 구현되며, LLM 관여 없이 규칙 기반으로 동작합니다.

입력: LLM이 판단한 결과
- source_type: 출처 유형 (아래 3가지 값만 허용)
  - "internal": 사내 RAG 검색 결과를 근거로 사용
  - "web": 웹 검색 결과를 근거로 사용 (내부 근거 부족 시 폴백)
  - "none": 근거가 필요 없는 서술형 섹션
- source_count: 참조한 출처 개수
- source_relevance: 출처의 관련성 점수
- has_fabrication_risk: 허위 생성 위험 여부

출력: 승인 상태
- auto_approved: 자동 승인 (신뢰할 수 있는 출처, 충분한 근거)
- review_required: 검토 필요 (출처 부족, 허위 생성 위험 등)

Note: tool 선택(어떤 데이터 소스를 사용할지)은 llm_writer.py에서
LLM이 직접 판단합니다. 이 모듈은 그 결과를 받아 승인 여부만 결정합니다.
"""

from enum import Enum


class Route(Enum):
    """승인 라우팅 결과"""

    AUTO_APPROVE = "auto_approved"
    NEEDS_REVIEW = "review_required"

    @property
    def label(self) -> str:
        """
        화면 출력 및 문서 삽입용 한글 레이블.

        사용법:
            decision = route(...)
            if decision == Route.AUTO_APPROVE:  # enum 멤버로 비교
                print(decision.label)           # "자동 승인" 출력
        """
        return _ROUTE_LABELS[self]


# 한글 레이블 매핑 (문서/화면 출력용)
# decision.value("auto_approved")를 직접 노출하지 말고 decision.label 사용
_ROUTE_LABELS: dict[Route, str] = {
    Route.AUTO_APPROVE: "자동 승인",
    Route.NEEDS_REVIEW: "검토 필요",
}


def route(
    source_type: str,
    source_count: int,
    source_relevance: str,
    has_fabrication_risk: bool,
) -> Route:
    """
    LLM 메타데이터를 기반으로 승인 라우팅을 결정합니다.

    Args:
        source_type: 출처 유형 ("internal", "web", "none")
        source_count: 참조한 출처 개수
        source_relevance: 출처 관련성 ("high", "medium", "low")
        has_fabrication_risk: 허위 생성 위험 여부

    Returns:
        Route.AUTO_APPROVE: 자동 승인
        Route.NEEDS_REVIEW: 검토 필요
    """
    # 1. source_type == "none" → 항상 AUTO_APPROVE
    # 근거가 원래 필요 없는 서술형 섹션 (인사말, 맺음말 등)
    # source_relevance 값이 뭐든 무관하게 방어적으로 처리
    if source_type == "none":
        return Route.AUTO_APPROVE

    # 2. 내부 RAG 검색 결과 기반 + 높은 관련성 + 허위 생성 위험 없음
    # 사내 문서는 신뢰도가 가장 높으므로 high 관련성만 자동 승인
    # medium/low는 근거가 불충분할 수 있어 검토 필요
    if (
        source_type == "internal"
        and source_relevance == "high"
        and not has_fabrication_risk
    ):
        return Route.AUTO_APPROVE

    # 3. 웹 검색 폴백 결과 + 중간 이상 관련성 + 허위 생성 위험 없음
    # 내부 RAG에서 근거를 찾지 못해 웹으로 폴백한 경우
    # 웹 검색은 내부 문서보다 신뢰도가 낮으므로 medium까지 허용
    # (내부 근거 부족 시 웹이라도 있으면 활용하는 전략)
    if (
        source_type == "web"
        and source_relevance in ("high", "medium")
        and not has_fabrication_risk
    ):
        return Route.AUTO_APPROVE

    # 4. 그 외 모든 경우 → NEEDS_REVIEW
    # - source_relevance가 "low"인 경우 (근거 불충분)
    # - has_fabrication_risk가 True인 경우 (허위 생성 위험)
    # - 알 수 없는 source_type인 경우 (방어적 처리)
    return Route.NEEDS_REVIEW

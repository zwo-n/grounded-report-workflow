"""
router.py 유닛 테스트

테스트 케이스:
- 분기 1: source_type == "none" → AUTO_APPROVE
- 분기 2: internal + high + no risk → AUTO_APPROVE
- 분기 3: web + high/medium + no risk → AUTO_APPROVE
- 분기 4: 그 외 → NEEDS_REVIEW
- has_fabrication_risk=True로 분기 2/3 탈락 케이스
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.router import Route, route


class TestRouteNone:
    """분기 1: source_type == 'none' → AUTO_APPROVE"""

    def test_none_with_high_relevance(self):
        """none 타입 + high 관련성 → AUTO_APPROVE"""
        result = route(
            source_type="none",
            source_count=0,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert result == Route.AUTO_APPROVE

    def test_none_with_low_relevance(self):
        """none 타입 + low 관련성 → AUTO_APPROVE (관련성 무관)"""
        result = route(
            source_type="none",
            source_count=0,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        assert result == Route.AUTO_APPROVE

    def test_none_with_fabrication_risk(self):
        """none 타입 + 허위 생성 위험 → AUTO_APPROVE (위험도 무관)"""
        # none 타입은 근거가 필요 없는 섹션이므로 fabrication_risk도 무시
        result = route(
            source_type="none",
            source_count=0,
            source_relevance="low",
            has_fabrication_risk=True,
        )
        assert result == Route.AUTO_APPROVE


class TestRouteInternal:
    """분기 2: internal + high + no risk → AUTO_APPROVE"""

    def test_internal_high_no_risk(self):
        """internal + high + no risk → AUTO_APPROVE"""
        result = route(
            source_type="internal",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert result == Route.AUTO_APPROVE

    def test_internal_medium_no_risk(self):
        """internal + medium → NEEDS_REVIEW (high만 자동 승인)"""
        result = route(
            source_type="internal",
            source_count=2,
            source_relevance="medium",
            has_fabrication_risk=False,
        )
        assert result == Route.NEEDS_REVIEW

    def test_internal_low_no_risk(self):
        """internal + low → NEEDS_REVIEW"""
        result = route(
            source_type="internal",
            source_count=1,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        assert result == Route.NEEDS_REVIEW

    def test_internal_high_with_fabrication_risk(self):
        """internal + high + fabrication_risk → NEEDS_REVIEW (위험으로 탈락)"""
        result = route(
            source_type="internal",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=True,
        )
        assert result == Route.NEEDS_REVIEW


class TestRouteWeb:
    """분기 3: web + high/medium + no risk → AUTO_APPROVE"""

    def test_web_high_no_risk(self):
        """web + high + no risk → AUTO_APPROVE"""
        result = route(
            source_type="web",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert result == Route.AUTO_APPROVE

    def test_web_medium_no_risk(self):
        """web + medium + no risk → AUTO_APPROVE (medium도 허용)"""
        result = route(
            source_type="web",
            source_count=2,
            source_relevance="medium",
            has_fabrication_risk=False,
        )
        assert result == Route.AUTO_APPROVE

    def test_web_low_no_risk(self):
        """web + low → NEEDS_REVIEW"""
        result = route(
            source_type="web",
            source_count=1,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        assert result == Route.NEEDS_REVIEW

    def test_web_high_with_fabrication_risk(self):
        """web + high + fabrication_risk → NEEDS_REVIEW (위험으로 탈락)"""
        result = route(
            source_type="web",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=True,
        )
        assert result == Route.NEEDS_REVIEW

    def test_web_medium_with_fabrication_risk(self):
        """web + medium + fabrication_risk → NEEDS_REVIEW (위험으로 탈락)"""
        result = route(
            source_type="web",
            source_count=2,
            source_relevance="medium",
            has_fabrication_risk=True,
        )
        assert result == Route.NEEDS_REVIEW


class TestRouteNeedsReview:
    """분기 4: 그 외 모든 경우 → NEEDS_REVIEW"""

    def test_unknown_source_type(self):
        """알 수 없는 source_type → NEEDS_REVIEW (방어적 처리)"""
        result = route(
            source_type="unknown",
            source_count=5,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert result == Route.NEEDS_REVIEW

    def test_empty_source_type(self):
        """빈 source_type → NEEDS_REVIEW"""
        result = route(
            source_type="",
            source_count=0,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert result == Route.NEEDS_REVIEW

    def test_all_bad_conditions(self):
        """모든 조건이 나쁜 경우 → NEEDS_REVIEW"""
        result = route(
            source_type="internal",
            source_count=0,
            source_relevance="low",
            has_fabrication_risk=True,
        )
        assert result == Route.NEEDS_REVIEW


class TestRouteEnumValues:
    """Route enum 값 테스트"""

    def test_auto_approve_value(self):
        """AUTO_APPROVE enum 값 확인"""
        assert Route.AUTO_APPROVE.value == "auto_approved"

    def test_needs_review_value(self):
        """NEEDS_REVIEW enum 값 확인"""
        assert Route.NEEDS_REVIEW.value == "review_required"

    def test_auto_approve_label(self):
        """AUTO_APPROVE 한글 레이블 확인"""
        assert Route.AUTO_APPROVE.label == "자동 승인"

    def test_needs_review_label(self):
        """NEEDS_REVIEW 한글 레이블 확인"""
        assert Route.NEEDS_REVIEW.label == "검토 필요"


class TestRouteComparison:
    """enum 멤버 비교 방식 테스트 (docx_builder 사용 패턴)"""

    def test_compare_with_enum_member(self):
        """enum 멤버로 비교 (올바른 방식)"""
        decision = route(
            source_type="internal",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        # 올바른 비교 방식: enum 멤버 자체로 비교
        assert decision == Route.AUTO_APPROVE
        assert decision != Route.NEEDS_REVIEW

    def test_label_for_display(self):
        """문서/화면 출력용 레이블 사용 패턴"""
        decision = route(
            source_type="web",
            source_count=2,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        # 문서에는 .label을 사용 (영문 .value 노출 금지)
        assert decision == Route.NEEDS_REVIEW
        assert decision.label == "검토 필요"
        # .value는 내부용 (문서에 직접 노출하지 않음)
        assert decision.value == "review_required"

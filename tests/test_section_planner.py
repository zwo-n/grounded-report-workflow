"""
section_planner.py 유닛 테스트

테스트 케이스:
- 정상적인 섹션 계획 생성
- 빈 응답/파싱 실패 시 기본 섹션 폴백
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.section_planner import plan_sections, _parse_sections_response


class TestPlanSections:
    """plan_sections 함수 테스트"""

    def test_plan_sections_success(self):
        """정상적인 섹션 계획 생성"""
        def mock_client(messages):
            return json.dumps({
                "sections": [
                    {"title": "서론", "query": "제안서 서론을 작성해주세요", "order": 1},
                    {"title": "현황 분석", "query": "현재 클라우드 비용 현황을 분석해주세요", "order": 2},
                    {"title": "최적화 전략", "query": "비용 최적화 전략을 제안해주세요", "order": 3},
                    {"title": "기대 효과", "query": "최적화 시 기대되는 효과를 설명해주세요", "order": 4},
                    {"title": "결론", "query": "제안서 결론을 작성해주세요", "order": 5},
                ]
            })

        result = plan_sections(
            user_request="클라우드 비용 최적화 제안서 작성해줘",
            llm_client=mock_client,
        )

        assert len(result) == 5
        assert result[0]["title"] == "서론"
        assert result[0]["order"] == 1
        assert result[-1]["title"] == "결론"
        assert result[-1]["order"] == 5

        # 모든 섹션에 필수 필드 확인
        for section in result:
            assert "title" in section
            assert "query" in section
            assert "order" in section

    def test_plan_sections_empty_response_fallback(self):
        """빈 응답 시 기본 섹션으로 폴백"""
        def mock_client(messages):
            return ""

        result = plan_sections(
            user_request="테스트 요청",
            llm_client=mock_client,
        )

        # 기본 섹션 구성 확인
        assert len(result) == 3
        assert result[0]["title"] == "서론"
        assert result[1]["title"] == "본론"
        assert result[2]["title"] == "결론"

    def test_plan_sections_invalid_json_fallback(self):
        """유효하지 않은 JSON 응답 시 기본 섹션으로 폴백"""
        def mock_client(messages):
            return "이것은 JSON이 아닙니다"

        result = plan_sections(
            user_request="테스트 요청",
            llm_client=mock_client,
        )

        # 기본 섹션 구성 확인
        assert len(result) == 3
        assert result[0]["title"] == "서론"

    def test_prompt_contains_user_request(self):
        """프롬프트에 사용자 요청이 포함되는지 확인"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"sections": []})

        plan_sections(
            user_request="AI 기술 동향 보고서",
            llm_client=mock_client,
        )

        user_message = captured_messages[0][1]["content"]
        assert "AI 기술 동향 보고서" in user_message


class TestParseSectionsResponse:
    """_parse_sections_response 함수 테스트"""

    def test_parse_valid_response(self):
        """유효한 응답 파싱"""
        raw = json.dumps({
            "sections": [
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "본론", "query": "본론 작성", "order": 2},
            ]
        })
        result = _parse_sections_response(raw)

        assert len(result) == 2
        assert result[0]["title"] == "서론"
        assert result[1]["title"] == "본론"

    def test_parse_unordered_sections(self):
        """순서가 뒤섞인 섹션 정렬 확인"""
        raw = json.dumps({
            "sections": [
                {"title": "결론", "query": "결론 작성", "order": 3},
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "본론", "query": "본론 작성", "order": 2},
            ]
        })
        result = _parse_sections_response(raw)

        assert result[0]["title"] == "서론"
        assert result[1]["title"] == "본론"
        assert result[2]["title"] == "결론"

    def test_parse_empty_sections_fallback(self):
        """빈 섹션 배열 -> 기본 섹션 폴백"""
        raw = json.dumps({"sections": []})
        result = _parse_sections_response(raw)

        assert len(result) == 3
        assert result[0]["title"] == "서론"

    def test_parse_missing_required_fields(self):
        """필수 필드 누락된 섹션 필터링"""
        raw = json.dumps({
            "sections": [
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "제목만"},  # query 없음 -> 필터링
                {"query": "쿼리만", "order": 3},  # title 없음 -> 필터링
            ]
        })
        result = _parse_sections_response(raw)

        assert len(result) == 1
        assert result[0]["title"] == "서론"

    def test_parse_empty_string_fallback(self):
        """빈 문자열 -> 기본 섹션 폴백"""
        result = _parse_sections_response("")
        assert len(result) == 3

    def test_parse_none_fallback(self):
        """None 입력 -> 기본 섹션 폴백"""
        result = _parse_sections_response(None)
        assert len(result) == 3

"""
section_planner.py 유닛 테스트

테스트 케이스:
- 정상적인 섹션 계획 생성
- 빈 응답/파싱 실패 시 기본 섹션 폴백
- template_hint 명시적 제공 시 few-shot 예시 포함
- template_hint 없을 때 자동 감지 + 섹션 생성 통합
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.section_planner import (
    plan_sections,
    _parse_plan_response,
    AVAILABLE_TEMPLATES,
)
from pipeline.templates import (
    get_template,
    format_template_as_example,
    format_templates_for_detection,
    TEMPLATES,
)


class TestPlanSections:
    """plan_sections 함수 테스트"""

    def test_plan_sections_success(self):
        """정상적인 섹션 계획 생성"""
        def mock_client(messages):
            return json.dumps({
                "template_hint": "제안서",
                "sections": [
                    {"title": "서론", "query": "제안서 서론을 작성해주세요", "order": 1},
                    {"title": "현황 분석", "query": "현재 클라우드 비용 현황을 분석해주세요", "order": 2},
                    {"title": "최적화 전략", "query": "비용 최적화 전략을 제안해주세요", "order": 3},
                    {"title": "기대 효과", "query": "최적화 시 기대되는 효과를 설명해주세요", "order": 4},
                    {"title": "결론", "query": "제안서 결론을 작성해주세요", "order": 5},
                ]
            })

        sections, detected_hint = plan_sections(
            user_request="클라우드 비용 최적화 제안서 작성해줘",
            llm_client=mock_client,
        )

        assert len(sections) == 5
        assert sections[0]["title"] == "서론"
        assert sections[0]["order"] == 1
        assert sections[-1]["title"] == "결론"
        assert sections[-1]["order"] == 5
        assert detected_hint == "제안서"

        # 모든 섹션에 필수 필드 확인
        for section in sections:
            assert "title" in section
            assert "query" in section
            assert "order" in section

    def test_plan_sections_empty_response_fallback(self):
        """빈 응답 시 기본 섹션으로 폴백"""
        def mock_client(messages):
            return ""

        sections, detected_hint = plan_sections(
            user_request="테스트 요청",
            llm_client=mock_client,
        )

        # 기본 섹션 구성 확인
        assert len(sections) == 3
        assert sections[0]["title"] == "서론"
        assert sections[1]["title"] == "본론"
        assert sections[2]["title"] == "결론"
        assert detected_hint is None

    def test_plan_sections_invalid_json_fallback(self):
        """유효하지 않은 JSON 응답 시 기본 섹션으로 폴백"""
        def mock_client(messages):
            return "이것은 JSON이 아닙니다"

        sections, detected_hint = plan_sections(
            user_request="테스트 요청",
            llm_client=mock_client,
        )

        # 기본 섹션 구성 확인
        assert len(sections) == 3
        assert sections[0]["title"] == "서론"
        assert detected_hint is None

    def test_prompt_contains_user_request(self):
        """프롬프트에 사용자 요청이 포함되는지 확인"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"template_hint": None, "sections": []})

        plan_sections(
            user_request="AI 기술 동향 보고서",
            llm_client=mock_client,
        )

        user_message = captured_messages[0][1]["content"]
        assert "AI 기술 동향 보고서" in user_message


class TestParsePlanResponse:
    """_parse_plan_response 함수 테스트"""

    def test_parse_valid_response(self):
        """유효한 응답 파싱"""
        raw = json.dumps({
            "template_hint": "제안서",
            "sections": [
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "본론", "query": "본론 작성", "order": 2},
            ]
        })
        sections, hint = _parse_plan_response(raw)

        assert len(sections) == 2
        assert sections[0]["title"] == "서론"
        assert sections[1]["title"] == "본론"
        assert hint == "제안서"

    def test_parse_unordered_sections(self):
        """순서가 뒤섞인 섹션 정렬 확인"""
        raw = json.dumps({
            "template_hint": None,
            "sections": [
                {"title": "결론", "query": "결론 작성", "order": 3},
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "본론", "query": "본론 작성", "order": 2},
            ]
        })
        sections, hint = _parse_plan_response(raw)

        assert sections[0]["title"] == "서론"
        assert sections[1]["title"] == "본론"
        assert sections[2]["title"] == "결론"
        assert hint is None

    def test_parse_empty_sections_fallback(self):
        """빈 섹션 배열 -> 기본 섹션 폴백"""
        raw = json.dumps({"template_hint": "제안서", "sections": []})
        sections, hint = _parse_plan_response(raw)

        assert len(sections) == 3
        assert sections[0]["title"] == "서론"
        assert hint == "제안서"  # 힌트는 유지

    def test_parse_missing_required_fields(self):
        """필수 필드 누락된 섹션 필터링"""
        raw = json.dumps({
            "sections": [
                {"title": "서론", "query": "서론 작성", "order": 1},
                {"title": "제목만"},  # query 없음 -> 필터링
                {"query": "쿼리만", "order": 3},  # title 없음 -> 필터링
            ]
        })
        sections, _ = _parse_plan_response(raw)

        assert len(sections) == 1
        assert sections[0]["title"] == "서론"

    def test_parse_empty_string_fallback(self):
        """빈 문자열 -> 기본 섹션 폴백"""
        sections, hint = _parse_plan_response("")
        assert len(sections) == 3
        assert hint is None

    def test_parse_none_fallback(self):
        """None 입력 -> 기본 섹션 폴백"""
        sections, hint = _parse_plan_response(None)
        assert len(sections) == 3
        assert hint is None

    def test_parse_invalid_template_hint(self):
        """유효하지 않은 template_hint -> None으로 처리"""
        raw = json.dumps({
            "template_hint": "존재하지않는템플릿",
            "sections": [{"title": "서론", "query": "서론 작성", "order": 1}]
        })
        sections, hint = _parse_plan_response(raw)

        assert len(sections) == 1
        assert hint is None  # 유효하지 않은 힌트는 None


class TestTemplateHintExplicit:
    """template_hint 명시적 제공 시 동작 테스트"""

    def test_with_template_hint_includes_example(self):
        """template_hint 제공 시 프롬프트에 few-shot 예시 포함"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({
                "sections": [
                    {"title": "서론", "query": "서론 작성", "order": 1},
                    {"title": "결론", "query": "결론 작성", "order": 2},
                ]
            })

        sections, returned_hint = plan_sections(
            user_request="AWS 비용 절감 방안",
            template_hint="제안서",
            llm_client=mock_client,
        )

        user_message = captured_messages[0][1]["content"]

        # 프롬프트에 템플릿 관련 내용 포함 확인
        assert "제안서" in user_message
        assert "참고 예시" in user_message
        assert "현황 분석" in user_message  # 제안서 템플릿의 섹션
        assert "기대 효과" in user_message  # 제안서 템플릿의 섹션

        # 결과 확인
        assert len(sections) == 2
        assert returned_hint == "제안서"  # 명시적 제공 시 그대로 반환

    def test_explicit_hint_skips_detection_prompt(self):
        """명시적 template_hint 제공 시 감지 프롬프트 미포함"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"sections": []})

        plan_sections(
            user_request="테스트 요청",
            template_hint="제안서",
            llm_client=mock_client,
        )

        system_message = captured_messages[0][0]["content"]

        # 감지 관련 프롬프트가 없어야 함
        assert "문서 유형 판단" not in system_message
        assert "1단계" not in system_message

    def test_unknown_template_hint_ignored(self):
        """존재하지 않는 template_hint는 무시"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"sections": []})

        sections, returned_hint = plan_sections(
            user_request="테스트 요청",
            template_hint="존재하지않는템플릿",
            llm_client=mock_client,
        )

        user_message = captured_messages[0][1]["content"]

        # 존재하지 않는 템플릿이면 예시 미포함
        assert "참고 예시" not in user_message
        # 실제로 적용되지 않았으므로 None 반환
        assert returned_hint is None


class TestTemplateHintAutoDetection:
    """template_hint 자동 감지 동작 테스트"""

    def test_auto_detect_proposal(self):
        """자동 감지: 제안서 유형"""
        def mock_client(messages):
            return json.dumps({
                "template_hint": "제안서",
                "sections": [
                    {"title": "서론", "query": "서론", "order": 1},
                    {"title": "제안 내용", "query": "제안", "order": 2},
                ]
            })

        sections, detected_hint = plan_sections(
            user_request="클라우드 비용 최적화 제안서 작성해줘",
            template_hint=None,  # 자동 감지
            llm_client=mock_client,
        )

        assert detected_hint == "제안서"
        assert len(sections) == 2

    def test_auto_detect_technical_report(self):
        """자동 감지: 기술 보고서 유형"""
        def mock_client(messages):
            return json.dumps({
                "template_hint": "기술 보고서",
                "sections": [
                    {"title": "서론", "query": "서론", "order": 1},
                    {"title": "기술 분석", "query": "분석", "order": 2},
                ]
            })

        sections, detected_hint = plan_sections(
            user_request="AI 기술 동향 보고서 작성해줘",
            template_hint=None,
            llm_client=mock_client,
        )

        assert detected_hint == "기술 보고서"

    def test_auto_detect_no_match(self):
        """자동 감지: 매칭 없음 -> None"""
        def mock_client(messages):
            return json.dumps({
                "template_hint": None,
                "sections": [
                    {"title": "서론", "query": "서론", "order": 1},
                ]
            })

        sections, detected_hint = plan_sections(
            user_request="우리 팀 회의 정리해줘",
            template_hint=None,
            llm_client=mock_client,
        )

        assert detected_hint is None

    def test_auto_detect_prompt_contains_template_descriptions(self):
        """자동 감지 프롬프트에 템플릿 설명 포함"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"template_hint": None, "sections": []})

        plan_sections(
            user_request="테스트 요청",
            template_hint=None,
            llm_client=mock_client,
        )

        system_message = captured_messages[0][0]["content"]

        # 모든 템플릿의 이름과 description이 프롬프트에 포함되어야 함
        for name, template in TEMPLATES.items():
            assert name in system_message
            assert template["description"] in system_message


class TestTemplates:
    """templates.py 테스트"""

    def test_get_template_exists(self):
        """존재하는 템플릿 조회"""
        template = get_template("제안서")
        assert template is not None
        assert "description" in template
        assert "sections" in template
        assert len(template["sections"]) > 0

    def test_get_template_not_exists(self):
        """존재하지 않는 템플릿 조회"""
        template = get_template("없는템플릿")
        assert template is None

    def test_format_template_as_example(self):
        """템플릿을 예시 문자열로 변환"""
        template = get_template("제안서")
        example = format_template_as_example(template)

        assert "문서 유형:" in example
        assert "섹션 구성 예시:" in example
        assert "서론" in example
        assert "결론" in example

    def test_format_templates_for_detection(self):
        """템플릿 목록을 감지용 문자열로 변환"""
        detection_text = format_templates_for_detection()

        for name, template in TEMPLATES.items():
            assert name in detection_text
            assert template["description"] in detection_text

    def test_templates_have_required_fields(self):
        """모든 템플릿이 필수 필드를 가지는지 확인"""
        for name, template in TEMPLATES.items():
            assert "description" in template, f"{name} 템플릿에 description 없음"
            assert "sections" in template, f"{name} 템플릿에 sections 없음"

            for section in template["sections"]:
                assert "title" in section, f"{name} 템플릿 섹션에 title 없음"
                assert "query" in section, f"{name} 템플릿 섹션에 query 없음"
                assert "order" in section, f"{name} 템플릿 섹션에 order 없음"

"""
classifier.py 유닛 테스트

테스트 케이스:
- "none" 분류 (서론, 결론 등)
- "internal" 분류 (회사 내부 정보)
- "web" 분류 (외부 시장 정보)
- 파싱 실패 시 기본값 "internal" 반환
"""

import json
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.classifier import classify_source_type, _parse_classification_response


class TestClassifySourceType:
    """classify_source_type 함수 테스트"""

    def test_classify_none_section(self):
        """서론/결론 섹션 -> none 분류"""
        def mock_client(messages):
            return json.dumps({"source_type": "none"})

        result = classify_source_type(
            section_title="서론",
            section_query="보고서 서론을 작성해주세요",
            llm_client=mock_client,
        )
        assert result == "none"

    def test_classify_internal_section(self):
        """회사 내부 정보 섹션 -> internal 분류"""
        def mock_client(messages):
            return json.dumps({"source_type": "internal"})

        result = classify_source_type(
            section_title="회사 기술 역량",
            section_query="회사의 주요 기술 역량과 프로젝트 경험을 설명해주세요",
            llm_client=mock_client,
        )
        assert result == "internal"

    def test_classify_web_section(self):
        """외부 시장 정보 섹션 -> web 분류"""
        def mock_client(messages):
            return json.dumps({"source_type": "web"})

        result = classify_source_type(
            section_title="시장 동향",
            section_query="RAG 기반 문서 자동화 시장 동향을 설명해주세요",
            llm_client=mock_client,
        )
        assert result == "web"

    def test_prompt_contains_section_info(self):
        """프롬프트에 섹션 정보가 포함되는지 확인"""
        captured_messages = []

        def mock_client(messages):
            captured_messages.append(messages)
            return json.dumps({"source_type": "internal"})

        classify_source_type(
            section_title="테스트 제목",
            section_query="테스트 쿼리입니다",
            llm_client=mock_client,
        )

        user_message = captured_messages[0][1]["content"]
        assert "테스트 제목" in user_message
        assert "테스트 쿼리입니다" in user_message


class TestParseClassificationResponse:
    """_parse_classification_response 함수 테스트"""

    def test_parse_valid_none(self):
        """유효한 none 응답 파싱"""
        result = _parse_classification_response('{"source_type": "none"}')
        assert result == "none"

    def test_parse_valid_internal(self):
        """유효한 internal 응답 파싱"""
        result = _parse_classification_response('{"source_type": "internal"}')
        assert result == "internal"

    def test_parse_valid_web(self):
        """유효한 web 응답 파싱"""
        result = _parse_classification_response('{"source_type": "web"}')
        assert result == "web"

    def test_parse_invalid_json(self):
        """유효하지 않은 JSON -> internal 폴백"""
        result = _parse_classification_response("not a json")
        assert result == "internal"

    def test_parse_missing_field(self):
        """source_type 필드 없음 -> internal 폴백"""
        result = _parse_classification_response('{"other_field": "value"}')
        assert result == "internal"

    def test_parse_invalid_value(self):
        """유효하지 않은 source_type 값 -> internal 폴백"""
        result = _parse_classification_response('{"source_type": "invalid"}')
        assert result == "internal"

    def test_parse_empty_string(self):
        """빈 문자열 -> internal 폴백"""
        result = _parse_classification_response("")
        assert result == "internal"


class TestProcessSectionIntegration:
    """process_section과 classifier 통합 테스트"""

    def test_none_classification_flow(self):
        """none 분류 -> 검색 없이 처리"""
        from pipeline.main import process_section

        def mock_classifier(messages):
            return json.dumps({"source_type": "none"})

        def mock_llm(messages):
            return json.dumps({
                "answer": "테스트 서론입니다.",
                "source_type": "none",
                "source_count": 0,
                "source_relevance": "low",
                "has_fabrication_risk": False,
            })

        section = {"title": "서론", "query": "서론을 작성해주세요"}
        llm_result, decision, sources, classified_type = process_section(
            section,
            llm_client=mock_llm,
            classifier_client=mock_classifier,
        )

        assert classified_type == "none"
        assert llm_result["source_type"] == "none"
        assert len(sources) == 0

    def test_internal_classification_flow(self):
        """internal 분류 -> 내부 검색 수행"""
        from pipeline.main import process_section
        from pipeline.router import Route

        def mock_classifier(messages):
            return json.dumps({"source_type": "internal"})

        def mock_llm(messages):
            return json.dumps({
                "answer": "회사의 기술 역량입니다.",
                "source_type": "internal",
                "source_count": 3,
                "source_relevance": "high",
                "has_fabrication_risk": False,
            })

        section = {"title": "회사 기술 역량", "query": "기술 역량을 설명해주세요"}
        llm_result, decision, sources, classified_type = process_section(
            section,
            llm_client=mock_llm,
            classifier_client=mock_classifier,
        )

        assert classified_type == "internal"
        assert llm_result["source_type"] == "internal"
        assert len(sources) > 0  # rag_tool 목업 데이터 반환
        assert decision == Route.AUTO_APPROVE

    def test_web_classification_flow(self):
        """web 분류 -> 웹 검색 수행"""
        from pipeline.main import process_section
        from pipeline.router import Route

        def mock_classifier(messages):
            return json.dumps({"source_type": "web"})

        def mock_llm(messages):
            return json.dumps({
                "answer": "시장 동향입니다.",
                "source_type": "web",
                "source_count": 3,
                "source_relevance": "high",
                "has_fabrication_risk": False,
            })

        section = {"title": "시장 동향", "query": "시장 동향을 설명해주세요"}
        llm_result, decision, sources, classified_type = process_section(
            section,
            llm_client=mock_llm,
            classifier_client=mock_classifier,
        )

        assert classified_type == "web"
        assert llm_result["source_type"] == "web"
        assert len(sources) > 0  # web_search 목업 데이터 반환
        assert decision == Route.AUTO_APPROVE

    def test_internal_to_web_fallback(self):
        """internal 분류 -> 관련성 낮음 -> 웹 폴백"""
        from pipeline.main import process_section

        def mock_classifier(messages):
            return json.dumps({"source_type": "internal"})

        call_count = [0]

        def mock_llm(messages):
            call_count[0] += 1
            user_msg = messages[-1]["content"]

            # 첫 번째 호출 (internal): 관련성 낮음
            if "rag://internal" in user_msg:
                return json.dumps({
                    "answer": "관련 정보를 찾기 어렵습니다.",
                    "source_type": "internal",
                    "source_count": 1,
                    "source_relevance": "low",
                    "has_fabrication_risk": False,
                })
            # 두 번째 호출 (web fallback): 정상 응답
            else:
                return json.dumps({
                    "answer": "웹 검색 결과입니다.",
                    "source_type": "web",
                    "source_count": 2,
                    "source_relevance": "medium",
                    "has_fabrication_risk": False,
                })

        section = {"title": "차별화 전략", "query": "차별화 전략을 설명해주세요"}
        llm_result, decision, sources, classified_type = process_section(
            section,
            llm_client=mock_llm,
            classifier_client=mock_classifier,
        )

        assert classified_type == "internal"  # 초기 분류는 internal
        assert llm_result["source_type"] == "web"  # 폴백 후 최종은 web
        assert call_count[0] == 2  # LLM 2회 호출 (internal + web fallback)

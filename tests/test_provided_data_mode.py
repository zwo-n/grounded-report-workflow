"""
test_provided_data_mode.py - provided_data 모드 통합 테스트

테스트 대상:
- 고정 템플릿(gambarlabs_report) + 제공 데이터 모드 전체 흐름
- 템플릿 플레이스홀더 치환
- RAG 오염 없음 검증

Note:
- 실제 LLM API 호출을 mock으로 대체하여 테스트
- 실제 API 호출 테스트는 별도 통합 테스트로 수행
"""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from pipeline.data_ingest import ingest_tabular, ingest_text, ProvidedChunk
from pipeline.templates import is_fixed_template, get_fixed_sections, TEMPLATES
from pipeline.section_planner import plan_sections
from pipeline.router import route, Route
from pipeline.main import process_section_with_provided_data
from pipeline.docx_builder import build_from_template, get_template_path


class TestFixedTemplate:
    """고정 템플릿 관련 테스트"""

    def test_gambarlabs_report_is_fixed(self):
        assert is_fixed_template("gambarlabs_report") is True

    def test_proposal_is_not_fixed(self):
        assert is_fixed_template("제안서") is False

    def test_unknown_template_is_not_fixed(self):
        assert is_fixed_template("존재하지않는템플릿") is False

    def test_get_fixed_sections_returns_sections(self):
        sections = get_fixed_sections("gambarlabs_report")
        assert sections is not None
        assert len(sections) == 3
        titles = [s["title"] for s in sections]
        assert "개요" in titles
        assert "주요내용" in titles
        assert "결론및제언" in titles

    def test_fixed_sections_have_match_keywords(self):
        sections = get_fixed_sections("gambarlabs_report")
        for section in sections:
            assert "match_keywords" in section
            assert len(section["match_keywords"]) > 0


class TestPlanSectionsWithFixedTemplate:
    """plan_sections 고정 템플릿 분기 테스트"""

    def test_force_fixed_skips_llm(self):
        """force_fixed=True일 때 LLM 호출 없이 고정 섹션 반환"""
        mock_client = MagicMock()

        sections, title, hint = plan_sections(
            user_request="2026년 7월 활동 보고서",
            template_hint="gambarlabs_report",
            llm_client=mock_client,
            force_fixed=True,
        )

        # LLM 호출 없음
        mock_client.assert_not_called()

        # 고정 섹션 반환
        assert len(sections) == 3
        assert sections[0]["title"] == "개요"

    def test_fixed_template_auto_detected(self):
        """is_fixed_template이 True면 자동으로 고정 섹션 사용"""
        mock_client = MagicMock()

        sections, title, hint = plan_sections(
            user_request="활동 보고서",
            template_hint="gambarlabs_report",
            llm_client=mock_client,
            force_fixed=False,  # force_fixed가 False여도 is_fixed_template 체크
        )

        # gambarlabs_report는 fixed=True이므로 LLM 호출 없음
        mock_client.assert_not_called()


class TestProcessSectionWithProvidedData:
    """process_section_with_provided_data 함수 테스트"""

    @pytest.fixture
    def sample_chunks(self) -> list[ProvidedChunk]:
        return [
            {
                "content": "7월 1주차 RAG 파이프라인 개발 완료",
                "source_title": "활동일지.csv",
                "source_url": "provided://활동일지.csv#row1",
                "topic_keywords": ["7월", "RAG", "파이프라인", "개발"],
                "score": 1.0,
            },
            {
                "content": "정기 회의 진행, 프로젝트 진척 공유",
                "source_title": "활동일지.csv",
                "source_url": "provided://활동일지.csv#row2",
                "topic_keywords": ["회의", "프로젝트"],
                "score": 1.0,
            },
            {
                "content": "향후 계획: 테스트 자동화 구축 예정",
                "source_title": "활동일지.csv",
                "source_url": "provided://활동일지.csv#row3",
                "topic_keywords": ["향후", "계획", "테스트", "자동화"],
                "score": 1.0,
            },
        ]

    @pytest.fixture
    def mock_llm_client(self):
        """LLM 응답을 mock"""
        def mock_client(messages):
            return """{
                "answer": "테스트 응답입니다.",
                "source_type": "provided_data",
                "source_count": 1,
                "source_relevance": "high",
                "has_fabrication_risk": false
            }"""
        return mock_client

    def test_section_with_matching_chunks(self, sample_chunks, mock_llm_client):
        section = {
            "title": "주요내용",
            "query": "주요 활동 내용을 상세히 기술해주세요",
            "match_keywords": ["개발", "회의", "테스트"],
        }

        llm_result, decision, sources, classified_type = process_section_with_provided_data(
            section,
            sample_chunks,
            llm_client=mock_llm_client,
            document_title="7월 활동 보고서",
        )

        assert classified_type == "provided_data"
        assert len(sources) > 0  # 매칭된 sources가 있어야 함

    def test_section_without_matching_chunks(self, mock_llm_client):
        """매칭되는 chunk가 없는 경우"""
        section = {
            "title": "결론",
            "query": "결론을 작성해주세요",
            "match_keywords": ["존재하지않는키워드"],
        }

        empty_chunks: list[ProvidedChunk] = []

        llm_result, decision, sources, classified_type = process_section_with_provided_data(
            section,
            empty_chunks,
            llm_client=mock_llm_client,
        )

        # 매칭 없으면 근거 부족 처리
        assert llm_result["source_count"] == 0
        assert decision == Route.NEEDS_REVIEW


class TestRouterWithProvidedData:
    """router.py의 provided_data 라우팅 테스트"""

    def test_provided_data_high_relevance_auto_approve(self):
        decision = route(
            source_type="provided_data",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=False,
        )
        assert decision == Route.AUTO_APPROVE

    def test_provided_data_medium_relevance_auto_approve(self):
        decision = route(
            source_type="provided_data",
            source_count=2,
            source_relevance="medium",
            has_fabrication_risk=False,
        )
        assert decision == Route.AUTO_APPROVE

    def test_provided_data_low_relevance_needs_review(self):
        decision = route(
            source_type="provided_data",
            source_count=1,
            source_relevance="low",
            has_fabrication_risk=False,
        )
        assert decision == Route.NEEDS_REVIEW

    def test_provided_data_with_fabrication_risk_needs_review(self):
        decision = route(
            source_type="provided_data",
            source_count=3,
            source_relevance="high",
            has_fabrication_risk=True,
        )
        assert decision == Route.NEEDS_REVIEW


class TestTemplatePlaceholderReplacement:
    """템플릿 플레이스홀더 치환 테스트"""

    @pytest.fixture
    def template_path(self):
        path = get_template_path("gambarlabs_report")
        if path is None or not path.exists():
            pytest.skip("gambarlabs_report 템플릿 파일 없음")
        return path

    def test_get_template_path(self):
        path = get_template_path("gambarlabs_report")
        # 템플릿 경로가 정의되어 있어야 함
        assert "docx_template_path" in TEMPLATES.get("gambarlabs_report", {})

    def test_build_from_template_replaces_title(self, template_path):
        doc = build_from_template(
            template_path,
            {"{{TITLE}}": "테스트 문서 제목"}
        )

        # 문서가 생성되어야 함
        assert doc is not None

        # 플레이스홀더가 치환되었는지 확인 (표 내 텍스트 검사)
        found_title = False
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if "테스트 문서 제목" in cell.text:
                        found_title = True
                        break

        assert found_title, "{{TITLE}} 플레이스홀더가 치환되지 않음"

    def test_build_from_template_replaces_multiple(self, template_path):
        placeholders = {
            "{{TITLE}}": "테스트 보고서",
            "{{OVERVIEW}}": "개요 내용입니다.",
            "{{MAIN_CONTENT}}": "주요 내용입니다.",
            "{{CONCLUSION}}": "결론 내용입니다.",
        }

        doc = build_from_template(template_path, placeholders)
        assert doc is not None


class TestRagIsolation:
    """RAG 오염 방지 테스트"""

    def test_provided_chunks_not_persisted(self):
        """provided_chunks는 메모리에만 존재하고 RAG 인덱스에 저장되지 않음"""
        # data_ingest 모듈은 RAG 인덱스(rag_tool.py)를 import하지 않음
        import pipeline.data_ingest as di
        import inspect

        source = inspect.getsource(di)
        assert "rag_tool" not in source
        assert "chroma" not in source.lower()
        assert "vectorstore" not in source.lower()

    def test_source_url_format_is_distinct(self):
        """provided_data의 source_url은 'provided://' 접두사로 구분됨"""
        chunks = ingest_text("테스트 데이터", source_name="테스트")

        for chunk in chunks:
            assert chunk["source_url"].startswith("provided://")
            # internal/web 형식과 다름
            assert not chunk["source_url"].startswith("rag://")
            assert not chunk["source_url"].startswith("http")


class TestEndToEndMocked:
    """전체 흐름 Mock 테스트"""

    @pytest.fixture
    def mock_csv_path(self):
        path = Path(__file__).parent.parent / "assets" / "mock_provided_data.csv"
        if not path.exists():
            pytest.skip("mock_provided_data.csv 파일 없음")
        return path

    def test_full_pipeline_flow(self, mock_csv_path):
        """전체 파이프라인 흐름 테스트 (LLM mock)"""
        # 1. 데이터 인제스트
        chunks = ingest_tabular(mock_csv_path)
        assert len(chunks) > 0

        # 2. 고정 템플릿 섹션 가져오기
        sections = get_fixed_sections("gambarlabs_report")
        assert sections is not None

        # 3. 각 섹션별 매칭 테스트
        for section in sections:
            from pipeline.web_search import _extract_topic_keywords

            # 섹션 키워드 추출
            section_keywords = section.get("match_keywords", []).copy()
            combined_text = f"{section['title']} {section['query']}"
            dynamic_keywords = _extract_topic_keywords(combined_text)
            section_keywords.extend(dynamic_keywords)

            # 중복 제거
            section_keywords = list(dict.fromkeys(section_keywords))

            # 매칭
            from pipeline.data_ingest import filter_chunks_by_keywords
            matched = filter_chunks_by_keywords(chunks, section_keywords, min_match=1)

            # 적어도 일부 섹션은 매칭이 되어야 함
            print(f"[{section['title']}] {len(matched)}개 매칭")

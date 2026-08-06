"""
test_data_ingest.py - data_ingest 모듈 단위 테스트

테스트 대상:
- ingest_tabular: CSV/Excel 파일 인제스트
- ingest_text: 비정형 텍스트 인제스트
- filter_chunks_by_keywords: 키워드 기반 chunk 필터링
- _extract_keywords_from_text: 키워드 추출 내부 함수
"""

import pytest
from pathlib import Path
import tempfile

from pipeline.data_ingest import (
    ingest_tabular,
    ingest_text,
    filter_chunks_by_keywords,
    _extract_keywords_from_text,
    ProvidedChunk,
)


class TestExtractKeywords:
    """_extract_keywords_from_text 함수 테스트"""

    def test_extract_korean_keywords(self):
        text = "파이프라인 개발 및 테스트 완료"
        keywords = _extract_keywords_from_text(text)
        assert "파이프라인" in keywords
        assert "개발" in keywords
        assert "테스트" in keywords

    def test_extract_english_keywords(self):
        text = "RAG pipeline development"
        keywords = _extract_keywords_from_text(text)
        assert "RAG" in keywords
        assert "pipeline" in keywords
        assert "development" in keywords

    def test_filter_stopwords(self):
        text = "내용 확인 결과 테스트 완료"
        keywords = _extract_keywords_from_text(text)
        # 불용어는 제외되어야 함
        assert "내용" not in keywords
        assert "확인" not in keywords
        assert "테스트" in keywords

    def test_minimum_length(self):
        text = "A 가 테스트"
        keywords = _extract_keywords_from_text(text)
        # 1글자는 제외
        assert "A" not in keywords
        assert "가" not in keywords
        assert "테스트" in keywords

    def test_max_keywords_limit(self):
        text = "하나 둘셋 넷다섯 여섯일곱 여덟아홉 열하나 열둘셋 열넷다섯 열여섯일곱 열여덟아홉 스물하나 스물둘"
        keywords = _extract_keywords_from_text(text)
        assert len(keywords) <= 10

    def test_empty_text(self):
        assert _extract_keywords_from_text("") == []
        assert _extract_keywords_from_text(None) == []


class TestIngestText:
    """ingest_text 함수 테스트"""

    def test_basic_text_ingest(self):
        text = """첫 번째 단락입니다.

두 번째 단락입니다.

세 번째 단락입니다."""

        chunks = ingest_text(text, source_name="테스트")
        assert len(chunks) == 3
        assert chunks[0]["source_title"] == "테스트"
        assert "provided://테스트#chunk1" == chunks[0]["source_url"]

    def test_custom_separator(self):
        text = "항목1---항목2---항목3"
        chunks = ingest_text(text, source_name="구분자테스트", chunk_separator="---")
        assert len(chunks) == 3

    def test_empty_text(self):
        assert ingest_text("") == []
        assert ingest_text("   ") == []

    def test_chunk_has_keywords(self):
        text = "RAG 파이프라인 개발 완료"
        chunks = ingest_text(text, source_name="키워드테스트")
        assert len(chunks) == 1
        assert "파이프라인" in chunks[0]["topic_keywords"]

    def test_chunk_has_default_score(self):
        text = "테스트 데이터"
        chunks = ingest_text(text)
        assert chunks[0]["score"] == 1.0


class TestIngestTabular:
    """ingest_tabular 함수 테스트"""

    def test_csv_ingest(self):
        # 임시 CSV 파일 생성
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("날짜,활동,결과\n")
            f.write("2026-07-01,개발,완료\n")
            f.write("2026-07-02,테스트,진행중\n")
            temp_path = f.name

        try:
            chunks = ingest_tabular(temp_path)
            assert len(chunks) == 2
            assert "날짜: 2026-07-01" in chunks[0]["content"]
            assert "활동: 개발" in chunks[0]["content"]
        finally:
            Path(temp_path).unlink()

    def test_specific_columns(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("A,B,C\n")
            f.write("1,2,3\n")
            temp_path = f.name

        try:
            chunks = ingest_tabular(temp_path, content_columns=["A", "B"])
            assert len(chunks) == 1
            assert "A: 1" in chunks[0]["content"]
            assert "B: 2" in chunks[0]["content"]
            assert "C: 3" not in chunks[0]["content"]
        finally:
            Path(temp_path).unlink()

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            ingest_tabular("/nonexistent/path.csv")

    def test_unsupported_format(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as f:
            temp_path = f.name

        try:
            with pytest.raises(ValueError, match="지원하지 않는 파일 형식"):
                ingest_tabular(temp_path)
        finally:
            Path(temp_path).unlink()

    def test_source_url_format(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write("col\n")
            f.write("val\n")
            temp_path = f.name

        try:
            chunks = ingest_tabular(temp_path)
            # source_url 형식: provided://<파일명>#row<N>
            assert chunks[0]["source_url"].startswith("provided://")
            assert "#row1" in chunks[0]["source_url"]
        finally:
            Path(temp_path).unlink()


class TestFilterChunksByKeywords:
    """filter_chunks_by_keywords 함수 테스트"""

    @pytest.fixture
    def sample_chunks(self) -> list[ProvidedChunk]:
        return [
            {
                "content": "RAG 파이프라인 개발",
                "source_title": "test.csv",
                "source_url": "provided://test.csv#row1",
                "topic_keywords": ["RAG", "파이프라인", "개발"],
                "score": 1.0,
            },
            {
                "content": "테스트 자동화 구축",
                "source_title": "test.csv",
                "source_url": "provided://test.csv#row2",
                "topic_keywords": ["테스트", "자동화", "구축"],
                "score": 1.0,
            },
            {
                "content": "회의 진행 완료",
                "source_title": "test.csv",
                "source_url": "provided://test.csv#row3",
                "topic_keywords": ["회의"],
                "score": 1.0,
            },
        ]

    def test_filter_by_single_keyword(self, sample_chunks):
        matched = filter_chunks_by_keywords(sample_chunks, ["RAG"])
        assert len(matched) == 1
        assert "RAG" in matched[0]["topic_keywords"]

    def test_filter_by_multiple_keywords(self, sample_chunks):
        matched = filter_chunks_by_keywords(sample_chunks, ["개발", "테스트"])
        assert len(matched) == 2

    def test_partial_match(self, sample_chunks):
        # 부분 문자열 매칭 테스트
        matched = filter_chunks_by_keywords(sample_chunks, ["파이프"])
        assert len(matched) >= 1

    def test_no_match(self, sample_chunks):
        matched = filter_chunks_by_keywords(sample_chunks, ["존재하지않는키워드"])
        assert len(matched) == 0

    def test_empty_keywords_returns_all(self, sample_chunks):
        matched = filter_chunks_by_keywords(sample_chunks, [])
        assert len(matched) == len(sample_chunks)

    def test_min_match_threshold(self, sample_chunks):
        # min_match=2: 최소 2개 키워드 매칭 필요
        matched = filter_chunks_by_keywords(
            sample_chunks,
            ["RAG", "파이프라인", "테스트"],
            min_match=2
        )
        # "RAG 파이프라인 개발"만 2개 이상 매칭
        assert len(matched) == 1
        assert matched[0]["source_url"] == "provided://test.csv#row1"

    def test_score_sorting(self, sample_chunks):
        matched = filter_chunks_by_keywords(
            sample_chunks,
            ["RAG", "파이프라인", "개발", "테스트"]
        )
        # 더 많이 매칭된 chunk가 먼저 와야 함
        if len(matched) > 1:
            assert matched[0]["score"] >= matched[1]["score"]

    def test_case_insensitive(self, sample_chunks):
        matched = filter_chunks_by_keywords(sample_chunks, ["rag"])
        assert len(matched) == 1


class TestMockProvidedDataCsv:
    """실제 mock_provided_data.csv 파일 테스트"""

    @pytest.fixture
    def mock_csv_path(self):
        path = Path(__file__).parent.parent / "assets" / "mock_provided_data.csv"
        if not path.exists():
            pytest.skip("mock_provided_data.csv 파일 없음")
        return path

    def test_ingest_mock_csv(self, mock_csv_path):
        chunks = ingest_tabular(mock_csv_path)
        assert len(chunks) > 0

        # 모든 chunk가 올바른 구조를 가지는지 확인
        for chunk in chunks:
            assert "content" in chunk
            assert "source_title" in chunk
            assert "source_url" in chunk
            assert "topic_keywords" in chunk
            assert "score" in chunk
            assert chunk["source_url"].startswith("provided://")

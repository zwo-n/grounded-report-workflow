"""
test_web_search.py - 통합 웹 검색 모듈 테스트

Tavily + Naver 통합 검색 모듈의 유닛 테스트입니다.
"""

import unittest
from unittest.mock import MagicMock, patch

from pipeline.web_search import (
    _calculate_naver_score,
    _clean_html,
    _extract_domain,
    _is_excluded_domain,
    EXCLUDED_DOMAINS,
    NAVER_EXCLUDED_DOMAINS,
    reset_call_counts,
    search_naver,
    search_tavily,
    search_web,
)


class TestHelperFunctions(unittest.TestCase):
    """헬퍼 함수 테스트"""

    def test_extract_domain_simple(self):
        """기본 도메인 추출"""
        self.assertEqual(
            _extract_domain("https://example.com/path"),
            "example.com",
        )

    def test_extract_domain_with_www(self):
        """www 접두사 제거"""
        self.assertEqual(
            _extract_domain("https://www.example.com/path"),
            "example.com",
        )

    def test_extract_domain_subdomain(self):
        """서브도메인 유지"""
        self.assertEqual(
            _extract_domain("https://blog.example.com/path"),
            "blog.example.com",
        )

    def test_is_excluded_domain_youtube(self):
        """유튜브 도메인 제외"""
        self.assertTrue(
            _is_excluded_domain("https://www.youtube.com/watch", EXCLUDED_DOMAINS)
        )
        self.assertTrue(
            _is_excluded_domain("https://youtu.be/123", EXCLUDED_DOMAINS)
        )

    def test_is_excluded_domain_naver_blog(self):
        """네이버 블로그 제외 (Naver 전용)"""
        self.assertTrue(
            _is_excluded_domain("https://blog.naver.com/user", NAVER_EXCLUDED_DOMAINS)
        )
        # 일반 EXCLUDED_DOMAINS에는 포함 안됨
        self.assertFalse(
            _is_excluded_domain("https://blog.naver.com/user", EXCLUDED_DOMAINS)
        )

    def test_is_excluded_domain_allowed(self):
        """허용 도메인"""
        self.assertFalse(
            _is_excluded_domain("https://techcrunch.com/article", EXCLUDED_DOMAINS)
        )

    def test_clean_html_tags(self):
        """HTML 태그 제거"""
        self.assertEqual(_clean_html("<b>Bold</b> text"), "Bold text")

    def test_clean_html_entities(self):
        """HTML 엔티티 변환"""
        self.assertEqual(_clean_html("A &amp; B &quot;test&quot;"), 'A & B "test"')

    def test_calculate_naver_score_first(self):
        """1위 점수 = 1.0"""
        self.assertEqual(_calculate_naver_score(1, 10), 1.0)

    def test_calculate_naver_score_last(self):
        """마지막 점수 = 0.5"""
        self.assertEqual(_calculate_naver_score(10, 10), 0.5)

    def test_calculate_naver_score_single(self):
        """단일 결과 = 1.0"""
        self.assertEqual(_calculate_naver_score(1, 1), 1.0)


class TestSearchTavily(unittest.TestCase):
    """search_tavily 함수 테스트"""

    def setUp(self):
        reset_call_counts()

    @patch("pipeline.web_search._is_mock_mode")
    @patch("pipeline.web_search._get_tavily_client")
    def test_no_client(self, mock_get_client, mock_is_mock):
        """클라이언트 없으면 빈 결과"""
        mock_is_mock.return_value = False
        mock_get_client.return_value = None
        result = search_tavily("test query")
        self.assertEqual(result, {"results": []})

    @patch("pipeline.web_search._is_mock_mode")
    def test_mock_mode(self, mock_is_mock):
        """Mock 모드 테스트"""
        mock_is_mock.return_value = True
        result = search_tavily("test query", max_results=2)
        self.assertIn("results", result)
        self.assertLessEqual(len(result["results"]), 2)


class TestSearchNaver(unittest.TestCase):
    """search_naver 함수 테스트"""

    def setUp(self):
        reset_call_counts()

    @patch("pipeline.web_search._is_mock_mode")
    @patch("pipeline.web_search._get_naver_credentials")
    def test_no_credentials(self, mock_creds, mock_is_mock):
        """인증 정보 없으면 빈 결과"""
        mock_is_mock.return_value = False
        mock_creds.return_value = None
        result = search_naver("test query")
        self.assertEqual(result, {"results": []})

    @patch("pipeline.web_search._is_mock_mode")
    def test_mock_mode(self, mock_is_mock):
        """Mock 모드 테스트"""
        mock_is_mock.return_value = True
        result = search_naver("test query", max_results=2)
        self.assertIn("results", result)
        self.assertLessEqual(len(result["results"]), 2)

    @patch("pipeline.web_search.requests.get")
    @patch("pipeline.web_search._get_naver_credentials")
    @patch("pipeline.web_search._is_mock_mode")
    def test_successful_search(self, mock_is_mock, mock_creds, mock_get):
        """성공적인 검색"""
        mock_is_mock.return_value = False
        mock_creds.return_value = ("id", "secret")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "total": 100,
            "items": [
                {
                    "title": "<b>AI</b> 기술 동향",
                    "description": "최신 <b>AI</b> 기술 분석",
                    "link": "https://news.example.com/ai",
                },
            ],
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = search_naver("AI 기술", max_results=2)

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["source_title"], "AI 기술 동향")
        self.assertEqual(result["results"][0]["content"], "최신 AI 기술 분석")


class TestSearchWebIntegrated(unittest.TestCase):
    """search_web 통합 함수 테스트"""

    def setUp(self):
        reset_call_counts()

    @patch("pipeline.web_search._is_mock_mode")
    def test_integrated_search_mock(self, mock_is_mock):
        """통합 검색 Mock 테스트"""
        mock_is_mock.return_value = True

        result = search_web(
            query="RAG 문서 자동화",
            query_global="RAG document automation",
            max_results=4,
        )

        self.assertIn("results", result)
        self.assertLessEqual(len(result["results"]), 4)

        # 결과에 [글로벌] 또는 [국내] 태그 확인
        titles = [r["source_title"] for r in result["results"]]
        has_global = any("[글로벌]" in t for t in titles)
        has_domestic = any("[국내]" in t for t in titles)
        self.assertTrue(has_global or has_domestic)

    @patch("pipeline.web_search._is_mock_mode")
    def test_results_sorted_by_score(self, mock_is_mock):
        """결과가 score 기준 정렬되는지 확인"""
        mock_is_mock.return_value = True

        result = search_web("test query", max_results=6)

        scores = [r["score"] for r in result["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))


if __name__ == "__main__":
    unittest.main()

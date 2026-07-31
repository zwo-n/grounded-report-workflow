"""
lang_guard.py 유닛 테스트

테스트 케이스:
- 순수 한국어 (완결된 문장)
- 순수 중국어
- 한중 혼용 (실제 qwen 이탈 패턴)
- 빈 문자열

Note: 테스트 데이터는 실제 LLM이 생성하는 완결된 한국어 문장 형태를 사용.
      소스 문서 조각(나열형 텍스트)은 검증 대상이 아님.
"""

import pytest
import sys
from pathlib import Path

# 프로젝트 루트를 path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.lang_guard import check_korean_ratio, is_language_valid, has_chinese


class TestCheckKoreanRatio:
    """check_korean_ratio 함수 테스트"""

    def test_pure_korean(self):
        """순수 한국어 텍스트 - 비율 1.0"""
        text = "안녕하세요 반갑습니다"
        ratio = check_korean_ratio(text)
        assert ratio == 1.0

    def test_pure_korean_with_punctuation(self):
        """한국어 + 숫자/특수문자 - 비율 1.0 (숫자/특수문자 제외)"""
        text = "2024년 프로젝트 완료! 성공률 95%"
        ratio = check_korean_ratio(text)
        assert ratio == 1.0

    def test_pure_chinese(self):
        """순수 중국어 텍스트 - 비율 0.0"""
        text = "你好世界欢迎光临"
        ratio = check_korean_ratio(text)
        assert ratio == 0.0

    def test_korean_chinese_mixed(self):
        """한중 혼용 텍스트"""
        text = "안녕하세요你好世界"
        ratio = check_korean_ratio(text)
        assert 0.5 <= ratio <= 0.6

    def test_korean_english_mixed(self):
        """한영 혼용 텍스트 (짧은 구문)"""
        text = "AWS Bedrock 기반 프로젝트"
        ratio = check_korean_ratio(text)
        assert 0.3 <= ratio <= 0.4

    def test_empty_string(self):
        """빈 문자열 - 비율 0.0"""
        ratio = check_korean_ratio("")
        assert ratio == 0.0

    def test_only_numbers_and_spaces(self):
        """숫자와 공백만 있는 경우 - 비율 0.0"""
        text = "123 456 789"
        ratio = check_korean_ratio(text)
        assert ratio == 0.0


class TestIsLanguageValid:
    """is_language_valid 함수 테스트 - 완결된 문장 기준"""

    def test_pure_korean_valid(self):
        """순수 한국어 완결 문장 - 유효"""
        text = "회사는 관세 문서 자동화 프로젝트를 성공적으로 완료했습니다."
        assert is_language_valid(text) is True

    def test_korean_with_technical_terms_valid(self):
        """한국어 + 영문 기술 용어 (완결 문장) - 50% 이상 유지"""
        text = (
            "회사는 AWS Bedrock Agent를 활용하여 통관 서류 자동 생성 시스템을 "
            "구축했으며, 이를 통해 업무 효율성을 크게 향상시켰습니다."
        )
        ratio = check_korean_ratio(text)
        assert ratio >= 0.5  # 기술 용어 포함 문장은 50% 이상 유지
        assert is_language_valid(text) is True

    def test_heavy_technical_terms_valid(self):
        """기술 용어가 많은 정상 답변 - 50% 이상이면 통과"""
        # 실제 qwen 테스트에서 받은 정상 답변 (한글 비율 약 53%)
        text = (
            "회사는 AWS Bedrock Agent 기반 통관 서류 자동 생성 시스템을 구축하여 "
            "수작업 대비 처리 시간을 80% 단축했습니다. 또한 LangGraph 기반 6단계 "
            "에이전트 파이프라인을 설계하여 클라우드 비용 이상탐지 시스템을 성공적으로 "
            "구현했습니다. 주요 기술스택으로는 AWS Bedrock(Claude, Titan Embedding), "
            "LangGraph, RAG(OpenSearch), 이상탐지 알고리즘(Isolation Forest, Z-score) "
            "등을 보유하고 있습니다."
        )
        ratio = check_korean_ratio(text)
        assert 0.5 <= ratio <= 0.6  # 기술 용어가 많아 50%대
        assert is_language_valid(text) is True  # 하지만 정상 통과

    def test_pure_chinese_invalid(self):
        """순수 중국어 - 무효 (언어 이탈)"""
        text = "这是一个自动化项目的描述文档"
        assert is_language_valid(text) is False

    def test_mostly_chinese_invalid(self):
        """대부분 중국어 - 무효"""
        text = "프로젝트 这是一个自动化项目的描述"
        assert is_language_valid(text) is False

    def test_empty_string_valid(self):
        """빈 문자열 - 유효 (근거 없음 케이스)"""
        assert is_language_valid("") is True

    def test_whitespace_only_valid(self):
        """공백만 있는 문자열 - 유효"""
        assert is_language_valid("   ") is True

    def test_threshold_boundary(self):
        """임계값 경계 테스트 - 정확히 50%"""
        text = "가나다라마ABCDE"  # 한글 5자, 영문 5자 = 50%
        ratio = check_korean_ratio(text)
        assert ratio == 0.5
        assert is_language_valid(text) is True  # 기본 임계값 50%에서 통과

    def test_threshold_boundary_fail(self):
        """임계값 미달 테스트 - 50% 미만"""
        text = "가나다라ABCDEF"  # 한글 4자, 영문 6자 = 40%
        ratio = check_korean_ratio(text)
        assert ratio == 0.4
        assert is_language_valid(text) is False  # 50% 미달로 실패


class TestHasChinese:
    """has_chinese 함수 테스트"""

    def test_pure_chinese(self):
        """순수 중국어 - True"""
        text = "这是一个自动化项目"
        assert has_chinese(text) is True

    def test_pure_korean(self):
        """순수 한국어 - False"""
        text = "이것은 자동화 프로젝트입니다"
        assert has_chinese(text) is False

    def test_korean_chinese_mixed(self):
        """한중 혼용 - True (중국어 10% 이상)"""
        text = "프로젝트 개요입니다. 这个项目是关于自动化的。"
        assert has_chinese(text) is True

    def test_korean_english_mixed(self):
        """한영 혼용 - False (중국어 없음)"""
        text = "AWS Bedrock 기반 프로젝트입니다"
        assert has_chinese(text) is False

    def test_empty_string(self):
        """빈 문자열 - False"""
        assert has_chinese("") is False

    def test_single_chinese_char_strict_zero_tolerance(self):
        """중국어 1글자만 섞여도 True (0% 허용, 과거 10% 임계값이면 통과했을 저비율 케이스)"""
        text = (
            "회사는 다양한 기술 역량을 보유하고 있으며 자동화 시스템 구축에 "
            "강점을 가지고 있습니다 关"
        )
        # 중국어 비율이 10% 미만인 저농도 케이스
        assert check_korean_ratio(text) > 0  # 대부분 한글
        assert has_chinese(text) is True
        assert is_language_valid(text) is False


class TestRealWorldCases:
    """실제 qwen 응답 패턴 테스트"""

    def test_valid_complete_answer(self):
        """정상적인 완결 문장 응답"""
        text = (
            "회사는 다양한 기술 역량을 보유하고 있으며, 특히 AWS Bedrock과 "
            "LangGraph를 활용한 자동화 시스템 구축에 강점을 가지고 있습니다. "
            "2024년에는 관세 문서 자동화 프로젝트와 클라우드 비용 이상탐지 "
            "프로젝트를 성공적으로 수행했습니다."
        )
        ratio = check_korean_ratio(text)
        assert ratio >= 0.5  # 기술 용어 포함 시 50% 이상
        assert is_language_valid(text) is True

    def test_valid_answer_with_tech_terms(self):
        """기술 용어가 포함된 완결 문장 응답"""
        text = (
            "클라우드 비용 이상탐지 프로젝트에서는 LangGraph 기반의 6단계 "
            "에이전트 파이프라인을 설계하여 비정상 과금 패턴을 실시간으로 "
            "탐지하는 시스템을 성공적으로 구현했습니다."
        )
        ratio = check_korean_ratio(text)
        assert ratio >= 0.5  # 기술 용어 포함 시 50% 이상
        assert is_language_valid(text) is True

    def test_qwen_mid_sentence_chinese_switch(self):
        """qwen 실제 이탈 패턴: 문장 중간에서 중국어로 전환"""
        text = (
            "회사는 다양한 기술을 활용하여 혁신적인 솔루션을 제공합니다. "
            "특히 AWS Bedrock를 사용한 자동화 시스템과 LangGraph 기반의 "
            "이상 탐지 프로젝트가 두典型案例分别是AWS Bedrock和LangGraph。"
            "在海关文件自动化项目中..."
        )
        assert has_chinese(text) is True
        assert is_language_valid(text) is False

    def test_qwen_full_chinese_hallucination(self):
        """qwen 이탈 패턴: 완전히 중국어로 응답"""
        text = "该公司在2024年成功完成了海关文件自动化项目和云成本异常检测项目。"
        assert is_language_valid(text) is False

    def test_qwen_gradual_transition(self):
        """qwen 이탈 패턴: 점진적으로 중국어 비율 증가"""
        text = (
            "회사는 기술 역량을 보유하고 있습니다. 主要技术包括AWS和LangGraph。"
            "这些技术被广泛应用于自动化项目中。"
        )
        assert has_chinese(text) is True
        assert is_language_valid(text) is False

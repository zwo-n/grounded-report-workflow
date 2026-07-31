"""
lang_guard.py - 응답 언어 검증 모듈 (2차 안전장치)

1차 방어는 llm_writer.py의 시스템 프롬프트(언어 하네스)가 담당합니다.
이 모듈은 하네스를 우회해 언어가 이탈한 응답을 사후에 걸러내는
fallback 역할만 수행합니다. qwen2.5 모델 테스트 시 약 20% 확률로
중국어 등 다른 언어가 섞이는 문제가 발견되어, 프롬프트 강화 이후에도
남을 수 있는 잔여 케이스를 감지하기 위해 유지합니다.

주요 기능:
- 한글 비율 체크 (threshold 기반)
- 언어 이탈 감지 (중국어 등 혼입 탐지)
"""

import re


def check_korean_ratio(text: str) -> float:
    """
    텍스트에서 한글 문자 비율을 계산합니다.

    Args:
        text: 검사할 텍스트

    Returns:
        한글 문자 비율 (0.0 ~ 1.0)
        공백, 숫자, 특수문자를 제외한 문자 중 한글의 비율
    """
    if not text:
        return 0.0

    # 공백, 숫자, 특수문자, 구두점 제외 (실제 "글자"만 카운트)
    # 한글: \uAC00-\uD7A3 (완성형), \u1100-\u11FF (자모)
    # 영문, 중국어 등 다른 문자도 포함해서 전체 문자 수 계산
    letters_only = re.sub(r'[\s\d\W]', '', text, flags=re.UNICODE)

    if not letters_only:
        return 0.0

    # 한글 문자 카운트 (완성형 + 자모)
    korean_pattern = re.compile(r'[\uAC00-\uD7A3\u1100-\u11FF]')
    korean_chars = korean_pattern.findall(letters_only)

    return len(korean_chars) / len(letters_only)


def has_chinese(text: str, threshold: float = 0.0) -> bool:
    """
    텍스트에 중국어가 threshold 비율을 초과하여 포함되어 있는지 확인합니다.

    Args:
        text: 검사할 텍스트
        threshold: 중국어 비율 임계값 (기본값 0.0 = 0%, 중국어가 한 글자라도
                   있으면 감지. 하네스 우회 시 즉시 차단하기 위한 fallback이므로
                   허용 오차를 두지 않음)

    Returns:
        True: 중국어가 threshold를 초과하여 포함됨 (threshold=0.0이면 1글자라도 포함 시)
        False: 중국어가 없음 (threshold 이하)
    """
    if not text:
        return False

    letters_only = re.sub(r'[\s\d\W]', '', text, flags=re.UNICODE)
    if not letters_only:
        return False

    # 중국어 문자 범위 (CJK Unified Ideographs)
    # 한자는 한국어에서도 쓰이지만, qwen 이탈 시 중국어 간체자가 주로 나옴
    chinese_pattern = re.compile(r'[\u4E00-\u9FFF]')
    chinese_chars = chinese_pattern.findall(letters_only)

    if not chinese_chars:
        return False

    return len(chinese_chars) / len(letters_only) > threshold


def is_language_valid(text: str, min_korean_ratio: float = 0.5) -> bool:
    """
    텍스트가 유효한 한국어인지 검증합니다.

    Args:
        text: 검사할 텍스트
        min_korean_ratio: 최소 한글 비율 (기본값 0.5 = 50%)
                          기술 용어(AWS, Bedrock, LangGraph 등)가 많이 포함된
                          정상적인 한국어 답변도 50% 이상을 유지함.
                          중국어 이탈은 has_chinese()에서 별도로 감지.

    Returns:
        True: 유효한 한국어 (비율 충족 또는 빈 문자열)
        False: 언어 이탈 (한글 비율 미달)

    Note:
        - 빈 문자열은 True를 반환합니다. (근거 없음 케이스)
        - 중국어가 한 글자라도 포함되면 has_chinese()에서 먼저 차단됩니다.
    """
    # 빈 문자열은 정상 케이스 (근거 없음 = answer가 빈 값)
    if not text or not text.strip():
        return True

    # 중국어가 한 글자라도 포함되면 언어 이탈로 판단 (0% 허용)
    if has_chinese(text):
        return False

    ratio = check_korean_ratio(text)
    return ratio >= min_korean_ratio

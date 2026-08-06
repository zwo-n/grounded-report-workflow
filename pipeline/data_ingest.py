"""
data_ingest.py - 제공 데이터 인제스트 모듈

Excel/CSV 파일 또는 비정형 텍스트를 chunk 리스트로 변환합니다.
각 chunk에는 섹션 매칭용 메타데이터(원본 출처, 주제어)가 포함됩니다.

중요:
- 이 모듈의 결과물은 실행 1회성이며, RAG 인덱스에 영구 저장되지 않습니다.
- source_type="provided_data"로 분류되어 기존 internal/web과 분리됩니다.
- 실행 종료 시 메모리에서 자동 폐기됩니다 (GC).

사용 예:
    from pipeline.data_ingest import ingest_tabular, filter_chunks_by_keywords

    # CSV 파일 인제스트
    chunks = ingest_tabular("data.csv")

    # 섹션 키워드로 필터링
    matched = filter_chunks_by_keywords(chunks, ["개발", "테스트"])
"""

import re
from pathlib import Path
from typing import TypedDict

import pandas as pd


class ProvidedChunk(TypedDict):
    """제공 데이터 chunk 타입"""

    content: str  # 본문 텍스트
    source_title: str  # 원본 파일명 또는 섹션명
    source_url: str  # "provided://<파일명>#row<N>" 형식
    topic_keywords: list[str]  # 주제어 리스트 (매칭용)
    score: float  # 기본 1.0 (제공 데이터는 항상 신뢰)


# 불용어 (보고서 문서에 흔한 범용 단어)
_STOPWORDS = {
    "내용",
    "결과",
    "진행",
    "완료",
    "예정",
    "관련",
    "대한",
    "위한",
    "통한",
    "작성",
    "확인",
    "검토",
    "필요",
    "사항",
    "기타",
    "비고",
    "담당",
    "담당자",
}


def _extract_keywords_from_text(text: str) -> list[str]:
    """
    텍스트에서 주제어를 추출합니다.
    web_search.py의 _extract_topic_keywords와 유사한 로직.

    Args:
        text: 원본 텍스트

    Returns:
        추출된 키워드 리스트 (2글자 이상 한글/영문)
    """
    if not text:
        return []

    # 한글/영문 단어 추출 (2글자 이상)
    words = re.findall(r"[가-힣a-zA-Z]{2,}", text)
    keywords = [w for w in words if w.lower() not in _STOPWORDS]

    # 중복 제거하면서 순서 유지
    seen: set[str] = set()
    unique_keywords: list[str] = []
    for kw in keywords:
        kw_lower = kw.lower()
        if kw_lower not in seen:
            seen.add(kw_lower)
            unique_keywords.append(kw)

    return unique_keywords[:10]  # 최대 10개


def ingest_tabular(
    file_path: str | Path,
    content_columns: list[str] | None = None,
    keyword_columns: list[str] | None = None,
) -> list[ProvidedChunk]:
    """
    Excel 또는 CSV 파일을 chunk 리스트로 변환합니다.

    Args:
        file_path: 파일 경로 (.xlsx, .xls, .csv)
        content_columns: 본문으로 사용할 컬럼 목록 (None이면 모든 컬럼)
        keyword_columns: 주제어 추출용 컬럼 (None이면 content_columns와 동일)

    Returns:
        ProvidedChunk 리스트

    Raises:
        ValueError: 지원하지 않는 파일 형식
        FileNotFoundError: 파일 없음
    """
    file_path = Path(file_path)

    if not file_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_path}")

    # 파일 읽기
    suffix = file_path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        df = pd.read_excel(file_path)
    elif suffix == ".csv":
        df = pd.read_csv(file_path, encoding="utf-8-sig")  # BOM 처리
    else:
        raise ValueError(f"지원하지 않는 파일 형식: {suffix}")

    # 컬럼 설정
    all_columns = df.columns.tolist()
    if content_columns is None:
        content_columns = all_columns
    if keyword_columns is None:
        keyword_columns = content_columns

    # 유효한 컬럼만 필터링
    content_columns = [c for c in content_columns if c in all_columns]
    keyword_columns = [c for c in keyword_columns if c in all_columns]

    if not content_columns:
        raise ValueError("유효한 content_columns가 없습니다")

    chunks: list[ProvidedChunk] = []

    for idx, row in df.iterrows():
        # 본문 생성 (모든 content_columns 결합)
        content_parts = []
        for col in content_columns:
            val = row[col]
            if pd.notna(val):
                content_parts.append(f"{col}: {val}")

        content = "\n".join(content_parts)

        if not content.strip():
            continue  # 빈 행 스킵

        # 주제어 추출
        keyword_text = " ".join(
            str(row[col]) for col in keyword_columns if pd.notna(row[col])
        )
        topic_keywords = _extract_keywords_from_text(keyword_text)

        chunks.append(
            {
                "content": content,
                "source_title": file_path.name,
                "source_url": f"provided://{file_path.name}#row{idx + 1}",
                "topic_keywords": topic_keywords,
                "score": 1.0,
            }
        )

    print(f"[data_ingest] {file_path.name}에서 {len(chunks)}개 chunk 생성")
    return chunks


def ingest_text(
    text: str,
    source_name: str = "제공 텍스트",
    chunk_separator: str = "\n\n",
) -> list[ProvidedChunk]:
    """
    비정형 텍스트를 chunk 리스트로 변환합니다.

    Args:
        text: 원본 텍스트
        source_name: 출처명 (예: "회의록")
        chunk_separator: 청크 분리 기준 (기본: 빈 줄)

    Returns:
        ProvidedChunk 리스트
    """
    if not text or not text.strip():
        return []

    # 청크 분리
    raw_chunks = text.split(chunk_separator)

    chunks: list[ProvidedChunk] = []

    for idx, raw in enumerate(raw_chunks, 1):
        content = raw.strip()
        if not content:
            continue

        topic_keywords = _extract_keywords_from_text(content)

        chunks.append(
            {
                "content": content,
                "source_title": source_name,
                "source_url": f"provided://{source_name}#chunk{idx}",
                "topic_keywords": topic_keywords,
                "score": 1.0,
            }
        )

    print(f"[data_ingest] {source_name}에서 {len(chunks)}개 chunk 생성")
    return chunks


def filter_chunks_by_keywords(
    chunks: list[ProvidedChunk],
    section_keywords: list[str],
    min_match: int = 1,
) -> list[ProvidedChunk]:
    """
    섹션 키워드와 매칭되는 chunk만 필터링합니다.

    Args:
        chunks: 전체 chunk 리스트
        section_keywords: 섹션의 주제 키워드 (섹션 title + query에서 추출)
        min_match: 최소 매칭 키워드 수 (기본 1)

    Returns:
        매칭된 chunk 리스트 (score 기준 정렬)
    """
    if not section_keywords:
        return chunks  # 키워드 없으면 전체 반환

    section_keywords_lower = [kw.lower() for kw in section_keywords]
    matched: list[ProvidedChunk] = []

    for chunk in chunks:
        chunk_keywords_lower = [kw.lower() for kw in chunk["topic_keywords"]]

        # 매칭 점수 계산 (부분 문자열 매칭 포함)
        match_count = sum(
            1
            for sk in section_keywords_lower
            if any(sk in ck or ck in sk for ck in chunk_keywords_lower)
        )

        if match_count >= min_match:
            # 매칭 점수를 score에 반영 (정렬용)
            scored_chunk: ProvidedChunk = {
                "content": chunk["content"],
                "source_title": chunk["source_title"],
                "source_url": chunk["source_url"],
                "topic_keywords": chunk["topic_keywords"],
                "score": match_count / len(section_keywords),
            }
            matched.append(scored_chunk)

    # 매칭 점수 내림차순 정렬
    matched.sort(key=lambda x: x["score"], reverse=True)

    return matched

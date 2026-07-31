"""
scripts/lang_guard_test.py

source_type="none" 섹션(서론/결론 등 검색 근거 없이 순수 생성하는 경우)에서
qwen2.5 모델의 중국어 이탈률을 실제 Ollama 호출로 측정하는 스크립트.

llm_writer.py의 SYSTEM_PROMPT_NONE 하네스를 그대로 사용하고,
llm_writer.has_chinese()로 이탈 여부를 판정한다.
few-shot 등 하네스 변경 전/후 비교를 위한 기준선(baseline) 측정용.

Note: 언어 검증 함수는 원래 pipeline/lang_guard.py에 있었으나
      pipeline/llm_writer.py로 통합되었다.

사용법:
    python scripts/lang_guard_test.py [N]
    N: 총 호출 횟수 (기본값 30)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from pipeline.llm_writer import generate_section_draft, has_chinese

# source_type="none" 섹션의 실제 사용 패턴(서론/결론/인사말/맺음말)을 반영한 질의 세트
QUERIES = [
    "보고서 서론을 작성해주세요.",
    "이 보고서의 목적에 대해 서론을 작성해주세요.",
    "보고서의 결론 부분을 작성해주세요.",
    "전체 내용을 요약하는 결론을 작성해주세요.",
    "보고서 도입부에 들어갈 인사말을 작성해주세요.",
    "본 보고서를 마무리하는 맺음말을 작성해주세요.",
]


def run(n: int) -> None:
    leaked_samples: list[tuple[int, str, str]] = []
    leak_count = 0
    durations: list[float] = []

    print(f"source_type=none 하네스 중국어 이탈률 측정 시작 (총 {n}회 호출)\n")

    total_start = time.time()
    for i in range(n):
        query = QUERIES[i % len(QUERIES)]
        start = time.time()
        result = generate_section_draft(
            section_query=query,
            sources=[],
            source_type="none",
        )
        elapsed = time.time() - start
        durations.append(elapsed)

        answer = result["answer"]
        leaked = has_chinese(answer)
        if leaked:
            leak_count += 1
            leaked_samples.append((i + 1, query, answer))

        status = "LEAK" if leaked else "ok"
        print(f"[{i + 1:2d}/{n}] {elapsed:5.1f}s  {status:4s}  {query}")

    total_elapsed = time.time() - total_start

    print("\n" + "=" * 60)
    print("결과 요약")
    print("=" * 60)
    print(f"총 호출 수      : {n}")
    print(f"중국어 이탈 횟수: {leak_count}")
    print(f"이탈률          : {leak_count / n * 100:.1f}%")
    print(f"총 실행 시간    : {total_elapsed:.1f}초")
    print(f"평균 호출 시간  : {sum(durations) / len(durations):.1f}초")

    if leaked_samples:
        print("\n이탈 응답 샘플:")
        for idx, query, answer in leaked_samples[:5]:
            print(f"\n  [{idx}] 질문: {query}")
            print(f"      응답: {answer[:200]}")
    else:
        print("\n이탈 응답 없음.")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 30
    run(n)

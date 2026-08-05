"""
두 가지 topic으로 파이프라인 실행 후 검증

- 부산 금정구 한달간 더운 날씨
- 2026년 상반기 국내 클라우드 보안 트렌드

검증 항목:
- 2024_프로젝트_이력.docx, 기술스택_정리본.docx가 참고자료에 등장하지 않아야 함
"""

import os
import sys
import zipfile
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_real_doc import run_real_pipeline

TOPICS = [
    "부산 금정구 한달간 더운 날씨",
    "2026년 상반기 국내 클라우드 보안 트렌드",
]

FORBIDDEN_SOURCES = ["2024_프로젝트_이력", "기술스택_정리본"]


def extract_docx_text(docx_path: str) -> str:
    """docx 파일에서 텍스트 추출 (unzip 후 document.xml 파싱)"""
    import re

    with zipfile.ZipFile(docx_path, 'r') as z:
        # word/document.xml 읽기
        with z.open('word/document.xml') as f:
            content = f.read().decode('utf-8')

    # XML 태그 제거
    text = re.sub(r'<[^>]+>', ' ', content)
    return text


def check_forbidden_sources(docx_path: str) -> list[str]:
    """금지된 출처가 포함되어 있는지 확인"""
    text = extract_docx_text(docx_path)
    found = []
    for source in FORBIDDEN_SOURCES:
        if source in text:
            found.append(source)
    return found


def main():
    print("=" * 70)
    print("  두 가지 topic으로 파이프라인 테스트")
    print("=" * 70)

    results = []

    for i, topic in enumerate(TOPICS, 1):
        print(f"\n{'='*70}")
        print(f"  [{i}/{len(TOPICS)}] Topic: {topic}")
        print("=" * 70)

        try:
            output_path = run_real_pipeline(
                user_request=f"{topic}에 대한 기술 보고서를 작성해줘",
                verbose=True,
            )

            # 금지된 출처 확인
            found = check_forbidden_sources(output_path)

            results.append({
                "topic": topic,
                "output": output_path,
                "forbidden_found": found,
                "success": len(found) == 0,
            })

            print(f"\n[검증] 출력 파일: {output_path}")
            print(f"[검증] 금지 출처 검색: {FORBIDDEN_SOURCES}")
            if found:
                print(f"[실패] 발견된 금지 출처: {found}")
            else:
                print(f"[통과] 금지 출처 없음")

        except Exception as e:
            print(f"[에러] {e}")
            results.append({
                "topic": topic,
                "output": None,
                "forbidden_found": [],
                "success": False,
                "error": str(e),
            })

    # 최종 결과 출력
    print("\n" + "=" * 70)
    print("  최종 검증 결과")
    print("=" * 70)

    all_passed = True
    for r in results:
        status = "PASS" if r["success"] else "FAIL"
        print(f"\n[{status}] {r['topic']}")
        if r.get("output"):
            print(f"       파일: {r['output']}")
        if r.get("forbidden_found"):
            print(f"       금지출처: {r['forbidden_found']}")
        if r.get("error"):
            print(f"       에러: {r['error']}")
        if not r["success"]:
            all_passed = False

    print("\n" + "=" * 70)
    if all_passed:
        print("  모든 테스트 통과")
    else:
        print("  일부 테스트 실패")
    print("=" * 70)


if __name__ == "__main__":
    main()

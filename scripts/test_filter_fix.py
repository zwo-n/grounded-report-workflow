"""
필터 수정 검증 테스트

두 가지 다른 topic으로 실행하여:
1. 2024_프로젝트_이력.docx/기술스택_정리본.docx 근거 없이 인용되지 않는지
2. 결론이 topic과 일치하는지
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pipeline.rag_tool import search_internal_knowledge
from pipeline.web_search import search_web, _extract_topic_keywords
from pipeline.llm_writer import generate_section_draft

print("=" * 70)
print("  필터 수정 검증 테스트")
print("=" * 70)

# 테스트 1: RAG threshold 테스트
print("\n[테스트 1] RAG threshold 필터링")
print("-" * 50)

# 현재 mock 데이터는 고정 score이므로, threshold를 높여서 필터링 테스트
print("min_score=0.7 (기본값):")
results = search_internal_knowledge("AWS 기술 역량", min_score=0.7)
print(f"  결과 수: {len(results['results'])}")
for r in results["results"]:
    print(f"    - {r['source_title']} (score: {r['score']})")

print("\nmin_score=0.96 (높은 threshold):")
results = search_internal_knowledge("AWS 기술 역량", min_score=0.96)
print(f"  결과 수: {len(results['results'])}")
if not results["results"]:
    print("  → 관련 문서 없음 처리 OK")

# 테스트 2: 웹서치 topic 키워드 추출 테스트
print("\n[테스트 2] topic 키워드 추출")
print("-" * 50)

topics = [
    "클라우드 비용 최적화 제안서",
    "AI 챗봇 도입 기술 보고서",
    "2026년 클라우드 보안 트렌드 분석",
]

for topic in topics:
    keywords = _extract_topic_keywords(topic)
    print(f"  '{topic}' → {keywords}")

# 테스트 3: 결론 생성 - topic 주입 테스트
print("\n[테스트 3] 결론 생성 (topic 주입)")
print("-" * 50)

test_cases = [
    {
        "topic": "클라우드 비용 최적화 제안서",
        "query": "결론을 작성해주세요",
        "summary": "- 현황: 월 클라우드 비용 1억원 지출\n- 제안: 리소스 최적화 및 예약 인스턴스 도입\n- 기대효과: 30% 비용 절감",
    },
    {
        "topic": "AI 챗봇 도입 기술 보고서",
        "query": "결론을 작성해주세요",
        "summary": "- 현황: 고객 문의 응대 시간 평균 5분\n- 제안: GPT 기반 챗봇 도입\n- 기대효과: 응대 시간 80% 단축",
    },
]

for i, tc in enumerate(test_cases, 1):
    print(f"\n[케이스 {i}] topic: {tc['topic']}")
    result = generate_section_draft(
        section_query=tc["query"],
        sources=[],
        source_type="none",
        topic=tc["topic"],
        previous_sections_summary=tc["summary"],
    )
    answer = result["answer"]
    print(f"  생성된 결론 (첫 150자):")
    print(f"  {answer[:150]}...")

    # topic 키워드가 결론에 포함되어 있는지 확인
    keywords = _extract_topic_keywords(tc["topic"])
    found = [k for k in keywords if k.lower() in answer.lower()]
    print(f"  topic 키워드 포함 여부: {found}")

# 테스트 4: 웹서치 topic 필터링 테스트 (mock 모드)
print("\n[테스트 4] 웹서치 topic 필터링 (MOCK 모드)")
print("-" * 50)
os.environ["USE_MOCK_SEARCH"] = "true"

topics = ["클라우드 비용", "AI 챗봇"]
for topic in topics:
    print(f"\ntopic: {topic}")
    results = search_web(f"{topic} 도입 사례", topic=topic)
    print(f"  결과 수: {len(results['results'])}")
    for r in results["results"]:
        print(f"    - {r['source_title'][:50]}...")

print("\n" + "=" * 70)
print("  테스트 완료")
print("=" * 70)

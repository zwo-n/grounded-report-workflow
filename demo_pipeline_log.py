"""
파이프라인 로깅 데모 실행 스크립트

사용법:
    python demo_pipeline_log.py
    python demo_pipeline_log.py --error   # 에러 케이스 포함
"""
import sys
import time
from pipeline.pipeline_logger import PipelineContext, log_step, print_summary
from pipeline.router import Route

def run_demo(include_error=False):
    ctx = PipelineContext("grounded_report", stream_to_console=False)

    @log_step(ctx, "섹션 계획 생성")
    def plan_sections(request):
        time.sleep(0.12)
        return [
            {"title": "요약", "query": "핵심 내용"},
            {"title": "현황 분석", "query": "비용 구조"},
            {"title": "개선 방안", "query": "절감 방안"},
        ]

    @log_step(ctx, "문서 초기화")
    def create_document(title, author):
        time.sleep(0.05)
        return {"title": title, "author": author}

    @log_step(ctx, "소스 분류")
    def classify(query):
        time.sleep(0.06)
        return "internal"

    @log_step(ctx, "RAG 검색")
    def search_rag(query):
        time.sleep(0.15)
        return [{"title": "내부문서", "score": 0.92}]

    @log_step(ctx, "LLM 생성")
    def generate(query, sources):
        time.sleep(0.2)
        return {"answer": "비용 30% 절감 가능...", "source_count": len(sources)}

    @log_step(ctx, "섹션 추가")
    def add_section(doc, title, content):
        time.sleep(0.03)
        return True

    @log_step(ctx, "문서 저장")
    def save(doc, path):
        time.sleep(0.08)
        return path

    @log_step(ctx, "PDF 변환")
    def convert_pdf(path):
        time.sleep(0.05)
        if include_error:
            raise RuntimeError("LibreOffice 타임아웃")
        return path.replace(".docx", ".pdf")

    # 실행
    print("=" * 60)
    print("  Grounded Report Pipeline")
    print("=" * 60 + "\n")

    try:
        sections = plan_sections("클라우드 비용 최적화 제안서")
        doc = create_document("제안서", "홍길동")

        for sec in sections:
            classify(sec["query"])
            sources = search_rag(sec["query"])
            result = generate(sec["query"], sources)
            add_section(doc, sec["title"], result["answer"])

        path = save(doc, "output/report.docx")
        convert_pdf(path)

    except Exception as e:
        print(f"[에러] {e}\n")

    print_summary(ctx, detailed=False)


if __name__ == "__main__":
    include_error = "--error" in sys.argv
    run_demo(include_error)

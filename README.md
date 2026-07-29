# grounded-report-workflow
 
계획서/보고서 작성을 위한 LLM 활용 워크플로우.
근거 문서(사내 RAG, 웹 검색)를 tool로 호출하여 섹션별 초안을 생성하고, 근거 신뢰도에 따라 자동 승인/검토 필요를 라우팅한다.
 
## 핵심 원칙
 
- 검색된 문서 밖 내용은 지어내지 않는다 (fabrication 금지)
- 모든 생성 문단에는 출처를 명시한다 (사내 문서 링크 또는 웹 URL)
- 근거가 부족한 섹션은 자동 생성을 생략하고 사람 검토로 넘긴다
## 파이프라인
 
1. 섹션 주제를 보고 LLM이 근거 필요 여부 및 tool(사내 RAG / 웹 검색) 선택을 판단
2. 사내 RAG 우선 호출 → 근거 부족 시 웹 검색으로 폴백
3. LLM이 구조화된 JSON(`answer`, `source_type`, `source_count`, `source_relevance`, `has_fabrication_risk`)으로 응답
4. 코드가 라우팅 결정 (자동 승인 / 검토 필요) — LLM은 라우팅에 관여하지 않음
5. 결과를 docx에 삽입 (출처 인라인 표기 + 참고문서 목록)
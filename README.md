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

## 실행 방법

### 1. Ollama 설치

```bash
# macOS
brew install ollama

# Linux
curl -fsSL https://ollama.com/install.sh | sh
```

### 2. Ollama 서버 실행

```bash
ollama serve
```

### 3. 모델 다운로드

```bash
ollama pull qwen2.5:7b-instruct-q4_0
```

### 4. Python 의존성 설치

```bash
pip install -r requirements.txt
```

### 5. 파이프라인 실행

```bash
python -m pipeline.main
```

실행 결과로 `output.docx` 파일이 생성됩니다.

## 프로젝트 구조

```
pipeline/
├── main.py           # 파이프라인 조립 및 실행
├── rag_tool.py       # 사내 RAG 검색 (목업)
├── web_search.py     # 웹 검색 (목업)
├── llm_writer.py     # Ollama LLM 호출 및 초안 생성
├── lang_guard.py     # 응답 언어 검증 (한글 비율, 중국어 감지)
├── router.py         # 승인 라우팅 결정
└── docx_builder.py   # Word 문서 생성

tests/
├── test_lang_guard.py
└── test_router.py
```

## 라우팅 규칙

| source_type | source_relevance | has_fabrication_risk | 결과 |
|-------------|------------------|----------------------|------|
| none | - | - | 자동 승인 |
| internal | high | false | 자동 승인 |
| web | high/medium | false | 자동 승인 |
| 그 외 | - | - | 검토 필요 |

## 언어 검증 (하네스 + lang_guard)

qwen2.5 모델은 약 20% 확률로 한국어 응답 중 중국어로 전환되는 현상이 있습니다. 2단계로 방어합니다.

1. **프롬프트 하네스 (1차, 사전 제어)**: `llm_writer.py`의 시스템 프롬프트에 "반드시 한국어로만 응답" 규칙과 few-shot 예시를 명시하여, 모델이 처음부터 언어를 이탈하지 않도록 유도합니다.
2. **lang_guard (2차, 사후 검증 fallback)**: 하네스를 우회한 잔여 케이스를 감지합니다.
   - **한글 비율 체크**: 50% 이상 유지 (기술 용어 포함 시에도 통과)
   - **중국어 감지**: 중국어가 한 글자라도 포함되면 즉시 차단 (0% 허용)
   - 언어 이탈 감지 시 `has_fabrication_risk=True`로 설정되어 검토 필요로 라우팅

## 테스트 실행

```bash
python -m pytest tests/ -v
```

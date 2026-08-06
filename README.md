# Grounded Report Workflow

> LLM 기반 보고서 자동 생성 시스템
> Slack 명령어로 CSV 데이터를 기반으로 Word 문서를 자동 생성.

---

## 1. 프로젝트 개요

### 1.1 목적
- CSV 형식의 활동 데이터를 입력받아 정형화된 Word 보고서 자동 생성
- Slack 봇을 통한 간편한 보고서 요청 및 수신
- 근거 기반 작성으로 허위 내용(fabrication) 방지

### 1.2 핵심 원칙
- 검색된 문서 밖 내용은 생성하지 않음
- 모든 생성 문단에 출처 명시 (제공 데이터 또는 웹 URL)
- 근거 부족 섹션은 자동 생성 생략, 사람 검토로 전환

### 1.3 주요 기능
| 기능 | 설명 |
|------|------|
| CSV 데이터 인제스트 | Slack에 첨부된 CSV 파일 자동 파싱 |
| 템플릿 기반 문서 생성 | 보고서 템플릿에 내용 채워넣기 기능 지원 |
| 섹션별 LLM 작성 | 개요, 주요내용, 결론 및 제언 자동 생성 |
| 웹 검색 보강 | 필요한  섹션에 따라 웹 검색을 통한 트렌드/인사이트 추가 |
| Word 문서 출력 | 로고, 서식, 참고자료 자동 삽입 |

---

## 2. 시스템 아키텍처

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   Slack     │────▶│  slack_app  │────▶│  pipeline/  │
│  (사용자)    │     │             │     │   main.py   │
└─────────────┘     └─────────────┘     └─────────────┘
                                              │
                    ┌─────────────────────────┼─────────────────────────┐
                    ▼                         ▼                         ▼
             ┌─────────────┐          ┌─────────────┐          ┌─────────────┐
             │ data_ingest │          │ llm_writer  │          │ web_search  │
             │ (CSV 파싱)   │          │ (Groq API)  │          │(Tavily/Naver)│
             └─────────────┘          └─────────────┘          └─────────────┘
                                                                      │
                                                                      ▼
                                                               ┌─────────────┐
                                                               │ docx_builder│
                                                               │ (Word 생성) │
                                                               └─────────────┘
```

---

## 3. 환경 설정

### 3.1 필수 요구사항
- Python 3.11+
- Groq API 키
- Slack Bot/App 토큰
- Tavily API 키 (글로벌 웹 검색용)
- Naver Search API 키 (국내 웹 검색용)

### 3.2 의존성 설치

```bash
pip install -r requirements.txt
```

### 3.3 환경 변수 설정 (.env)

```env
# Groq LLM API
GROQ_API_KEY="gsk_xxxxx"

# Slack 봇 토큰
SLACK_BOT_TOKEN="xoxb-xxxxx"
SLACK_APP_TOKEN="xapp-xxxxx"

# 웹 검색 API
TAVILY_API_KEY="tvly-xxxxx"
NAVER_CLIENT_ID="xxxxx"
NAVER_CLIENT_SECRET="xxxxx"

# 옵션: Mock 검색 모드 (API 크레딧 절약)
USE_MOCK_SEARCH=false
```

---

## 4. 실행 방법

### 4.1 Slack 봇 실행

```bash
# 포그라운드 실행
python slack_app.py

# 백그라운드 실행 (권장)
nohup python slack_app.py >> slack_app.log 2>&1 &
```

### 4.2 Slack 명령어

#### 일반 모드 (웹 검색 기반)
```
/report [요청 내용]
```

**사용 예시:**
```
/report AWS 클라우드 비용 최적화 방안에 대한 기술 보고서를 작성해줘
```
- 웹 검색(Tavily, Naver)을 통해 정보를 수집하여 보고서 자동 생성
- CSV 파일 불필요

#### 템플릿 모드 (CSV 데이터 기반)
```
/report [보고서 제목] --template [템플릿명]
```

**사용 예시:**
1. Slack 채널에서 CSV 파일 첨부
2. 메시지에 명령어 입력:
   ```
   /report 7월 활동 보고서 --template gambarlabs_report
   ```
3. 봇이 Word 문서 생성 후 채널에 업로드

- 내부 정의된 템플릿에 CSV 데이터를 기반으로 내용 채워넣기
- 제공된 데이터 외 내용은 생성하지 않음 (근거 기반)

### 4.3 지원 템플릿

| 템플릿명 | 설명 | 섹션 구성 |
|---------|------|----------|
| `gambarlabs_report` | 감바랩스 활동 보고서 | 개요, 주요내용, 결론및제언 |
| `제안서` | 일반 제안서 | 서론, 현황분석, 제안내용, 기대효과, 실행계획, 결론 |
| `기술 보고서` | 기술 문서 | 서론, 기술개요, 상세분석, 적용사례, 결론 |

### 4.4 직접 파이프라인 실행 (개발/테스트용)

```bash
python -c "
from pipeline.data_ingest import ingest_tabular
from pipeline.main import run_pipeline

chunks = ingest_tabular('assets/mock_provided_data.csv')
run_pipeline('7월 활동 보고서', template_hint='gambarlabs_report', provided_chunks=chunks)
"
```

---

## 5. 프로젝트 구조

```
grounded-report-workflow/
├── slack_app.py              # Slack 봇 메인 (Socket Mode)
├── .env                      # 환경 변수 (API 키 등)
├── requirements.txt          # Python 의존성
│
├── pipeline/                 # 핵심 파이프라인 모듈
│   ├── main.py               # 파이프라인 조립 및 실행
│   ├── data_ingest.py        # CSV/엑셀 데이터 인제스트
│   ├── section_planner.py    # 섹션 계획 생성
│   ├── classifier.py         # 소스 타입 분류
│   ├── llm_writer.py         # LLM 초안 생성 (Groq API)
│   ├── web_search.py         # 웹 검색 (Tavily + Naver)
│   ├── router.py             # 승인 라우팅 결정
│   ├── docx_builder.py       # Word 문서 생성
│   └── templates.py          # 문서 템플릿 정의
│
├── assets/                   # 정적 자산
│   ├── gambarlabs_report_template.docx  # 보고서 템플릿
│   ├── gambalabs-logo.png    # 로고 이미지
│   └── mock_provided_data.csv # 테스트용 샘플 데이터
│
├── output/                   # 생성된 문서 출력 폴더
│
├── scripts/                  # 유틸리티 스크립트
│   └── groq_model_comparison.py
│
└── tests/                    # 테스트
    ├── test_lang_guard.py
    └── test_router.py
```

---

## 6. 핵심 모듈 설명

### 6.1 slack_app.py
- Slack Socket Mode로 실시간 이벤트 수신
- `/report` 명령어 처리
- CSV 파일 다운로드 및 파이프라인 호출
- 생성된 문서 Slack 채널에 업로드

### 6.2 pipeline/main.py
- 전체 파이프라인 오케스트레이션
- 템플릿 모드 vs 일반 모드 분기
- 섹션별 LLM 호출 및 문서 조립
- 로고 삽입, 글자색 통일 등 후처리

### 6.3 pipeline/llm_writer.py
- Groq API를 통한 LLM 호출
- 모델: `openai/gpt-oss-20b`
- 구조화된 JSON 응답 생성

### 6.4 pipeline/docx_builder.py
- python-docx 기반 Word 문서 생성
- 템플릿 플레이스홀더 치환
- 서식 적용 (폰트, 색상, 정렬 등)

---

## 7. 라우팅 규칙

| source_type | source_relevance | has_fabrication_risk | 결과 |
|-------------|------------------|----------------------|------|
| none | - | - | 자동 승인 |
| provided_data | - | false | 자동 승인 |
| internal | high | false | 자동 승인 |
| web | high/medium | false | 자동 승인 |
| 그 외 | - | - | 검토 필요 |

---

## 8. 트러블슈팅

### 8.1 Rate Limit 에러 (429)
```
Rate limit reached for model `openai/gpt-oss-20b`
```
**원인:** Groq API 일일 토큰 한도 초과 (200,000 토큰/일)
**해결:**
- 표시된 시간만큼 대기 후 재시도
- 다른 Groq 계정의 API 키 사용

### 8.2 Slack 파일 다운로드 실패
**원인:** Bot에 `files:read` 권한 없음
**해결:** Slack App 설정에서 OAuth Scopes에 `files:read` 추가

### 8.3 문서 생성 후 빈 섹션
**원인:** CSV 데이터와 섹션 키워드 불일치
**해결:**
- CSV 컬럼명 확인 (날짜, 구분, 활동내용 등)
- `templates.py`의 `match_keywords` 확인

---

## 9. 설정 변경

### 9.1 LLM 모델 변경
`pipeline/` 폴더 내 4개 파일에서 `MODEL_NAME` 수정:
- `section_planner.py`
- `classifier.py`
- `llm_writer.py`
- `web_search.py`

### 9.2 템플릿 추가
`pipeline/templates.py`의 `TEMPLATES` 딕셔너리에 새 템플릿 추가

### 9.3 로고 변경
`assets/gambalabs-logo.png` 파일 교체

---

## 10. 테스트

```bash
# 전체 테스트 실행
python -m pytest tests/ -v

# 특정 테스트 실행
python -m pytest tests/test_router.py -v
```

---

## 11. 참고 사항

### 11.1 API 사용량
- **Groq:** 무료 티어 200,000 토큰/일
- **Tavily:** 무료 티어 1,000 검색/월
- **Naver Search:** 무료 25,000 요청/일

### 11.2 로그 확인
```bash
# 실시간 로그 확인
tail -f slack_app.log

# 최근 에러 확인
grep -i error slack_app.log | tail -20
```

---

## 12. 변경 이력

| 날짜 | 버전 | 변경 내용 |
|------|------|----------|
| 2026-08-06 | 1.0 | 초기 핸드오버 문서 작성 |

---

*본 문서는 프로젝트 핸드오버를 위해 작성되었습니다.*

# 설계 결정 기록 (v1.0)

이 문서는 `japanese-learning` 프로젝트에서 내린 설계 결정과 그 이유를 기록합니다.

## 1. 프로젝트 개요

- 이름: Japanese Learning
- 목적: 로컬 우선 일본어 단어 학습 도구. 공통 영어 JMdict 데이터셋을 SQLite로 import하고, 검색·학습하는 로컬 우선 도구.
- 범위: 사전 임포트 + CLI 검색 + 로컬 웹 단어장 + 학습 자료 임포트 + 복습 연습 (단어 플래시카드·단어 입력·문장 입력·일본어 보고 입력·대화 입력)

## 2. 데이터 소스 및 가져오기 결정

### 2.1 JMdict (사전)
- **선택**: `scriptin/jmdict-simplified`의 `jmdict-eng-common` JSON 아카이브.
- **이유**: 영어 초급자 친화적 JSON 변환. EDRDG 라이선스(CC BY-SA 4.0) 유지. 시작 단계에 적합한 common-only 데이터.
- **버전 관리**: `DATA_VERSION`, `ARCHIVE_URL`, `ARCHIVE_SHA256`을 `src/japanese_learning.py`에 고정. 업데이트 시 세 항목을 함께 수정.
- **검증**: SHA-256 체크섬 비교. 불일치 시 아카이브 삭제 후 재다운로드.

### 2.2 학습 자료 (learning materials)
- **선택**: Tatoeba, KFTT, BSD, OpenJLPT.
- **이유**: 각각 서로 다른 라이선스와 특성을 보유.
  - Tatoeba: 커뮤니티 기여, CC BY 2.0 FR / CC0 1.0 (문장별)
  - KFTT: 위키백과 교토 문서, CC BY-SA 3.0
  - BSD: 비즈니스 시나리오, CC BY-NC-SA
  - OpenJLPT: 문법·어휘 예문, CC BY-SA 4.0
- **사유**: 소스 분리 및 라이선스 투명성 유지. `source_manifest` 테이블에 소스별 버전·라이선스·저작자 기록.

## 3. 아키텍처 결정

### 3.1 CLI 중심 + 로컬 웹 앱
- **CLI** (`src/japanese_learning.py`): `import-dictionary`, `search` 서브커맨드. 가볍고 스크립트 중심.
- **웹 앱** (`src/web_app.py`): `ThreadingHTTPServer` 기반. `127.0.0.1:8000`에 바인드. 개인 로컬 사용 전용.
- **이유**: 서버 의존성 최소화. `uv run python src/web_app.py`로 바로 실행 가능.

### 3.2 학습 데이터베이스 분리
- `data/reference/jmdict.sqlite3`: 사전 데이터 (읽기 전용, Git 제외)
- `data/reference/learning_materials.sqlite3`: 학습 자료 (읽기 전용, Git 제외)
- `data/private/study.sqlite3`: 개인 학습 진도 (Git 제외)
- **이유**: 사전 데이터와 개인 학습 기록을 물리적으로 분리. 공개 저장소에 개인 학습 기록이 섞이지 않도록 함.

## 4. Python 및 라이브러리 규칙

### 4.1 Python 3.13 + `uv` 고정
- **이유**: Personal Dev Kit 확정 기준. `uv`로 환경과 의존성 관리. 직접 `pip` 사용 금지.
- **영향**: `.python-version`과 `pyproject.toml`의 요구 버전을 일치시킴.

### 4.2 Ruff (`E4`, `E7`, `E9`, `F`, `I`, `UP`, `B`)
- **이유**: Personal Dev Kit의 Python 규칙 준수. formatter는 큰따옴표, 공백 4칸, 줄 길이 88.
- **예외**: `E501`(줄 길이 위반)은 기본 강제하지 않음. 긴 주석이나 문자열을 이유로 나누는 일을 줄이기 위함.

## 5. 학습 시스템 설계

### 5.1 학습 항목 분류
- `word`: 사전 단어 (kanji, kana, senses)
- `material`: 학습 자료 (Tatoeba 문장, KFTT, BSD, OpenJLPT 등)
- **이유**: 사전 단어와 학습 자료를 동일한 스터디 큐에서 관리하되, 데이터 소스 구분.

### 5.2 학습 모드
- `word_flashcard`, `word_typing`, `sentence_typing`, `japanese_copy_typing`, `dialogue_typing`
- **이유**: 단일 아이템에 여러 학습 모드를 적용해 회상·번역·베끼기·대화 맥락 등 다양한 학습 모드를 제공.

### 5.3 간격 복습 (Spaced Review)
- **방식**: `study_reviews` 테이블에 `interval_days`, `repetitions`, `lapses` 저장.
- **평가**: `again`(10분 후), `hard`(1.2배), `good`(2배), `easy`(2.5배).
- **이유**: 간격 반복 알고리즘(SRS)으로 장기 기억 강화.
- **구현**: 간격 계산은 `next_interval()` 순수 함수로 분리해 `tests/test_study_logic.py`에서 검증.

### 5.4 단어 JLPT 필터 제거
- **결정**: 단어 화면의 JLPT N5~N1 선택지를 제거하고, 품사 필터만 남김.
- **이유**: JMdict 스냅샷에 단어 등급 필드가 없어 선택 시 항상 0건이 나오는 함정이었음. 자료 화면의 OpenJLPT 단계만 별도로 유지.

### 5.5 품사 필터와 페이지네이션
- **결정**: 품사 필터를 LIMIT 이후 파이썬 필터가 아니라 SQLite `json_each` 조건으로 적용.
- **이유**: 기존 방식은 첫 페이지가 비고 `total`·`has_more`가 실제 결과와 어긋났음. 현재는 필터된 결과 기준으로 개수와 다음 페이지를 계산.

### 5.6 자료 검색 trigram FTS5
- **결정**: `learning_items`에 외부 콘텐츠 FTS5(`tokenize='trigram'`) 인덱스를 두고 3자 이상 질의에 사용. 2자 이하(`猫`, `京都`)는 LIKE로 폴백.
- **이유**: LIKE 전체 스캔은 매치 없는 일본어 질의에서 약 1초. trigram은 부분 문자열을 지원해 0.01초대로 줄지만 trie 특성상 3자 미만은 매치하지 못함.
- **비용**: 인덱스 +약 470MB, 최초 빌드 약 30초. 임포트 시 자동 생성, 기존 DB는 `--rebuild-search-index`.
- **대안 기각**: 기본 unicode61 토크나이저는 공백 없는 일본어를 문장 단위 토큰으로 처리해 부분 검색이 안 됨.

### 5.7 저장 단어 정렬
- **결정**: `/api/saved?sort=recent|kana|due`. 정렬 SQL은 화이트리스트 딕셔너리에서만 선택.
- **이유**: 저장이 늘면 저장일 순서만으로는 찾기 어려움. `due`는 스킬별 복습 예정 중 가장 이른 시각을 쓰고, 아직 복습하지 않은 항목을 먼저 보여줌.
- **안전성**: 문자열 보간 대신 고정 SQL 조각만 사용해 주입 여지를 없앰.

### 5.8 학습 통계와 `study_answers` 기록 중단
- **결정**: `study_log`(append-only: 항목·모드·평가·시각)를 추가하고 `study_answers` 쓰기를 중단. 기존 행은 보존하며 삭제하지 않음.
- **이유**: `study_answers`는 화면에 쓰이지 않고 원문 입력만 중복 저장. 연속일 계산에는 시각이 있는 이력이 필요했음.
- **연속일**: 로그와 기존 `study_reviews.reviewed_at`의 로컬 날짜를 합집합으로 계산. 오늘 기록이 없어도 어제까지 이어졌으면 유지.

### 5.9 학습 DB 내보내기
- **결정**: `GET /api/export`가 `iterdump()` 결과를 `kotoba-note-YYYY-MM-DD.sql`로 다운로드.
- **이유**: 개인 기록 백업·이전 수단이 없었음. SQL 덤프는 텍스트라 확인·복원이 쉽고 바이너리 스냅샷 파일 관리가 필요 없음.
- **주의**: 개인 데이터이므로 Git·공유 저장소에 두지 않음(README에 명시).

### 5.10 스킬 단위 복습과 세션 상한
- **결정**: `study_reviews` 기본키를 `(item_type,item_id,mode)`에서 `(item_type,item_id,skill)`로 마이그레이션. 모드→스킬: 플래시카드=인식, 단어 입력=재생, 문장·대화 입력=산출, 보고 입력=필사.
- **이유**: 같은 단어를 플래시카드와 입력으로 따로 스케줄하면 하루에 두 번 복습하게 됨. 대화 입력과 문장 입력은 같은 산출 스킬이라 한 일정을 공유해야 함.
- **세션 규칙**: 하루 복습 80개·신규 15개 상한, 같은 항목은 하루 한 번만, 실수(`lapses`)가 많은 항목 우선, 7일 예정 개수 표시. `study_log`에 `skill`·`correct`를 추가해 스킬별 유지율을 계산.
- **마이그레이션**: 기존 5행을 스킬 행으로 변환해 보존(중복 키는 `INSERT OR IGNORE`). 변환 전 `data/private/study.backup-*.sqlite3` 백업.

### 5.11 읽기 분절: 사전 최장일치 → Janome
- **최초 결정**: 의존성 없는 사전 최장일치. 조사·활용 분리는 포기하고 조회용으로 충분하다고 판단.
- **번복 근거**: 실제 출력이 `会いましょう` → `会 / いま / しょう`, `かかってきた` → `がか / かって / きた`처럼 활용형에서 경계가 틀렸고, 화면에 잘못된 단어 버튼이 노출됨. "조회에는 충분" 가정이 틀렸음.
- **현재**: Janome(형태소 분석, Apache 2.0)로 분절하고 `base_form`을 JMdict 표제어로 조회. `会い` → `会う`로 연결. 설치 용량 약 137MB.
- **대안 기각**: 규칙 기반 활용 복원(deinflection)은 동사 활용·수동·사역을 모두 다뤄야 해서 Janome보다 코드가 커짐.

### 5.12 TTS와 피치악센트
- **결정**: macOS `say -v Kyoko` → `afconvert` WAV를 `data/private/audio/`에 해시 캐시. 피치는 Kanjium `accents.txt`를 커밋·SHA-256 고정으로 받아 `kanjium.sqlite3`에 저장.
- **이유**: 오디오 원본을 저장소에 넣지 않으면서 로컬 발음 연습을 제공. 피치는 사전 데이터(CC BY-SA 4.0)라 재배포 시 출처 표기가 필요.
- **한계**: macOS 전용. 자동 발음 평가는 없음. 피치 숫자는 참고값이며 청취 연습을 대체하지 않음.

### 5.13 JLPT 어휘 드릴
- **결정**: OpenJLPT 아카이브의 `vocab/n*.json`만 별도 `jlpt_vocab.sqlite3`(7,811단어)로 추출. 기존 866MB 자료 DB는 재임포트하지 않음.
- **이유**: OpenJLPT 어휘에는 이미 `jmdict_id`·뜻·예문이 있어 JMdict와 연결 가능. 대용량 DB 재빌드 없이 단계별 드릴을 제공할 수 있음.
- **주의**: N5–N1은 커뮤니티 추정 등급이며 공식 JLPT 목록이 아님.

## 6. 보안 및 데이터 제외

- `data/downloads/`, `data/reference/`, `data/private/`는 `.gitignore`에 등록.
- 개인 학습 DB(`data/private/study.sqlite3`)는 절대 Git에 커밋하지 않음.
- 공개 저장소에는 임포터, 스키마, 소스/라이선스 정보만 포함.

## 7. 미결정 사항
- [x] 문장 난이도별 필터링 (JLPT N5~N1) — OpenJLPT 단계가 있는 문장만
- [x] 문장 길이 필터 — 읽기 화면 20~80자
- [x] 음성 합성(TTS) — macOS `say` + WAV 캐시 (원본 미보관)
- [ ] FSRS 전환 — 로그 200건 이후 재검토
- [ ] 사용자 정의 사전 번역(한국어 의미) 추가

**작성일**: 2026-10-09 (2026-10-23 보완)  
**작성자**: 사용자 + AI
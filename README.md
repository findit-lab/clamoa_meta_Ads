# Clamoa 경쟁 광고 인텔리전스 (v2 스캐폴드)

경쟁사 Meta 광고를 매일 관측해 **① Diff 이벤트(longevity) · ② 컨셉 클러스터링 · ③ LLM-last 선별 태깅**의
세 핵심 시그널을 산출하는 파이프라인. 기획서 `clamoa_ad_intel_production_plan_v2.md` 구현체.

> ⚠️ 산출물은 **가설 생성기**다. 실제 성과(ROAS/CTR)는 측정하지 않으며 카피 자동생성도 하지 않는다(기획서 §0).

## 아키텍처 (기획서 §4 매핑)

| 컴포넌트 | 위치 | 역할 |
|---|---|---|
| C1 타겟 레지스트리 | `src/adintel/targets.py` | 경쟁사 page_id 관리 |
| C2 수집기 | `src/adintel/collectors/` | `base`(인터페이스)·`mock`(합성)·`apify`(실) |
| **C3 Diff 엔진 ★** | `src/adintel/diff.py` | APPEARED/DISAPPEARED + `observed_active_days` |
| **C4 클러스터 ★** | `src/adintel/embedding/` | `phash`(근접중복)·`cluster`(컨셉 묶기) |
| **C5 비전 태깅 ★** | `src/adintel/tagging/vision.py` | Claude Vision(Sonnet 4.6) + mock 폴백 |
| C6 패턴 분석 | `src/adintel/analysis/patterns.py` | 컨셉×longevity lift |
| C7 리포트 | `src/adintel/reporting/` | `notion`·`slack` (키 있을 때 실전송) |
| 오케스트레이션 | `src/adintel/pipeline.py` | 일일 collect→diff→phash→cluster |

데이터: 로컬 **SQLite** (`data/adintel.db`) + 로컬 미디어 (`data/media/`). 기획서 BigQuery/GCS 스키마를 1:1 미러링.

## 빠른 시작

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/seed_targets.py            # ① 타겟 10곳 시드
python scripts/simulate_days.py --days 30 # ② mock 30일 전진 → Diff/longevity 시연
pytest tests/                             # ③ 핵심 로직 검증
python scripts/run_weekly.py --dry-run    # ④ 태깅+분석+리포트(콘솔 미리보기)
```

`.env` 설정(선택): `cp .env.example .env` 후 키 입력
- `ANTHROPIC_API_KEY` → C5가 실제 Claude Vision 태깅 사용 (없으면 결정적 mock)
- `APIFY_TOKEN` → C2가 실제 Apify 수집 사용 (없으면 mock)
- `NOTION_TOKEN`+`NOTION_DATABASE_ID`, `NOTION_ADS_DATABASE_ID`, `SLACK_WEBHOOK_URL` → C7 실전송
- `OPENAI_API_KEY` → Notion 제작요청(`제작상태=생성요청`) 기반 GPT Image 소재 생성

## 성공 기준 (기획서 §10)

- **2주차 게이트(가장 중요)**: 30일 시뮬레이션에서 종료 광고의 `observed_active_days`가 산출됨 → `simulate_days.py` 출력 확인.
- **3주차 게이트**: 컨셉 클러스터가 "같은 컨셉 다른 픽셀"을 묶고 위너 컨셉이 face validity 있게 나옴.
- **운영 게이트**: `run_weekly.py` 한 번으로 주간 리포트 생성.

## 운영 배치 (추후)

`run_daily.py`를 Cloud Scheduler로 매일, `run_weekly.py`를 주 1회 트리거. 초기엔 주 2회 수집 → 가설 검증 후 매일로 상향(기획서 §8 비용 모델).

## 광고 소재 제작 자동화

```bash
python3 scripts/audit_media.py --all                 # DB/export 미디어링크·타입 검증
python3 scripts/process_creative_requests.py --dry-run
python3 scripts/process_creative_requests.py --limit 5
```

노션 광고 추적 DB에서 `제작상태`를 `생성요청`으로 바꾸면 워커가 `미디어타입=image`
행만 처리한다. 생성 결과는 `data/generated/`에 저장되고 Notion `생성결과` 파일 속성에
첨부된다. 비이미지 요청은 `스킵`, 실패는 `오류`로 기록한다.

## Meta Ads 실시간 효율 대시보드

경쟁 광고 인텔리전스와 별도로, 우리 Meta 광고계정 성과를 15–30분 단위로 모니터링하는
내부용 대시보드가 추가됐다. 데이터 기준은 Meta Marketing API Insights이며, 자사
CRM/결제 매출 ROAS 연결은 v2 범위다.

```bash
# 1) .env에 META_ACCESS_TOKEN, SLACK_WEBHOOK_URL(선택) 설정
python3 scripts/add_meta_account.py --account-id 123456789 --name "Clamoa KR"

# 2) 오늘+어제 성과 수집. 계정은 n개까지 meta_ad_accounts 레지스트리에 추가 가능.
python3 scripts/sync_meta_insights.py --all --lookback-days 2

# 3) 대시보드 실행
python3 scripts/serve_dashboard.py
```

주요 테이블:
- `meta_ad_accounts`: 광고계정 레지스트리. 새 계정은 row 추가만으로 확장.
- `meta_insights`: 일자·계정·레벨별 최신 성과 fact.
- `meta_insight_snapshots`: 당일 누적값 스냅샷.
- `meta_sync_runs`: 계정별 동기화 성공/실패 이력.
- `meta_alert_events`: Slack 중복 알림 방지 ledger.

### Vercel + Supabase 운영 DB

로컬 기본값은 SQLite지만, Vercel에서는 Supabase Postgres 연결 문자열을 env로 넣으면
영구 DB를 사용한다.

필수 Vercel env:
- `DATABASE_URL` 또는 `SUPABASE_DATABASE_URL`: Supabase Project Settings → Database → Connection string. Vercel 서버리스에서는 pooler URL 권장.
- `META_ACCESS_TOKEN`: Meta Marketing API 토큰.
- `META_AD_ACCOUNTS`: 서버리스 첫 기동 시 계정 레지스트리 시드. 예:
  `1700079570882719|clamoa|KRW|Asia/Seoul|landing_click`
- `CLAMOA_META_PIXEL_ID`: Clamoa 패션홍보대행사 랜딩 전용 Meta Pixel/Dataset ID.
- `CLAMOA_META_CAPI_ACCESS_TOKEN`: Clamoa Pixel의 Conversions API access token. 없으면 `META_CAPI_ACCESS_TOKEN`, `META_ACCESS_TOKEN` 순서로 fallback.
- `META_CAPI_ALLOWED_ORIGINS`: 랜딩과 CAPI API가 다른 도메인일 때 허용할 origin 목록.

배포 후 최초 1회:

```bash
curl -X POST "https://<vercel-url>/api/sync?lookback_days=5"
```

`DATABASE_URL`이 없으면 Vercel은 `/tmp/adintel.db` 임시 SQLite로 fallback하므로,
재배포/콜드스타트 때 데이터가 비어 보일 수 있다.

## Clamoa 랜딩 UTM + 선택 Pixel/CAPI

현재 Meta 광고 계정은 **Clamoa 패션홍보대행사 광고** 기준이다. 대시보드는
`/api/utm/event`에 저장된 랜딩 이벤트 중 `landing_key=clamoa`만 유입 소스 표에
집계하므로, asinayo 아카이브 랜딩 이벤트와 섞이지 않는다.

Clamoa 랜딩은 PageView/Lead 이벤트를 `/api/utm/event`로 보내고, 필요하면 같은
`event_id`를 `/api/meta/capi`로 보내 브라우저 Pixel 이벤트와 dedup 되도록 구성한다.

이벤트 매핑:
- `PageView`: 페이지 로드
- `ViewContent`: 랜딩 도달
- `Lead`: 상담/문의 폼 제출

Dataset/Pixel 생성:

```bash
python3 scripts/create_meta_pixel.py --account-id act_<AD_ACCOUNT_ID> --name "clamoa website"
```

출력된 `CLAMOA_META_PIXEL_ID`를 Vercel env와 Clamoa 랜딩 `meta-pixel-id`에 반영한다.
랜딩과 API가 다른 도메인이면 `meta-capi-endpoint`를 절대 URL로 바꾸고
`utm-event-endpoint`도 같은 API 도메인의 절대 URL로 바꾼다.
`META_CAPI_ALLOWED_ORIGINS`에 랜딩 origin을 추가한다.
운영 전 Events Manager의 Test Events 코드가 있으면 `META_CAPI_TEST_EVENT_CODE`로
검증하고, 운영 배포 전에는 값을 비운다.

광고 URL UTM 예:
- Meta: `?utm_source=meta&utm_medium=paid_social&utm_campaign=clamoa_brandfit`
- Naver: `?utm_source=naver&utm_medium=paid_search&utm_campaign=brandfit`
- Google: `?utm_source=google&utm_medium=paid_search&utm_campaign=brandfit`

참고: `99_Archive/asinayo_homepage/index.html`은 별도 아카이브 랜딩이며
`landing_key=asinayo`로 이벤트를 보내도록 분리되어 있다.

## 범위 밖 (이번 스캐폴드 제외)

실 GCP 배포(Cloud Run/BigQuery/GCS), 실 Apify 수집 검증, CAPI 루프(자체 광고 성과↔longevity 상관) — 기획서 Phase 4+.

---
name: grc-weekly-report
description: GRC(글로벌렌터카) 주간지표 자동 생성 — Redash 데이터 수집 → 분석 → Confluence 페이지 생성
triggers:
  - GRC 주간회의록
  - 렌터카 주간지표
  - 렌터카 주간회의록
  - grc weekly
  - 글로벌렌터카 주간
argument-hint: "[날짜 (기본: 오늘 기준 직전주)]"
---

# GRC 주간지표 자동 생성

## Purpose
매주 GRC(글로벌렌터카) 주간지표 문서를 자동 생성하는 스킬.
Redash에서 데이터를 가져와 분석하고, Confluence에 페이지를 생성한다.

## When to Activate
- "GRC 주간회의록 만들어줘", "렌터카 주간지표", "grc weekly" 등 요청 시
- 매주 월요일 자동 트리거 (RemoteTrigger trig_01Up9JhBmG5XHYe24JAKHdQo)

## 필수 규칙

1. **숫자 단위**: 'M', 'm', '백만' 등 약자 금지. 쉼표 구분 전체 숫자 표기 필수 (예: 1,234,567)
2. **주차 기준**: ISO 8601 (월요일 시작, 일요일 종료)
3. **문서 제목**: "GRC 주간지표 - YYYY.MM.DD (자동생성)" 형식 필수
4. **분석 기준**: 직전주(W2) 1주 기준. WoW 비교용으로 전전주(W1) 수치를 병렬 표시
5. **병렬 비교 표시**: 모든 지표는 이전 기간과 나란히 표시
   - WoW: 지표 / W1(ISO Wxx) / W2(ISO Wxx) / 변화 형식으로 4컬럼 표
   - MoM: 지표 / 지난달 / 이번달 / 변화 형식으로 4컬럼 표
   - 변화: 상승 ⬆️ xx%, 하락 ⬇️ xx%
   - CTR/CVR 등 비율지표도 반드시 이전 기간 병렬 표시
6. **크로스셀 인기 상품**: product_id + product_nm 모두 표시. 지역/도시별로 분류
7. **달성률 표기**: "현재 xx% 달성 (N일간 누적실적)" + "현 페이스 유지시 월말 예상 xx%" 형태로 명확히 구분

## 환경 정보

- **Redash URL**: https://redash.myrealtrip.net
- **Redash API Key**: memory `reference_redash.md` 참조
- **Confluence Space ID**: 4105405010
- **Confluence Parent Page ID**: 5812093101
- **Atlassian 인증**: memory `reference_atlassian_token.md` 참조 (Basic Auth email:token)

## Workflow

### Step 1. 날짜 계산 (Python3)

```python
from datetime import date, timedelta
today = date.today()
W2_start = today - timedelta(days=7)   # 직전주 월요일
W2_end   = today - timedelta(days=1)   # 직전주 일요일
W1_start = today - timedelta(days=14)  # 전전주 월요일
W1_end   = today - timedelta(days=8)   # 전전주 일요일
W1_iso = W1_start.isocalendar()[1]
W2_iso = W2_start.isocalendar()[1]
this_month_start = today.replace(day=1)
last_month_end   = this_month_start - timedelta(days=1)
last_month_start = last_month_end.replace(day=1)
page_title = "GRC 주간지표 - " + today.strftime('%Y.%m.%d') + " (자동생성)"
```

### Step 2. Redash 쿼리 실행

저장 쿼리는 `POST /api/queries/{QUERY_ID}/results` → job 폴링(status=3) → 결과 수집.

**저장 쿼리 목록:**
- Q35722: 파라미터 없음 → KPI 스냅샷 (어제/WTD/MTD)
- Q35943: end_date=W2_end, platform=["'mweb'","'app'","'web'"] → UTM 퍼널
- Q35723 이번달: start_date=this_month_start, end_date=W2_end, group_by=month
- Q35723 지난달: start_date=last_month_start, end_date=last_month_end, group_by=month
- Q35883: start_date=W1_start, end_date=W2_end → 크로스셀 일별 CTR
- Q35880: start_date=W1_start, end_date=W2_end → 메인홈 행동

**크로스셀 상품 (ad-hoc SQL, data_source_id=17):**
Q35884 저장 쿼리에 수정 권한이 없으므로, 아래 SQL을 `POST /api/query_results`로 직접 실행:

```sql
SELECT
  ds.product_id AS product_id,
  p.PRODUCT_NM  AS product_nm,
  p.CITY_CD     AS city,
  ds.vertical   AS vertical,
  COUNTIF(basis_dt BETWEEN DATE('{W1_start}') AND DATE('{W1_end}')) AS w1_click,
  COUNTIF(basis_dt BETWEEN DATE('{W2_start}') AND DATE('{W2_end}')) AS w2_click,
  AVG(SAFE_CAST(ds.product_position AS INT64)) AS avg_position
FROM `mrtdata.edw.DW_BIZ_LOG`
LEFT JOIN `mrtdata.edw_mart.MART_PRODUCT_D` p ON p.PRODUCT_ID = ds.product_id
WHERE basis_dt BETWEEN DATE('{W1_start}') AND DATE('{W2_end}')
  AND (page_category LIKE '글로벌 렌터카%' OR LOWER(screen_name) LIKE 'global_rentacar%')
  AND screen_name = 'global_rentacar_mybooking'
  AND event_name = 'cross_sell' AND event_type = 'click'
  AND ds.product_id IS NOT NULL
GROUP BY 1, 2, 3, 4
ORDER BY w2_click DESC, w1_click DESC LIMIT 10
```

**쿠폰 사용 현황 (ad-hoc SQL):**
쿠폰 ID: 31724~31731 + 31730

```sql
-- 쿠폰별 사용건수
SELECT c.COUPON_ID, c.COUPON_NM, COUNT(DISTINCT c.RESVE_ID) AS use_cnt
FROM `mrtdata.edw_mart.MART_COUPON_RESVE_D` c
WHERE c.COUPON_ID IN (31730, 31731, 31724, 31725, 31726, 31727, 31728, 31729)
  AND REGEXP_EXTRACT(c.RESVE_ID, r'GRC-(\d{8})') BETWEEN '{W2_start_compact}' AND '{W2_end_compact}'
GROUP BY 1, 2 ORDER BY use_cnt DESC

-- 쿠폰별 할인금액
SELECT c.COUPON_ID, c.COUPON_NM,
  COUNT(DISTINCT c.RESVE_ID) AS use_cnt,
  SUM(h.discount_amount) AS total_discount,
  SUM(h.coupon_target_amount) AS total_target
FROM `mrtdata.edw_mart.MART_COUPON_RESVE_D` c
JOIN `mrtdata.edw.DW_MRT_COUPONS_COUPON_USE_HISTORY` h
  ON h.reservation_no = c.RESVE_ID AND h.action_type = 'USE' AND h.deleted_at IS NULL
WHERE c.COUPON_ID IN (31730, 31731, 31724, 31725, 31726, 31727, 31728, 31729)
  AND REGEXP_EXTRACT(c.RESVE_ID, r'GRC-(\d{8})') BETWEEN '{W2_start_compact}' AND '{W2_end_compact}'
GROUP BY 1, 2 ORDER BY total_discount DESC
```

### Step 3. Python 분석

```python
def fmt(n):
    try: return f"{int(float(n)):,}"
    except: return "-"

def fmt_chg(a, b):
    try:
        v = (float(b) - float(a)) / float(a) * 100
        sign = "⬆️" if v >= 0 else "⬇️"
        return f"{sign} {abs(v):.1f}%"
    except: return "-"

def fmt_pp(a, b):
    try:
        v = float(b) - float(a)
        sign = "⬆️" if v >= 0 else "⬇️"
        return f"{sign} {abs(v):.1f}pp"
    except: return "-"
```

- UTM: W1/W2 날짜 기준 분리 후 주차별 합산
- MoM: Q35723 이번달 vs 지난달 ALL행 비교
- 크로스셀: ad-hoc SQL 결과 → city 기준 그룹화, w2_click DESC 정렬
- 달성률: 현재 달성 + 일평균 페이스 기반 월말 예상 별도 표기

### Step 4. Confluence 페이지 생성

Confluence REST API v2 (`POST /api/v2/pages`) 사용:
- Base: https://myrealtrip.atlassian.net/wiki
- Auth: Basic Auth (memory 참조)
- spaceId: 4105405010
- parentId: 5812093101
- contentFormat: storage (HTML)

**페이지 섹션 순서:**

1. **TDL** — 지난주 미팅록 기반 금주 팔로업 체크박스 (있을 경우)
2. **GMV·공헌이익·달성률** — KPI 스냅샷 표 + 달성률/페이스 예상 불릿
3. **유입·전환 WoW** — 퍼널 표 (홈UV→리스트→상세→예약시도→완료→CVR) + 불릿
4. **UTM별 유입 분해** — 내부/외부 구분, source별 유입·완료·WoW 표
5. **월간 MoM** — 5월 vs 6월 MTD 진도율 표
6. **쿠폰 사용 현황** — 쿠폰별 사용건수·할인총액·적용거래액 표
7. **쿠폰 정액할인 시뮬레이션** (해당 시 — GRC CM 9%, 국내 CM 10% 기준)
8. **주요 포인트** — 핵심 인사이트 + 액션 아이템 불릿

### Step 5. 완료

생성된 Confluence 페이지 URL 출력.

## 참고

- 크로스셀 섹션은 요청 시에만 포함 (기본 미포함)
- 쿠폰 시뮬레이션은 요청 시에만 포함
- GRC 결제금액 분포 데이터: `DW_MRT_COUPONS_COUPON_USE_HISTORY.coupon_target_amount` 기준
  - 10~20만: 39.1%, 20~30만: 26.4%, 30~50만: 26.4%

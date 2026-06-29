# -*- coding: utf-8 -*-
"""
GRC 주간지표 자동 생성 스크립트
사용법: python3 run.py [YYYY-MM-DD]
  - 날짜 미입력 시 오늘 기준으로 직전주 분석
  - 예: python3 run.py 2026-06-29
"""
import json, urllib.request, time, base64, sys, os
from datetime import date, timedelta
from collections import defaultdict

# ── Config ────────────────────────────────────────────────
REDASH_URL = "https://redash.myrealtrip.net"
REDASH_KEY = os.environ.get("REDASH_API_KEY", "")
if not REDASH_KEY:
    print("ERROR: REDASH_API_KEY environment variable is required.")
    print("  export REDASH_API_KEY='your-key-here'")
    sys.exit(1)
CONFLUENCE_URL = "https://myrealtrip.atlassian.net/wiki"
CONFLUENCE_EMAIL = os.environ.get("CONFLUENCE_EMAIL", "yulim.kim@myrealtrip.com")
CONFLUENCE_TOKEN = os.environ.get("CONFLUENCE_TOKEN", "")
SPACE_ID = "4105405010"
PARENT_ID = "5812093101"
CM_TARGET = 15962412
GMV_TARGET = 916740000

# ── Helpers ───────────────────────────────────────────────
def redash_post_query(qid, params):
    payload = {"parameters": params, "max_age": 0}
    req = urllib.request.Request(
        f"{REDASH_URL}/api/queries/{qid}/results",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type":"application/json","Authorization":f"Key {REDASH_KEY}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["job"]["id"]

def redash_adhoc(sql):
    payload = {"data_source_id": 17, "query": sql, "parameters": {}, "max_age": 0}
    req = urllib.request.Request(
        f"{REDASH_URL}/api/query_results",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Content-Type":"application/json","Authorization":f"Key {REDASH_KEY}"})
    with urllib.request.urlopen(req) as r:
        return json.load(r)["job"]["id"]

def redash_poll(job_id, max_wait=200):
    for _ in range(max_wait // 4):
        time.sleep(4)
        with urllib.request.urlopen(urllib.request.Request(
            f"{REDASH_URL}/api/jobs/{job_id}?api_key={REDASH_KEY}",
            headers={"Authorization":f"Key {REDASH_KEY}"})) as r:
            job = json.load(r)["job"]
        if job["status"] == 3: return job["query_result_id"]
        if job["status"] == 4: raise Exception(f"Query failed: {job['error'][:200]}")
    raise Exception("Timeout")

def redash_fetch(rid):
    with urllib.request.urlopen(urllib.request.Request(
        f"{REDASH_URL}/api/query_results/{rid}?api_key={REDASH_KEY}",
        headers={"Authorization":f"Key {REDASH_KEY}"})) as r:
        return json.load(r)["query_result"]["data"]["rows"]

def redash_run(qid, params):
    return redash_fetch(redash_poll(redash_post_query(qid, params)))

def redash_run_adhoc(sql):
    return redash_fetch(redash_poll(redash_adhoc(sql)))

def fmt(n):
    try: return f"{int(float(n)):,}"
    except: return "-"

def chg(a, b):
    try:
        a, b = float(a), float(b)
        if a == 0: return "N/A"
        v = (b - a) / a * 100
        s = "\u2b06\ufe0f" if v >= 0 else "\u2b07\ufe0f"
        return f"{s} {abs(v):.1f}%"
    except: return "-"

def pp(a, b):
    try:
        v = float(b) - float(a)
        s = "\u2b06\ufe0f" if v >= 0 else "\u2b07\ufe0f"
        return f"{s} {abs(v):.1f}pp"
    except: return "-"

# ── Step 1: Dates ─────────────────────────────────────────
if len(sys.argv) > 1:
    today = date.fromisoformat(sys.argv[1])
else:
    today = date.today()

W2_start = today - timedelta(days=7)
W2_end   = today - timedelta(days=1)
W1_start = today - timedelta(days=14)
W1_end   = today - timedelta(days=8)
W1_iso   = W1_start.isocalendar()[1]
W2_iso   = W2_start.isocalendar()[1]
tms      = today.replace(day=1)
lme      = tms - timedelta(days=1)
lms      = lme.replace(day=1)
days_in_month = (today - tms).days

page_title = f"GRC \uc8fc\uac04\uc9c0\ud45c - {today.strftime('%Y.%m.%d')} (\uc790\ub3d9\uc0dd\uc131)"
print(f"Date: {today} | W1=ISO W{W1_iso}({W1_start}~{W1_end}) | W2=ISO W{W2_iso}({W2_start}~{W2_end})")
print(f"Title: {page_title}")

# ── Step 2: Collect Data ──────────────────────────────────
print("\n[Step 2] Collecting Redash data...")
data = {}
jobs = {}
jobs["kpi"]  = redash_post_query(35722, {})
jobs["utm"]  = redash_post_query(35943, {"end_date": str(W2_end), "platform": ["'mweb'","'app'","'web'"], "start_date": str(W1_start)})
jobs["mom"]  = redash_post_query(35723, {"start_date": str(tms), "end_date": str(W2_end), "group_by": "month"})
jobs["lm"]   = redash_post_query(35723, {"start_date": str(lms), "end_date": str(lme), "group_by": "month"})
jobs["ctr"]  = redash_post_query(35883, {"start_date": str(W1_start), "end_date": str(W2_end)})
jobs["main"] = redash_post_query(35880, {"start_date": str(W1_start), "end_date": str(W2_end)})

W2sc = W2_start.strftime("%Y%m%d")
W2ec = W2_end.strftime("%Y%m%d")
jobs["coupon"] = redash_adhoc(f"""
SELECT c.COUPON_ID, c.COUPON_NM,
  COUNT(DISTINCT c.RESVE_ID) AS use_cnt,
  SUM(h.discount_amount) AS total_discount,
  SUM(h.coupon_target_amount) AS total_target
FROM `mrtdata.edw_mart.MART_COUPON_RESVE_D` c
JOIN `mrtdata.edw.DW_MRT_COUPONS_COUPON_USE_HISTORY` h
  ON h.reservation_no = c.RESVE_ID AND h.action_type = 'USE' AND h.deleted_at IS NULL
WHERE c.COUPON_ID IN (31730,31731,31724,31725,31726,31727,31728,31729)
  AND REGEXP_EXTRACT(c.RESVE_ID, r'GRC-(\\d{{8}})') BETWEEN '{W2sc}' AND '{W2ec}'
GROUP BY 1, 2 ORDER BY total_discount DESC
""")

jobs["funnel"] = redash_adhoc(f"""
SELECT
  CASE WHEN basis_dt BETWEEN DATE('{W1_start}') AND DATE('{W1_end}') THEN 'W1'
       WHEN basis_dt BETWEEN DATE('{W2_start}') AND DATE('{W2_end}') THEN 'W2' END AS week,
  COUNT(DISTINCT CASE WHEN LOWER(screen_name) LIKE 'global_rentacar_home%' OR LOWER(screen_name) = 'global_rentacar_main' THEN pid END) AS home_uv,
  COUNT(DISTINCT CASE WHEN LOWER(screen_name) LIKE 'global_rentacar_list%' OR LOWER(screen_name) LIKE 'global_rentacar_search%' THEN pid END) AS list_uv,
  COUNT(DISTINCT CASE WHEN LOWER(screen_name) LIKE 'global_rentacar_detail%' THEN pid END) AS detail_uv,
  COUNT(DISTINCT CASE WHEN screen_name = 'global_rentacar_detail' AND event_name = 'order_try' AND event_type = 'click' THEN pid END) AS order_try_uv
FROM `mrtdata.edw.DW_BIZ_LOG`
WHERE basis_dt BETWEEN DATE('{W1_start}') AND DATE('{W2_end}')
  AND (page_category LIKE '\uae00\ub85c\ubc8c \ub80c\ud130\uce74%' OR LOWER(screen_name) LIKE 'global_rentacar%')
GROUP BY 1 ORDER BY 1
""")

for name, jid in jobs.items():
    try:
        rid = redash_poll(jid)
        data[name] = redash_fetch(rid)
        print(f"  {name}: {len(data[name])} rows")
    except Exception as e:
        data[name] = []
        print(f"  {name}: ERROR - {e}")

# ── Step 3: Analyze ───────────────────────────────────────
print("\n[Step 3] Analyzing...")
W1_dates = {str(W1_start + timedelta(days=i)) for i in range(7)}
W2_dates = {str(W2_start + timedelta(days=i)) for i in range(7)}

# MoM
lm_all = next((r for r in data["lm"] if r.get("country_nm")=="ALL"), data["lm"][0] if data["lm"] else {})
cm_all = next((r for r in data["mom"] if r.get("country_nm")=="ALL"), data["mom"][0] if data["mom"] else {})

# WoW from main
w1_main = sum(r["pv_uv"] for r in data["main"] if r["date"] in W1_dates)
w2_main = sum(r["pv_uv"] for r in data["main"] if r["date"] in W2_dates)

# WoW from UTM
w1_utm = [r for r in data["utm"] if r["basis_dt"] in W1_dates]
w2_utm = [r for r in data["utm"] if r["basis_dt"] in W2_dates]
w1_cc = sum(r["grc_checkout_complete_uv"] for r in w1_utm)
w2_cc = sum(r["grc_checkout_complete_uv"] for r in w2_utm)
w1_cvr = w1_cc / w1_main * 100 if w1_main else 0
w2_cvr = w2_cc / w2_main * 100 if w2_main else 0

# UTM by source
src_w1 = defaultdict(lambda: [0, 0])
src_w2 = defaultdict(lambda: [0, 0])
for r in w1_utm:
    src_w1[r["utm_source"]][0] += r["grc_main_uv"]
    src_w1[r["utm_source"]][1] += r["grc_checkout_complete_uv"]
for r in w2_utm:
    src_w2[r["utm_source"]][0] += r["grc_main_uv"]
    src_w2[r["utm_source"]][1] += r["grc_checkout_complete_uv"]
all_src = sorted(set(list(src_w1.keys()) + list(src_w2.keys())),
                 key=lambda s: src_w2[s][0] + src_w1[s][0], reverse=True)

# Funnel
fn_w1 = next((r for r in data["funnel"] if r["week"] == "W1"), {})
fn_w2 = next((r for r in data["funnel"] if r["week"] == "W2"), {})

# KPI
kpi_mtd = next((r for r in data["kpi"] if r["\uad6c\ubd84"] == "3_MTD"), {})
kpi_wtd = next((r for r in data["kpi"] if r["\uad6c\ubd84"] == "2_WTD"), {})
kpi_yesterday = next((r for r in data["kpi"] if r["\uad6c\ubd84"] == "1_\uc5b4\uc81c"), {})
kpi_prev = next((r for r in data["kpi"] if r["\uad6c\ubd84"] == "4_\uc804\uc8fc\ub3d9\uc77c\uc694\uc77c"), {})

mtd_cm = kpi_mtd.get("\ud655\uc815\uacf5\ud5cc\uc774\uc775_\uc6d0", 0)
daily_cm = mtd_cm / days_in_month if days_in_month else 0
projected_cm = daily_cm * 30
mtd_gmv = kpi_mtd.get("\uac70\ub798\uc561_\uc6d0", 0)

# Coupon totals
coupon_total_use = sum(r.get("use_cnt", 0) for r in data["coupon"])
coupon_total_discount = sum(r.get("total_discount", 0) for r in data["coupon"])
coupon_total_target = sum(r.get("total_target", 0) for r in data["coupon"])

print(f"  MoM: GMV {lm_all.get('gmv',0):,.0f} -> {cm_all.get('gmv',0):,.0f}")
print(f"  WoW: MainUV {w1_main}->{w2_main}, CC {w1_cc}->{w2_cc}, CVR {w1_cvr:.1f}%->{w2_cvr:.1f}%")
print(f"  Coupon: {coupon_total_use} uses, {coupon_total_discount:,.0f} discount")

# ── Step 4: Build HTML ────────────────────────────────────
print("\n[Step 4] Building HTML...")

def tr(*cells, bold=False):
    tag = "th" if bold else "td"
    return "<tr>" + "".join(f"<{tag}><p>{c}</p></{tag}>" for c in cells) + "</tr>"

def table(headers, rows):
    h = "<thead>" + tr(*headers, bold=True) + "</thead>"
    b = "<tbody>" + "".join(tr(*row) for row in rows) + "</tbody>"
    return f"<table>{h}{b}</table>"

# UTM rows (top 9)
utm_rows = []
for s in all_src[:9]:
    w1v, w2v = src_w1[s], src_w2[s]
    utm_rows.append((s, fmt(w1v[0]), fmt(w2v[0]), chg(w1v[0], w2v[0]),
                      fmt(w1v[1]), fmt(w2v[1]), chg(w1v[1], w2v[1])))

# Coupon rows
coupon_rows = []
for r in data["coupon"]:
    coupon_rows.append((
        str(r["COUPON_ID"]),
        r["COUPON_NM"].replace("\U0001f433", "").replace("\U0001f3ef", "").replace("\U0001f5fc", "").replace("\u26e9\ufe0f", "").replace("\U0001f525", "").strip()[:20],
        f'{r["use_cnt"]}\uac74',
        f'{r["total_discount"]:,}\uc6d0',
        f'{r["total_target"]:,}\uc6d0'
    ))
coupon_rows.append(("<strong>\ud569\uacc4</strong>", "", f"<strong>{coupon_total_use}\uac74</strong>",
                     f"<strong>{coupon_total_discount:,}\uc6d0</strong>", f"<strong>{coupon_total_target:,}\uc6d0</strong>"))

body = "".join([
    f'<h2>[{today}] \ub80c\ud2b8\uce74 Weekly Sync</h2>',
    f'<p><strong>\uae30\uc900:</strong> {W2_start} ~ {W2_end} (ISO W{W2_iso}) | W{W1_iso}({W1_start}~{W1_end}) \ub300\ube44 WoW</p>',
    '<hr>',

    # 1. GMV/CM/달성률
    f'<h2>1. GMV \xb7 \uacf5\ud5cc\uc774\uc775 \xb7 \ub2ec\uc131\ub960</h2>',
    table(["\uad6c\ubd84", "\uac70\ub798\uc561 (\uc6d0)", "\ud655\uc815 CM (\uc6d0)", "CM \ubaa9\ud45c", "\ub2ec\uc131\ub960"], [
        (f'\uc5b4\uc81c ({W2_end})', fmt(kpi_yesterday.get("\uac70\ub798\uc561_\uc6d0",0)), fmt(kpi_yesterday.get("\ud655\uc815\uacf5\ud5cc\uc774\uc775_\uc6d0",0)),
         fmt(kpi_yesterday.get("\uacf5\ud5cc\uc774\uc775_\ubaa9\ud45c",0)), f'{kpi_yesterday.get("\uacf5\ud5cc\uc774\uc775_\ub2ec\uc131\ub960",0)*100:.1f}%'),
        (f'WTD ({W2_start}~{W2_end})', fmt(kpi_wtd.get("\uac70\ub798\uc561_\uc6d0",0)), fmt(kpi_wtd.get("\ud655\uc815\uacf5\ud5cc\uc774\uc775_\uc6d0",0)),
         fmt(kpi_wtd.get("\uacf5\ud5cc\uc774\uc775_\ubaa9\ud45c",0)), f'{kpi_wtd.get("\uacf5\ud5cc\uc774\uc775_\ub2ec\uc131\ub960",0)*100:.1f}%'),
        (f'MTD ({tms}~{W2_end})', fmt(mtd_gmv), fmt(mtd_cm), fmt(CM_TARGET), f'{mtd_cm/CM_TARGET*100:.1f}%'),
        (f'\uc804\uc8fc\ub3d9\uc77c\uc694\uc77c ({W1_end})', fmt(kpi_prev.get("\uac70\ub798\uc561_\uc6d0",0)), fmt(kpi_prev.get("\ud655\uc815\uacf5\ud5cc\uc774\uc775_\uc6d0",0)),
         fmt(kpi_prev.get("\uacf5\ud5cc\uc774\uc775_\ubaa9\ud45c",0)), f'{kpi_prev.get("\uacf5\ud5cc\uc774\uc775_\ub2ec\uc131\ub960",0)*100:.1f}%'),
    ]),
    '<ul>',
    f'<li><strong>{tms.month}\uc6d4 MTD \uac70\ub798\uc561</strong>: {fmt(mtd_gmv)}\uc6d0 \u2014 \ubaa9\ud45c {fmt(GMV_TARGET)}\uc6d0 \ub300\ube44 <strong>\ud604\uc7ac {mtd_gmv/GMV_TARGET*100:.1f}% \ub2ec\uc131</strong> ({days_in_month}\uc77c\uac04 \ub204\uc801)</li>',
    f'<li><strong>{tms.month}\uc6d4 MTD \ud655\uc815 CM</strong>: {fmt(mtd_cm)}\uc6d0 \u2014 \ubaa9\ud45c {fmt(CM_TARGET)}\uc6d0 \ub300\ube44 <strong>\ud604\uc7ac {mtd_cm/CM_TARGET*100:.1f}% \ub2ec\uc131</strong>. \uc77c\ud3c9\uade0 {fmt(daily_cm)}\uc6d0 \ud398\uc774\uc2a4 \uc720\uc9c0\uc2dc \uc6d4\ub9d0 \uc608\uc0c1 \uc57d {fmt(projected_cm)}\uc6d0 (<strong>\uc6d4\ub9d0 \uc608\uc0c1 {projected_cm/CM_TARGET*100:.1f}%</strong>)</li>',
    f'<li><strong>W{W2_iso} \uac70\ub798\uc561</strong>: {fmt(kpi_wtd.get("\uac70\ub798\uc561_\uc6d0",0))}\uc6d0 | <strong>W{W2_iso} \ud655\uc815 CM</strong>: {fmt(kpi_wtd.get("\ud655\uc815\uacf5\ud5cc\uc774\uc775_\uc6d0",0))}\uc6d0</li>',
    f'<li><strong>MoM</strong>: GMV {fmt(lm_all.get("gmv",0))}\uc6d0(5\uc6d4) \u2192 {fmt(cm_all.get("gmv",0))}\uc6d0(6\uc6d4 {days_in_month}\uc77c) {chg(lm_all.get("gmv",1), cm_all.get("gmv",0))} | CM {chg(lm_all.get("cm",1), cm_all.get("cm",0))}</li>',
    '</ul><hr>',

    # 2. 유입/전환 WoW
    f'<h2>2. \uc720\uc785 \xb7 \uc804\ud658 WoW</h2>',
    '<h3>\ud37c\ub110 WoW</h3>',
    table(["\ub2e8\uacc4", f"W{W1_iso}", f"W{W2_iso}", "WoW"], [
        ("\ud648 UV", fmt(fn_w1.get("home_uv",0)), fmt(fn_w2.get("home_uv",0)), chg(fn_w1.get("home_uv",0), fn_w2.get("home_uv",0))),
        ("\ub9ac\uc2a4\ud2b8 UV", fmt(fn_w1.get("list_uv",0)), fmt(fn_w2.get("list_uv",0)), chg(fn_w1.get("list_uv",0), fn_w2.get("list_uv",0))),
        ("\uc0c1\uc138 UV", fmt(fn_w1.get("detail_uv",0)), fmt(fn_w2.get("detail_uv",0)), chg(fn_w1.get("detail_uv",0), fn_w2.get("detail_uv",0))),
        ("\uc608\uc57d\uc2dc\ub3c4 UV", fmt(fn_w1.get("order_try_uv",0)), fmt(fn_w2.get("order_try_uv",0)), chg(fn_w1.get("order_try_uv",0), fn_w2.get("order_try_uv",0))),
        ("\uad6c\ub9e4\uc644\ub8cc UV", fmt(w1_cc), fmt(w2_cc), chg(w1_cc, w2_cc)),
        ("CVR (\uc644\ub8cc/\ud648)", f"{w1_cvr:.1f}%", f"{w2_cvr:.1f}%", pp(w1_cvr, w2_cvr)),
    ]),
    '<hr>',

    # 3. UTM
    f'<h2>3. UTM\ubcc4 \uc720\uc785 \ubd84\ud574</h2>',
    table(["utm_source", f"W{W1_iso} \uc720\uc785", f"W{W2_iso} \uc720\uc785", "WoW",
           f"W{W1_iso} \uc644\ub8cc", f"W{W2_iso} \uc644\ub8cc", "WoW"], utm_rows),
    '<hr>',

    # 4. MoM
    f'<h2>4. \uc6d4\uac04 MoM ({lms.month}\uc6d4 vs {tms.month}\uc6d4 MTD)</h2>',
    f'<p>\u203b {tms.month}\uc6d4 {days_in_month}\uc77c\uac04 \ub204\uc801</p>',
    table(["\uc9c0\ud45c", f"{lms.month}\uc6d4", f"{tms.month}\uc6d4 MTD ({days_in_month}\uc77c)", "\uc9c4\ub3c4\uc728"], [
        ("\uac70\ub798\uc561", f'{fmt(lm_all.get("gmv",0))}\uc6d0', f'{fmt(cm_all.get("gmv",0))}\uc6d0', f'{cm_all.get("gmv",0)/lm_all.get("gmv",1)*100:.1f}%'),
        ("\uacf5\ud5cc\uc774\uc775", f'{fmt(lm_all.get("cm",0))}\uc6d0', f'{fmt(cm_all.get("cm",0))}\uc6d0', f'{cm_all.get("cm",0)/lm_all.get("cm",1)*100:.1f}%'),
        ("\uc608\uc57d\uc218", f'{lm_all.get("rsv_cnt",0)}\uac74', f'{cm_all.get("rsv_cnt",0)}\uac74', f'{cm_all.get("rsv_cnt",0)/max(lm_all.get("rsv_cnt",1),1)*100:.1f}%'),
        ("\ud655\uc815\ub960", f'{lm_all.get("confirm_rate",0):.1f}%', f'{cm_all.get("confirm_rate",0):.1f}%', pp(lm_all.get("confirm_rate",0), cm_all.get("confirm_rate",0))),
        ("CVR", f'{lm_all.get("cvr",0):.1f}%', f'{cm_all.get("cvr",0):.1f}%', pp(lm_all.get("cvr",0), cm_all.get("cvr",0))),
    ]),
    '<hr>',

    # 5. 쿠폰
    f'<h2>5. \ucfe0\ud3f0 \uc0ac\uc6a9 \ud604\ud669 (W{W2_iso})</h2>',
    table(["\ucfe0\ud3f0 ID", "\ucfe0\ud3f0\uba85", "\uc0ac\uc6a9", "\ud560\uc778 \ucd1d\uc561", "\uc801\uc6a9 \uac70\ub798\uc561"], coupon_rows) if coupon_rows else '<p>\uc0ac\uc6a9 \uc5c6\uc74c</p>',
    '<hr>',

    # 6. 주요 포인트 (placeholder - to be filled with insights)
    f'<h2>6. \uc8fc\uc694 \ud3ec\uc778\ud2b8</h2>',
    '<p>\u203b \ub370\uc774\ud130 \uae30\ubc18 \uc790\ub3d9 \uc0dd\uc131 \uc644\ub8cc. \uc778\uc0ac\uc774\ud2b8\ub294 \uc218\ub3d9 \ucd94\uac00 \ud544\uc694.</p>',
])

print(f"  HTML: {len(body):,} chars")

# ── Step 5: Create Confluence Page ────────────────────────
if not CONFLUENCE_TOKEN:
    print("\n[Step 5] CONFLUENCE_TOKEN not set. Saving HTML to /tmp/grc_weekly.html")
    with open("/tmp/grc_weekly.html", "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  Saved: /tmp/grc_weekly.html ({len(body):,} chars)")
    print(f"  Title: {page_title}")
    sys.exit(0)

print("\n[Step 5] Creating Confluence page...")
auth = base64.b64encode(f"{CONFLUENCE_EMAIL}:{CONFLUENCE_TOKEN}".encode()).decode()
payload = {
    "spaceId": SPACE_ID, "status": "current",
    "title": page_title,
    "parentId": PARENT_ID,
    "body": {"representation": "storage", "value": body}
}
req = urllib.request.Request(
    f"{CONFLUENCE_URL}/api/v2/pages",
    data=json.dumps(payload).encode(), method="POST",
    headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
try:
    with urllib.request.urlopen(req) as resp:
        result = json.load(resp)
        page_id = result["id"]
        print(f"  SUCCESS! page_id={page_id}")
        print(f"  URL: {CONFLUENCE_URL}/spaces/gB5E2neaQX5Z/pages/{page_id}")
except urllib.error.HTTPError as e:
    print(f"  HTTPError {e.code}: {e.read().decode()[:500]}")
    # Fallback: save HTML
    with open("/tmp/grc_weekly.html", "w", encoding="utf-8") as f:
        f.write(body)
    print(f"  Fallback saved: /tmp/grc_weekly.html")

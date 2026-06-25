# BSE Connector — Reconnaissance Report

**Phase:** 1 — Reconnaissance (complete)
**Date:** 2026-06-25
**Method:** Live network inspection blocked by sandbox; endpoints sourced from:
- Reverse-engineering of `BennyThadikaran/BseIndiaApi` (Python library that wraps real BSE XHR traffic)
- Direct response sampling via raw file fetches from that library's sample corpus
- Web searches confirming PDF URL patterns and authentication requirements

This document is the prerequisite for Phase 2 (API design) and Phase 3 (connector implementation).
No connector code exists yet.

---

## Authentication and Session Model

BSE's JSON API at `api.bseindia.com` is **not publicly accessible without a browser session**. Direct calls
return HTTP 301 to `https://www.bseindia.com/members/showinterest.aspx`, which is a login redirect.

**What the real browser does:**
1. Loads `https://www.bseindia.com/` — establishes session cookies.
2. All subsequent XHR calls include those cookies and the mandatory headers below.
3. The API checks `Referer` and likely `Origin`; calls without them are rejected.

**Required headers on every API call:**

```
User-Agent:      Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36
Accept:          application/json, text/plain, */*
Accept-Language: en-US,en;q=0.5
Origin:          https://www.bseindia.com/
Referer:         https://www.bseindia.com/
Connection:      keep-alive
```

**Session acquisition strategy for the connector:**
- Use a `requests.Session` object.
- Issue a GET to `https://www.bseindia.com/` before the first API call to set cookies.
- Reuse the session for all subsequent calls within a run.

---

## Base URLs

| Label       | Value                                          |
|-------------|------------------------------------------------|
| Web base    | `https://www.bseindia.com/`                    |
| API base    | `https://api.bseindia.com/BseIndiaAPI/api`     |
| Filing CDN  | `https://www.bseindia.com/xml-data/corpfiling` |

---

## Key Identifier: Scrip Code

Every BSE-listed company has a numeric **scrip code**. This is the primary key for all company-specific API calls.

- TCS: `532540`
- Not the same as NSE ticker symbol.
- BSE also uses ISIN (`INE467B01029` for TCS) but the API predominantly uses scrip code.

**Scrip code lookup endpoint:**

```
GET {API_BASE}/PeerSmartSearch/w?Type=EQ&text={query}
```

| Parameter | Type   | Description                          |
|-----------|--------|--------------------------------------|
| `Type`    | string | `EQ` for equity, `MF` for mutual fund |
| `text`    | string | Company name or ticker fragment      |

---

## Endpoint Inventory

### 1. Equity Metadata (`ComHeadernew/w`)

Returns fundamental reference data for a listed equity.

```
GET {API_BASE}/ComHeadernew/w?quotetype=EQ&scripcode={scripcode}
```

| Parameter   | Type   | Required | Description                  |
|-------------|--------|----------|------------------------------|
| `quotetype` | string | yes      | Always `EQ` for equity       |
| `scripcode` | int    | yes      | BSE scrip code               |
| `seriesid`  | string | no       | Series identifier (optional) |

**Response sample (field inventory):**

```json
{
  "SecurityId": "ETERNAL",
  "Grp_Index": "A / BSE SENSEX",
  "FaceVal": "1.00",
  "SecurityCode": "543320",
  "ISIN": "INE758T01015",
  "Industry": "E-Retail/ E-Commerce",
  "Group": "A",
  "Index": "BSE SENSEX",
  "PAIDUP_VALUE": "",
  "EPS": "2.62",
  "CEPS": "2.80",
  "PE": "102.65",
  "OPM": "27.89",
  "NPM": "22.79",
  "PB": "10.75",
  "ROE": "10.46",
  "Sector": "Consumer Discretionary",
  "IndustryNew": "Consumer Services",
  "IGroup": "Retailing",
  "ISubGroup": "E-Retail/ E-Commerce",
  "IShow": "1",
  "SetlType": "T+1",
  "COName": "",
  "Contact": "",
  "Email": "",
  "SDD": "",
  "COdetails": "",
  "sddscrip": "",
  "maturitydate": "",
  "ConEPS": "0.24",
  "ConCEPS": "1.71",
  "ConPE": "1123.58",
  "ConOPM": "0.00",
  "ConNPM": "0.00",
  "ConPB": null,
  "ConROE": null
}
```

**Notes:**
- All numeric fields arrive as strings (e.g., `"2.62"` not `2.62`).
- `null` values appear for consolidated metrics when unavailable.
- `ConEPS`, `ConPE`, etc. are consolidated (group-level) financials.

---

### 2. Announcements (`AnnSubCategoryGetData/w`)

**This is the primary endpoint for Atlas.** Returns corporate announcements including annual reports, board meeting outcomes, results, and filings.

```
GET {API_BASE}/AnnSubCategoryGetData/w
```

| Parameter     | Type   | Required | Default | Description                                         |
|---------------|--------|----------|---------|-----------------------------------------------------|
| `pageno`      | int    | yes      | 1       | Pagination (22 records per page based on samples)   |
| `strCat`      | string | yes      | `-1`    | Category filter; `-1` = all. See categories below.  |
| `subcategory` | string | yes      | `-1`    | Subcategory filter; `-1` = all                      |
| `strPrevDate` | string | yes      | —       | From-date in `YYYYMMDD` format                      |
| `strToDate`   | string | yes      | —       | To-date in `YYYYMMDD` format                        |
| `strSearch`   | string | yes      | `P`     | Always `P` (purpose literal, do not change)         |
| `strscrip`    | int    | no       | —       | BSE scrip code; omit for market-wide query          |
| `strType`     | string | yes      | `C`     | `C` = equity, `D` = debt, `M` = MF/ETF             |

**Announcement categories (`strCat` values):**

| Value             | Purpose                                        |
|-------------------|------------------------------------------------|
| `-1`              | All categories                                 |
| `AGM/EGM`         | AGM/EGM notices and annual reports             |
| `Board Meeting`   | Board meeting notices and outcomes             |
| `Company Update`  | General company updates                        |
| `Corp. Action`    | Corporate actions (dividends, splits, buyback) |
| `Insider Trading / SAST` | Insider trading disclosures            |
| `New Listing`     | New listing announcements                      |
| `Result`          | Quarterly/annual results                       |
| `Others`          | Miscellaneous                                  |

**Annual report retrieval strategy:**
- Set `strCat=AGM/EGM`, `strscrip={scripcode}`, broad date range.
- Filter returned records by `SUBCATNAME` containing `"Annual Report"`.
- The `SUBCATNAME` field carries the exact SEBI regulatory category (e.g., `"Annual Report"`, `"Annual Report - Revised"`).

**Response structure:**

```json
{
  "Table": [
    {
      "NEWSID": "6fb57b5e-a05f-4e05-b2da-6e2b5bfe32ae",
      "SCRIP_CD": 517397,
      "XML_NAME": "ANN_517397_6FB57B5E-A05F-4E05-B2DA-6E2B5BFE32AE",
      "NEWSSUB": "COMPANY - 517397 - Announcement subject line",
      "DT_TM": "2023-10-20T23:44:22.95",
      "NEWS_DT": "2023-10-20T23:44:22.95",
      "CRITICALNEWS": 0,
      "ANNOUNCEMENT_TYPE": "A",
      "QUARTER_ID": null,
      "FILESTATUS": "N    ",
      "ATTACHMENTNAME": "aab502e1-3e05-4fdc-bc10-ecbb436cab8d.pdf",
      "MORE": "",
      "HEADLINE": "Human-readable announcement headline",
      "CATEGORYNAME": null,
      "OLD": 1,
      "RN": 1,
      "PDFFLAG": 1,
      "NSURL": "https://www.bseindia.com/stock-share-price/company-name/TICKER/517397/",
      "SLONGNAME": "COMPANY FULL NAME LTD.",
      "AGENDA_ID": 177,
      "TotalPageCnt": 22,
      "News_submission_dt": "2023-10-20T23:44:22",
      "DissemDT": "2023-10-20T23:44:22.95",
      "TimeDiff": "00:00:00",
      "Fld_Attachsize": 626877,
      "SUBCATNAME": "Reg. 39 (3) - Details of Loss of Certificate / Duplicate Certificate",
      "AUDIO_VIDEO_FILE": null
    }
  ],
  "Table1": [
    {
      "ROWCNT": 1292
    }
  ]
}
```

**Field semantics:**

| Field            | Type      | Notes                                                              |
|------------------|-----------|--------------------------------------------------------------------|
| `NEWSID`         | UUID str  | Unique announcement identifier                                     |
| `SCRIP_CD`       | int       | BSE scrip code                                                     |
| `ATTACHMENTNAME` | str       | UUID filename of PDF; use with filing CDN URL below               |
| `OLD`            | int       | `1` = historical filing (use `AttachHis`); `0` = recent (`AttachLive`) |
| `PDFFLAG`        | int       | `1` = attachment exists and is a PDF                              |
| `Fld_Attachsize` | int       | File size in bytes                                                 |
| `SUBCATNAME`     | str       | Regulatory subcategory name; use to identify annual reports        |
| `DT_TM`          | datetime  | BSE server timestamp (IST, no timezone marker)                    |
| `TotalPageCnt`   | int       | Total pages in result set (use for pagination)                    |
| `ROWCNT`         | int       | Total records matching query (in `Table1`)                        |

---

### 3. Corporate Actions (`DefaultData/w`)

Returns dividend, bonus, split, buyback, and AGM date schedules.

```
GET {API_BASE}/DefaultData/w
```

| Parameter      | Type   | Description                                             |
|----------------|--------|---------------------------------------------------------|
| `ddlcategorys` | string | Category filter                                         |
| `ddlindustrys` | string | Industry filter                                         |
| `segment`      | string | Market segment                                          |
| `strSearch`    | string | Text search                                             |
| `Fdate`        | string | From date                                               |
| `TDate`        | string | To date                                                 |
| `Purposecode`  | string | Purpose codes: `P5`=Bonus, `P6`=Buyback, `P9`=Dividend, `P10`=Preference Dividend, `P26`=Split, `P29`=Delisting |
| `scripcode`    | int    | BSE scrip code                                          |

**Response sample:**

```json
[
  {
    "scrip_code": 500209,
    "short_name": "INFY",
    "Ex_date": "25 Oct 2023",
    "Purpose": "Interim Dividend - Rs. - 18.0000",
    "RD_Date": "25 Oct 2023",
    "BCRD_FROM": "",
    "BCRD_TO": "",
    "ND_START_DATE": "18 Oct 2023",
    "ND_END_DATE": "25 Oct 2023",
    "payment_date": "",
    "exdate": "20231025",
    "long_name": "INFOSYS LTD."
  }
]
```

---

### 4. Quote — OHLC (`getScripHeaderData/w`)

Current day's trading data.

```
GET {API_BASE}/getScripHeaderData/w?scripcode={scripcode}
```

**Response:**

```json
{
  "PrevClose": 1523.05,
  "Open": 1525.0,
  "High": 1528.95,
  "Low": 1500.35,
  "LTP": 1505.45
}
```

**Notes:**
- All values are floats (not strings) — unlike `ComHeadernew/w`.
- Only current session data; no historical OHLC.

---

### 5. Results Snapshot (`TabResults_PAR/w`)

Recent quarterly and annual financial results.

```
GET {API_BASE}/TabResults_PAR/w?scripcode={scripcode}&tabtype={tabtype}
```

**Response sample:**

```json
{
  "currency_unit": "in Cr.",
  "periods": ["Dec-25", "Sep-25", "FY24-25"],
  "results_in_crores": {
    "fields": ["title", "Dec-25", "Sep-25", "FY24-25"],
    "data": [
      ["Revenue", "2,883.00", "2,650.00", "8,617.00"],
      ["Net Profit", "657.00", "691.00", "1,960.00"],
      ["EPS", "0.72", "0.76", "2.22"],
      ["Cash EPS", "0.78", "0.81", "2.27"],
      ["OPM %", "27.89", "31.17", "26.73"],
      ["NPM %", "22.79", "26.08", "22.75"]
    ]
  },
  "results_in_millions": { "...": "same structure" },
  "period_links": [
    {
      "FY": "FY24-25",
      "LQ": "Dec-25",
      "SQ": "Sep-25",
      "LFY": "https://www.bseindia.com/corporates/results.aspx?Code=543320&...",
      "LLQ": "...",
      "LSQ": "..."
    }
  ]
}
```

---

### 6. Price/Volume 12-Month (`StockReachGraph/w`)

```
GET {API_BASE}/StockReachGraph/w?scripcode={scripcode}&flag={flag}&fromdate={date}&todate={date}&seriesid=
```

---

### 7. Result Calendar (`Corpforthresults/w`)

Upcoming results announcements.

```
GET {API_BASE}/Corpforthresults/w?fromdate={date}&todate={date}&scripcode={scripcode}
```

---

### 8. Securities Listing (`ListofScripData/w`)

```
GET {API_BASE}/ListofScripData/w?scripcode={scripcode}&Group=&industry=&segment=EQ&status=Active
```

---

### 9. Circulars (`getDataAdvance_New/w`)

BSE regulatory circulars.

```
GET {API_BASE}/getDataAdvance_New/w
```

Parameters: `strTxtNoticeNo`, `strTxtDate`, `strTxtTodate`, `strScripcode`, `strDep`, `strSegment`, `subject`, `category`, `containgtext`

---

## Document Download URL Patterns

Annual report PDFs and all corporate filing attachments are downloaded from the BSE filing CDN.

The `ATTACHMENTNAME` field in the announcements response is a UUID filename (e.g., `aab502e1-3e05-4fdc-bc10-ecbb436cab8d.pdf`).

**URL construction:**

| Condition              | URL Pattern                                                                |
|------------------------|----------------------------------------------------------------------------|
| `OLD == 0` (recent)    | `https://www.bseindia.com/xml-data/corpfiling/AttachLive/{ATTACHMENTNAME}` |
| `OLD == 1` (historical)| `https://www.bseindia.com/xml-data/corpfiling/AttachHis/{ATTACHMENTNAME}`  |

**Known casing variant:** Some historical PDFs use `Attachhis` (lowercase 'h') instead of `AttachHis`. Both patterns are confirmed live in BSE search results. The connector must handle both.

**PDF download notes:**
- File size is in `Fld_Attachsize` (bytes); large annual reports are typically 5–50 MB.
- PDFs do not require authentication cookies — the CDN serves them publicly once URL is known.
- URL is stable: a historical annual report URL does not change after filing.

---

## Data Bulk Downloads

### BhavCopy (EOD equity data)

```
GET https://www.bseindia.com/download/BhavCopy/Equity/BhavCopy_BSE_CM_0_0_0_{YYYYMMDD}_F_0000.CSV
```

CSV containing all equity scrip OHLCV data for a trading day.

### Delivery Report

```
GET https://www.bseindia.com/BSEDATA/gross/{YYYY}/SCBSEALL{DDMM}.zip
```

---

## Field Mapping: BSE → Atlas Models

This mapping is used exclusively by `BSEParser`. No code outside `atlas/acquisition/connectors/bse_parser.py` should reference BSE field names.

| BSE Field          | Atlas Model Field        | Transformation                                      |
|--------------------|--------------------------|-----------------------------------------------------|
| `NEWSID`           | `announcement_id`        | UUID string, store as-is                            |
| `SCRIP_CD`         | `scrip_code`             | int                                                 |
| `SLONGNAME`        | `company_name`           | str                                                 |
| `SUBCATNAME`       | `subcategory`            | str                                                 |
| `HEADLINE`         | `headline`               | str                                                 |
| `DT_TM`            | `announced_at`           | Parse as IST (`Asia/Kolkata`), store UTC            |
| `News_submission_dt`| `submitted_at`          | Parse as IST, store UTC                             |
| `ATTACHMENTNAME`   | `attachment_filename`    | str (UUID.pdf)                                      |
| `OLD`              | *(internal)*             | `0` → `AttachLive`; `1` → `AttachHis` URL segment  |
| `PDFFLAG`          | *(filter)*               | Skip records where `PDFFLAG != 1`                   |
| `Fld_Attachsize`   | `file_size_bytes`        | int                                                 |
| `TotalPageCnt`     | *(pagination)*           | Total pages for cursor management                   |
| `SecurityId`       | `ticker`                 | From `ComHeadernew/w`                               |
| `ISIN`             | `isin`                   | str                                                 |
| `SecurityCode`     | `scrip_code`             | str → int                                           |
| `FaceVal`          | `face_value`             | str → Decimal                                       |
| `PrevClose`        | `previous_close`         | float                                               |
| `LTP`              | `last_traded_price`      | float                                               |

---

## Assumptions

1. **Session-based auth is sufficient.** A single `requests.Session` with a warm-up GET to the BSE homepage acquires all cookies needed. No OAuth, no API keys, no login form.

2. **`OLD` field reliably identifies the CDN path.** `0` → `AttachLive`, `1` → `AttachHis`. This has not been independently verified in production; if downloads fail, check this assumption first.

3. **Annual reports are in `AGM/EGM` category.** The BSE website places annual report filings under `strCat=AGM/EGM`. Individual records are identified by `SUBCATNAME` containing `"Annual Report"`. There is no dedicated annual report API endpoint.

4. **Timestamps are IST without timezone marker.** `DT_TM` values like `"2023-10-20T23:44:22.95"` are in IST (`Asia/Kolkata`, UTC+5:30). The API returns no timezone suffix. The parser must assume IST.

5. **Pagination is 22 records per page.** Based on the `TotalPageCnt` semantics inferred from sample data. Actual page size should be verified against a live response before coding the pagination loop.

6. **PDFs are publicly accessible without cookies.** The filing CDN (`xml-data/corpfiling/...`) appears to serve PDFs without requiring a session. This must be verified before removing cookie injection from the download step.

---

## Known Risks

| Risk                           | Severity | Mitigation                                                   |
|--------------------------------|----------|--------------------------------------------------------------|
| API returns 301 without session| High     | Always warm up session before first API call                 |
| `AttachHis`/`Attachhis` casing | Medium   | Try both; log which succeeded                                |
| Rate limiting (no official spec)| Medium  | Default to 2 RPS (`ATLAS_HTTP_RATE_LIMIT_RPS`); back off on 429 |
| API shape change (unofficial)  | Medium   | All parsing in `BSEParser`; field access via `get()` not `[]` |
| IST timestamps without marker  | Low      | Always parse with explicit `Asia/Kolkata` tzinfo            |
| Large PDF files (up to 50 MB)  | Low      | Stream download; do not load into memory                    |
| `PDFFLAG` not always 1         | Low      | Filter before constructing download URL                      |
| `null` values in metadata      | Low      | All optional fields parsed with `.get(key)` defaulting to `None` |

---

## Phase 2 Prerequisites (before any implementation)

The following must be resolved before designing the connector's domain models:

- [ ] **Verify `OLD` field semantics** — confirm `0` vs `1` maps to `AttachLive` vs `AttachHis` by testing a known annual report filing.
- [ ] **Verify pagination page size** — confirm records per page for `AnnSubCategoryGetData/w`.
- [ ] **Verify PDF accessibility without session cookies** — try downloading a filing PDF without a browser session.
- [ ] **Sample real TCS annual report response** — run `AnnSubCategoryGetData/w` with `strscrip=532540`, `strCat=AGM/EGM` and record exact response fields for FY2023-24 annual report.
- [ ] **Confirm `SUBCATNAME` value for annual reports** — the exact string used in live data may differ from the assumed `"Annual Report"`.

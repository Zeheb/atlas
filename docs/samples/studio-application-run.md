# Atlas — sample outputs

Captured 2026-08-16 against the **TCS** repository.

Every command below was run once, from `C:/Users/makan/Development/Atlas`, and its
output pasted verbatim — no editing, tidying, truncation or reformatting. Where a run
failed, the failure is the sample. No source code was changed to produce anything here.

Build for every run in this file:

```
digest    3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
code_rev  m2.4.1-115-g60442f5
```

**Two things to know before reading.**

The flag shapes in the capture brief (`atlas query ownership --company TCS`) do not exist.
`atlas query` takes ticker and query as positionals: `atlas query TCS ownership`. Commands
below are the real ones, taken from `--help`.

The reasoning-layer runs (1b, 2, 3, 5) were attempted **three times against two providers**,
and the document records all three passes rather than only the one that worked:

* **Pass 1 — OmniRoute, not running.** Connection refused. One clean error line.
* **Pass 2 — OmniRoute, started.** Connection accepted, no response, 60-second read timeout,
  raw traceback.
* **Pass 3 — Gemini (`gemini-2.5-flash`).** All four exited 0. This is the model the M1.5
  evaluation baseline was frozen against.

Pass 3 was run by setting `ATLAS_LLM_PROVIDER` and `ATLAS_REASONING_MODEL` as environment
variables for those four commands only; `.env` was not modified and still selects omniroute.

The deterministic layer (runs 1a, 1c, 4, 4b, 6) needs no provider and was captured once.

---

## Run 1a — EXPECTED GOOD: ownership answered from structured facts

Command: `atlas query TCS ownership`

```
Ownership Structure  [TCS]
==========================

Shareholding Pattern (last 8 quarters)
--------------------------------------
Period    Promoter (QoQ)  FPI (QoQ)  DII     MF     Public  Pledged
--------  --------------  ---------  ------  -----  ------  -------
Mar 2026  71.77% (-)      9.66% (-)  13.41%  5.77%  28.23%  0.00%  

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
```

**What actually happened.** Clean, correctly typed, pinned to a build. It is also a
one-row table where the header promises eight quarters: the corpus holds exactly one
shareholding pattern for TCS, so there is no prior quarter to difference against. Both
QoQ columns print `(-)` rather than a fabricated `0.00%`, which is the honest rendering
of "no comparison available" — but the query still runs and still reports, so a reader
skimming for a trend gets a single point and must notice the `(-)` themselves.

---

## Run 1b — EXPECTED GOOD: same territory, through the reasoning layer

Command: `atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?"`

```
Error: Couldn't connect to OmniRoute at http://localhost:20128. Is OmniRoute running?
```

Exit code 1.

**What actually happened.** Failed closed on the provider connection. No partial answer,
no fallback to an ungrounded guess, no stack trace — one line naming the host, the port
and the thing to check. Whether the answer itself would have been good is not established
by this run.

---

## Run 1c — EXPECTED GOOD: the same question, deterministically

Command: `atlas query TCS capital`

```
Capital Allocation Events  [TCS]
================================

Dividends
---------
Date        Type     Per Share    Record Date
----------  -------  -----------  -----------
2026-04-09  final    31.00/share  -          
2026-04-09  final    31.00/share  -          
2024-10-10  interim  10.00/share  2024-10-18 
2024-10-10  interim  10.00/share  2024-10-18 

Buybacks
--------
Date        Sub-type        Amount     Price/Share
----------  --------------  ---------  -----------
2023-12-13  extinguishment  -          -          
2023-12-13  announcement    17,000 cr  4,150/share
2023-11-17  announcement    17,000 cr  4,150/share
2020-12-09  schedule        -          -          
2020-11-20  unknown         -          -          

Acquisitions & Incorporations
-----------------------------
Date        Target                                        Consideration  EV                 Stake 
----------  --------------------------------------------  -------------  -----------------  ------
2025-12-18  3-101-951221 SOCIEDAD ANONIMA                 subscription   -                  100.0%
2025-12-17  TATA CONSULTANCY SERVICES BT Private Limited  subscription   -                  100.0%
2025-12-16  Trident LE LLC                                subscription   -                  100.0%
2025-12-16  TCS North America Corporation                 subscription   -                  100.0%
2025-12-10  Coastal Cloud Holdings, LLC                   cash           700.0 usd_million  100.0%
2025-12-10  Coastal Cloud Holdings, LLC                   cash           700.0 usd_million  100.0%
2025-10-30  HyperVault AI Data Center Limited             subscription   7.5 crore_inr      100.0%

Investments
-----------
Date        Target                             Amount            
----------  ---------------------------------  ------------------
2025-11-20  HyperVault AI Data Center Limited  18,000.0 crore_inr

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
```

**What actually happened.** This is the strongest output in the set — typed events with
dates, consideration types, units carried explicitly (`usd_million` vs `crore_inr`, never
mixed), and a real acquisition trail. It also has a visible defect the brief did not
anticipate: **duplicate rows.** The 2026-04-09 final dividend appears twice, the
2024-10-10 interim twice, and Coastal Cloud twice. The 17,000 cr buyback appears at both
2023-11-17 and 2023-12-13, which is probably two genuine filings (announcement, then
extinguishment) rather than a duplicate, but the table gives a reader no way to tell those
two cases apart. Anyone totalling this column by eye double-counts. Not investigated
further — per the brief, this is a capture, not a fix.

---

## Run 2 — EXPECTED PARTIAL: a quarterly question over a Q2/Q4-only transcript corpus

Command: `atlas ask TCS "What has changed since last quarter?"`

```
Error: Couldn't connect to OmniRoute at http://localhost:20128. Is OmniRoute running?
```

Exit code 1.

**What actually happened.** The run never reached the reasoning layer, so **the thing this
run was designed to test — whether Atlas discloses that "last quarter" is really a
six-month window — is not established.** Recording that as unknown rather than inferring
it. The underlying corpus gap is independently confirmed: TCS holds 6 earnings
transcripts, all Q2/Q4, so every Q1 and Q3 call is missing.

---

## Run 3 — EXPECTED OUT-OF-CORPUS: peer valuation and broker views

Command: `atlas ask TCS "How does TCS's valuation compare with its peers, and what are brokerages saying about the stock?"`

```
Error: Couldn't connect to OmniRoute at http://localhost:20128. Is OmniRoute running?
```

Exit code 1.

**What actually happened.** Same failure, same place. Whether Atlas refuses cleanly,
hedges, or fabricates on an out-of-corpus question **is not established by this run.**
What can be said without the LLM: `atlas ask --help` documents "out-of-scope questions
(e.g. valuation) are declined rather than guessed", and the refusal path is exercised by
the `honest_negative` expected-behaviour class in the eval harness. That is a claim about
design and test coverage, not an observation of this run.

---

## Run 4 — KNOWN-BAD: the risk-factors path

Command: `atlas query TCS risks`

```
Recurring Risk Factors  [TCS]
=============================

Risk Factors (deduplicated, most-recent first)
----------------------------------------------
Period    Risk Factor                                                                                                                                                   
--------  --------------------------------------------------------------------------------------------------------------------------------------------------------------
Mar 2026  AI ecosystem play: To strengthen                                                                                                                              
Mar 2026  AI‑driven systems that combine                                                                                                                                
Mar 2026  Building a Future-Ready Talent                                                                                                                                
Mar 2026  Data Layer: Unlocking Enterprise Intelligence                                                                                                                 
Mar 2026  Making AI Real for our clients: True                                                                                                                          
Mar 2026  Models: From Foundation Models to Domain Intelligence                                                                                                         
Mar 2026  Redefining Services: We established a                                                                                                                         
Mar 2026  These will boost TCS’ Salesforce                                                                                                                              
Mar 2026  tcsAI: We democratised AI access                                                                                                                              
Mar 2025  Tata Consumer Products Limited (C) (NED)                                                                                                                     
Mar 2025  The Indian Hotels Company Limited (C) (NED)                                                                                                                  
Mar 2025  The Tata Power Company Limited (C) (NED)                                                                                                                     
Mar 2025  Excludes provision (FY 2021) and settlement (FY 2024) of legal claim.                                                                                         
Mar 2025  Further, none of the Independent Directors serve                                                                                                              
Mar 2025  Tata Chemicals Limited (C) (NED)                                                                                                                              
Mar 2025  Tata Motors Limited (C) (NED)                                                                                                                                 
Mar 2025  Tata Steel Limited (C) (NED)                                                                                                                                  
Mar 2025  The necessary quorum was present for all the                                                                                                                  
Mar 2024  Excludes provision (in FY 2021) and settlement (in FY 2024) of legal claim                                                                                    
Mar 2024  Excludes settlement of legal claim                                                                                                                            
Mar 2024  Excludes settlement of legal claim in FY 2024                                                                                                                 
Mar 2024  Samir Seksaria (Chief Financial Oﬃcer), is also a member of the Committee                                                                                     
Mar 2023  Excluding provision towards legal claim                                                                                                                       
Mar 2023  He served as the CFO of TCS from February 2017 until his                                                                                                      
Mar 2023  Samir Seksaria (Chief Financial Oﬃcer) is also a member of                                                                                                    
Mar 2023  includes multiple investors in group meetings                                                                                                                 
Mar 2022  *Appointed as a member of this Committee                                                                                                                      
Mar 2022  Aarthi Subramanian ceased to be a member of the NRC w.e.f. October 8, 2021                                                                                    
Mar 2022  Ceased to be a member of the Committee                                                                                                                        
Mar 2022  Ceased to be a member of the Committee consequent                                                                                                             
Mar 2022  Climate change                                                                                                                                                
Mar 2022  Employee Stock Purchase Scheme                                                                                                                                
Mar 2022  Excluding provision towards legal claim.                                                                                                                      
Mar 2022  includes shares held jointly with relative                                                                                                                    
Mar 2021  APAC - 8 (China - 5, Philippines -2, Singapore -1 )                                                                                                           
Mar 2021  Best in class profitability and strong balance sheet provide greater ability to invest                                                                        
Mar 2021  Consistently high shareholder returns enhances relationship capital                                                                                           
Mar 2021  Enabled new business models, new revenue streams                                                                                                              
Mar 2021  Expanded the addressable market                                                                                                                               
Mar 2021  Includes final dividend of erstwhile TCS e-Serve Limited and erstwhile                                                                                        
Mar 2021  J. Towers, Dalal Street, Mumbai 400 001                                                                                                                       
Mar 2021  Shareholding is consolidated based on Permanent Account Number (PAN) of                                                                                       
Mar 2021  Strong growth creates more jobs, and career growth opportunities for employees                                                                                
Mar 2021  the date of appointment is as per the MCA Portal.                                                                                                             
Mar 2020  * CSR Policy (https://on.tcs.com/Global-CSR-Policy)                                                                                                           
Mar 2020  ** Environment Policy (https://on.tcs.com/Environmental-Policy)                                                                                               
Mar 2020  Excluding the impact of one-time employee reward.                                                                                                             
Mar 2020  TATA Code of Conduct (https://on.tcs.com/Tata-Code-Of-Conduct)                                                                                                
Mar 2020  emissions have reduced by 6% YoY27, for the fourth                                                                                                            
Mar 2020  emissions have reduced by 6% YoY28, for the fourth                                                                                                            
Mar 2019  ** 	 Appointed as an Additional and Independent Director w.e.f. December 18, 2018.                                                                            
Mar 2019  ***	 Appointed as an Additional and Independent Director w.e.f. January 10, 2019.                                                                             
Mar 2019  APTOnline Limited                                                                                                                                             
Mar 2019  C-Edge Technologies Limited                                                                                                                                   
Mar 2019  Chairman of the Committee                                                                                                                                     
Mar 2019  TCS Foundation                                                                                                                                                
Mar 2019  TCS e-Serve International Limited                                                                                                                             
Mar 2019  Tata Consultancy Services (Africa) (PTY) Ltd.                                                                                                                 
Mar 2019  Tata Consultancy Services (South Africa) (PTY) Ltd.                                                                                                           
Mar 2019  Tata Sons Private Limited                                                                                                                                     
Mar 2018  Chandrasekaran                                                                                                                                                
Mar 2018  **	 Relinquished the office of Executive Director and appointed as an Additional Director in non-executive                                                    
Mar 2018  ***	 Appointed as an Additional and Independent Director w.e.f. January 11, 2018.                                                                             
Mar 2018  Tata Consultancy Services Asia Pacific Pte Ltd.                                                                                                               
Mar 2018  Tata Consultancy Services Malaysia Sdn Bhd                                                                                                                    
Mar 2018  Tata Consultancy Services Qatar S. S. C.                                                                                                                      
Mar 2018  Tata Consultancy Services Saudi Arabia                                                                                                                        
Mar 2018  The percentage increase in the median remuneration of employees in the financial year: 0.57%, reflecting an                                                   
Mar 2017  Earnings before interest, tax, depreciation and amortization (EBITDA): The EBITDA aggregated ` 32,311 crore in FY 2017 (` 30,677 crore in FY 2016) – a        
Mar 2017  Earnings per share (EPS): EPS aggregated ` 133.41 in FY 2017 (` 123.18 in FY 2016) – a growth of 8.3%.                                                        
Mar 2017  Profit after tax (PAT): PAT aggregated ` 26,289 crore in FY 2017 (` 24,270 crore in FY 2016) – a growth of 8.3%.                                              
Mar 2017  Profit before tax (PBT): PBT aggregated ` 34,513 crore in FY 2017 (` 31,840 crore in FY 2016) – a growth of 8.4%.                                             
Mar 2017  Revenue: The revenue of the Company aggregated ` 117,966 crore in FY 2017 (` 108,646 crore in FY 2016), registering a growth of 8.6%.                         
Mar 2017  The increase in ’Investments carried at fair value through P&L’ from ` 1,767 crore in FY 2016 to ` 19,692 crore in FY 2017  is due to net purchase of mutual  
Mar 2017  The net decrease of ` 484 crore in ’Investment carried at amortized cost’ from `632 crore in FY 2016 to ` 148 crore in FY 2017 is primarily due to redemption 
Mar 2017  increase in investments of ` 19,186 crore primarily due to investment in mutual funds and government securities during FY 2017                                
Mar 2017  offset by decrease in bank deposits by ` 2,453 crore, decrease in inter-corporate deposits by ` 1,618 crore and decrease in cash and bank balances by         
Mar 2017  ’Investments carried at fair value through OCI’ increased from ` 20,423 crore in FY 2016 to ` 22,140 crore in FY 2017. The increase of ` 1,717 crore is due to
Mar 2016  0.028                                                                                                                                                         
Mar 2016  0.096                                                                                                                                                         
Mar 2016  0.297                                                                                                                                                         
Mar 2016  0.379                                                                                                                                                         
Mar 2016  1.167                                                                                                                                                         
Mar 2016  Adjusted for 1:1 bonus issue in 2006 and 2009                                                                                                                 
Mar 2016  In the following discussions, the impact of the one-time employee reward on cash ﬂow from operating activities                                                
Mar 2016  Promoters                                                                                                                                                     
Mar 2016  Since this information is for part of the year, the same is not comparable.                                                                                   
Mar 2016  The increase was primarily due to:                                                                                                                            
Mar 2016  cloud based sales and marketing transformation,                                                                                                               
Mar 2016  excluding impact of one-time employee reward                                                                                                                  
Mar 2016  excluding one-me employee reward                                                                                                                             
Mar 2016  excluding one-meemployee reward                                                                                                                              
Mar 2016  excluding payment of one me employee reward                                                                                                                  
Mar 2016  excluding-one me employee reward                                                                                                                             
Mar 2016  mainly on account of operating lease liabilities                                                                                                              
Mar 2016  omni-channel supply chain solutions, d) next generation                                                                                                       
Mar 2014  ARCH  	 .OTE  TO THE CONSOLIDATED lNANCIAL statements gives details of movements in the hedging                                                     
Mar 2014  The increase of 2.33% is mainly due to (1) increase                                                                                                           
Mar 2014  The increase was spread across all asset groups,                                                                                                              
Mar 2012  Advance planning for visas                                                                                                                                    
Mar 2012  Broad-basing the number of key clients by gradually moving                                                                                                    
Mar 2012  Broadening the Company’s service offerings to become an                                                                                                       
Mar 2012  Building greater client intimacy by optimising operating metrics                                                                                              
Mar 2012  Diversiﬁ cation across geographies with focus on emerging                                                                                                     
Mar 2012  Diversiﬁ cation of product and services offerings                                                                                                             
Mar 2012  Greater focus                                                                                                                                                 
Mar 2012  Increased local recruitment                                                                                                                                   
Mar 2012  Leveraging the GNDM™                                                                                                                                          
Mar 2012  Working through industry bodies to articulate the Company’s                                                                                                   
Mar 2011  As a percentage of revenues these expenses                                                                                                                    
Mar 2011  Some of the agile processes and technologies                                                                                                                  
Mar 2011  The decrease of 1.88% was primarily due to:                                                                                                                   
Mar 2011  This is primarily due to increase of proﬁts in two                                                                                                            
Mar 2011  and has contributed 9.69% of total segment result                                                                                                             
Mar 2011  due to sustained demand                                                                                                                                       
Mar 2011  mostly related to construction / improvement of                                                                                                               

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
```

**What actually happened.** 116 rows, and close to none of them are risks.

Worth being precise about the failure mode, because it is more interesting than "the
extraction is noisy". The rows are not garbage — nearly every one is a real sentence
correctly lifted from a real annual report. What is wrong is the *label*. The extractor is
picking up: the Tata group directorship list (`Tata Motors Limited (C) (NED)`), audit
committee membership lines, footnote disclaimers about a legal-claim provision, a postal
address (`J. Towers, Dalal Street, Mumbai 400 001`), policy hyperlinks, the FY2017 MD&A
financial summary in full sentences, and five bare decimals from Mar 2016 (`0.028`,
`0.096`, …) that are almost certainly a stripped table column.

Two further tells. The Mar 2026 block is the *strategy* section — `tcsAI: We democratised
AI access`, `Data Layer: Unlocking Enterprise Intelligence` — filed as risk. And the
"deduplicated" claim in the header is doing nothing useful: `excluding one-me employee
reward`, `excluding one-meemployee reward` and `excluding-one me employee reward` all
survive as distinct rows, because they differ by exactly the ligature damage
(`ti` → `-`) that the PDF layer introduced. Dedup runs on strings, after extraction, so it
cannot see that these are one sentence.

Many rows are also truncated mid-clause (`AI ecosystem play: To strengthen`,
`Further, none of the Independent Directors serve`), so even a correctly-classified row
frequently does not carry a complete thought.

One more thing worth recording, found while verifying this file was byte-exact: **the
output contains raw control characters** — `0x07` (BEL) and `0x02` appear inside the text,
which is why `grep` classifies this document as binary rather than text. They survive from
the PDF layer, through extraction, into the assertion store, and out to the terminal
unfiltered. The `Mar 2014` row (`ARCH  <TAB> .OTE  TO THE CONSOLIDATED lNANCIAL statements`)
is the visible tip of the same damage: dropped leading capitals (`.OTE` for `NOTE`,
`lNANCIAL` for `FINANCIAL`) plus embedded control bytes. Nothing downstream sanitises this.

Net: `risk_recurrence` and anything built on this array is decorative. This matches what
the README already says about the path, at greater specificity.

---

## Run 4b — KNOWN-BAD, downstream: what recurrence does with that array

Command: `atlas query TCS risk_recurrence`

```
Recurring Risk Factors Across Periods  [TCS]
============================================

Risks appearing in 2+ distinct reporting periods
------------------------------------------------
Occurrences  Most Recent Period  Risk Factor                            
-----------  ------------------  ---------------------------------------
2            Mar 2023            Excluding provision towards legal claim
2            Mar 2018            Chandrasekaran                         

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
```

**What actually happened.** Two rows. One is a footnote disclaimer. The other is a person's
surname. Neither is a risk.

This is run 4's defect propagating one layer up, and it is worth showing separately because
the failure changes character on the way. Downstream of 116 noisy rows, the recurrence
query is a well-behaved piece of code doing exactly its job — group by text, keep anything
appearing in 2+ periods — and the output is confidently formatted, correctly counted, and
completely wrong. "Chandrasekaran appears as a recurring risk factor across two reporting
periods" is a sentence Atlas will state without hedging.

The ligature damage noted in run 4 is also visible here as a *suppression*: the three
`one-me employee reward` variants are one real recurring string that dedup could not
collapse, so none of them cleared the 2+ threshold. The output is therefore both
false-positive and false-negative at once.

Note this query is not listed in `atlas query --help`, which names 12 queries; the engine
implements 18 and dispatches them all. The help text is stale, not the engine.

---

## Run 5 — DRILL-THROUGH: claim back to source excerpt

Command: `atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?" --show-evidence`

```
Error: Couldn't connect to OmniRoute at http://localhost:20128. Is OmniRoute running?
```

Exit code 1.

**What actually happened.** `--show-evidence` hydrates the excerpt behind each citation in
an LLM answer, so with no answer there is nothing to drill through. The drill-to-source
path is **not demonstrated by this capture.** The deterministic equivalent —
`atlas query TCS drilldown <EVIDENCE_ID>`, which takes an id from the Sources column of
any table — was not run; it is not the same path and substituting it would have
misrepresented what was tested.

---

## Run 6 — build fingerprint

Command: `atlas fingerprint show`

```
digest    3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
code_rev  m2.4.1-115-g60442f5

ontology_version       1.0
parser_version         2.0
shared_parser_version  1.0
builder_version        1.0

analyzer_versions (11)
  acquisition              1.0
  agm_notice               1.0
  annual_report            3.4
  board_outcome            1.1
  brsr                     1.0
  buyback                  1.0
  credit_rating_report     1.0
  earnings_transcript      2.3
  financial_results        1.1
  investor_presentation    2.1
  shareholding_pattern     1.1
```

**What actually happened.** Every component that can change an extracted number, with its
version, plus the digest those versions hash to. The `Atlas 3436f960…` footer on runs 1a,
1c and 4 is this same digest, so each of those tables is pinned to this exact build. This
is the machinery that makes the defects above tractable: when the risk-factor rows change,
`annual_report 3.4` moving is what explains it.

---

## What this capture does and does not show

Established here: the deterministic query layer works, carries units and dates correctly,
prints build-pinned output, and degrades honestly where the corpus is thin (run 1a's `(-)`
columns). Also established: two real defects, one known and one not. The risk-factors path
is a misclassification problem rather than a parsing problem (run 4), and it propagates
into a downstream query that states a surname as a recurring risk without hedging
(run 4b); and `atlas query capital` emits duplicate rows that a reader would silently
double-count (run 1c) — the latter was not on the brief's list and surfaced only because
the output was read closely.

Not established: anything about the reasoning layer. The provider was down, so the three
runs designed to probe disclosure of a window gap, refusal on out-of-corpus questions, and
drill-to-source all returned the same connection error. They are recorded as failures
rather than retried or substituted, per the capture rules.

---

# Second pass — OmniRoute started

The gateway was started after the runs above and confirmed listening on 20128
(`netstat` shows `LISTENING`, and an HTTP probe of `/` returns 307). Runs 1b, 2, 3 and 5
were then repeated. The first-pass failures above are left exactly as captured; this is an
addition, not a replacement.

**All four failed again, identically, for a different reason.** The gateway now accepts the
connection and then never answers: `atlas` waits 60 seconds and raises. The four
tracebacks are byte-for-byte identical to each other — verified with `diff` — so one is
reproduced in full below and the other three are recorded by reference rather than pasted
four times.

Command (run 1b): `atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?"`

```
Traceback (most recent call last):
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connectionpool.py", line 534, in _make_request
    response = conn.getresponse()
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connection.py", line 571, in getresponse
    httplib_response = super().getresponse()
  File "C:\Users\makan\AppData\Local\Programs\Python\Python314\Lib\http\client.py", line 1459, in getresponse
    response.begin()
    ~~~~~~~~~~~~~~^^
  File "C:\Users\makan\AppData\Local\Programs\Python\Python314\Lib\http\client.py", line 336, in begin
    version, status, reason = self._read_status()
                              ~~~~~~~~~~~~~~~~~^^
  File "C:\Users\makan\AppData\Local\Programs\Python\Python314\Lib\http\client.py", line 297, in _read_status
    line = str(self.fp.readline(_MAXLINE + 1), "iso-8859-1")
               ~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^
  File "C:\Users\makan\AppData\Local\Programs\Python\Python314\Lib\socket.py", line 729, in readinto
    return self._sock.recv_into(b)
           ~~~~~~~~~~~~~~~~~~~~^^^
TimeoutError: timed out

The above exception was the direct cause of the following exception:

Traceback (most recent call last):
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\adapters.py", line 696, in send
    resp = conn.urlopen(
        method=request.method,
    ...<9 lines>...
        chunked=chunked,
    )
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connectionpool.py", line 842, in urlopen
    retries = retries.increment(
        method, url, error=new_e, _pool=self, _stacktrace=sys.exc_info()[2]
    )
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\util\retry.py", line 498, in increment
    raise reraise(type(error), error, _stacktrace)
          ~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\util\util.py", line 39, in reraise
    raise value
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connectionpool.py", line 788, in urlopen
    response = self._make_request(
        conn,
    ...<10 lines>...
        **response_kw,
    )
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connectionpool.py", line 536, in _make_request
    self._raise_timeout(err=e, url=url, timeout_value=read_timeout)
    ~~~~~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\urllib3\connectionpool.py", line 367, in _raise_timeout
    raise ReadTimeoutError(
        self, url, f"Read timed out. (read timeout={timeout_value})"
    ) from err
urllib3.exceptions.ReadTimeoutError: HTTPConnectionPool(host='localhost', port=20128): Read timed out. (read timeout=60.0)

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "<frozen runpy>", line 203, in _run_module_as_main
  File "<frozen runpy>", line 88, in _run_code
  File "C:\Users\makan\Development\Atlas\.venv\Scripts\atlas.exe\__main__.py", line 10, in <module>
    sys.exit(cli())
             ~~~^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\click\core.py", line 1569, in __call__
    return self.main(*args, **kwargs)
           ~~~~~~~~~^^^^^^^^^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\click\core.py", line 1490, in main
    rv = self.invoke(ctx)
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\click\core.py", line 1970, in invoke
    return _process_result(sub_ctx.command.invoke(sub_ctx))
                           ~~~~~~~~~~~~~~~~~~~~~~^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\click\core.py", line 1353, in invoke
    return ctx.invoke(self.callback, **ctx.params)
           ~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\click\core.py", line 907, in invoke
    return callback(*args, **kwargs)
  File "C:\Users\makan\Development\Atlas\src\atlas\cli.py", line 1301, in ask_cmd
    result = ask(Question(raw_text=question, subject_ref=subject), context, client)
  File "C:\Users\makan\Development\Atlas\src\atlas\reasoning\ask.py", line 80, in ask
    raw = client.complete(
        system=system_prompt,
        user=build_prompt(question, context),
    )
  File "C:\Users\makan\Development\Atlas\src\atlas\reasoning\llm\omniroute.py", line 79, in complete
    response = requests.post(
        f"{self._base_url}/v1/messages",
    ...<8 lines>...
        timeout=self._timeout,
    )
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\api.py", line 134, in post
    return request("post", url, data=data, json=json, **kwargs)
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\api.py", line 71, in request
    return session.request(method=method, url=url, **kwargs)
           ~~~~~~~~~~~~~~~^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\sessions.py", line 651, in request
    resp = self.send(prep, **send_kwargs)
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\sessions.py", line 784, in send
    r = adapter.send(request, **kwargs)
  File "C:\Users\makan\Development\Atlas\.venv\Lib\site-packages\requests\adapters.py", line 742, in send
    raise ReadTimeout(e, request=request)
requests.exceptions.ReadTimeout: HTTPConnectionPool(host='localhost', port=20128): Read timed out. (read timeout=60.0)
```

Exit code 1. Runs 2, 3 and 5 produced this same output byte-for-byte.

**What actually happened, and why the second failure is more interesting than the first.**

Compare the two passes. Connection *refused* produced one clean line naming host, port and
remedy — a handled transport error. Connection *accepted then silent* produced 98 lines of
raw traceback through `urllib3`, `requests`, `click` and `runpy`. The comment at
[cli.py:1303](../../src/atlas/cli.py) explicitly reasons about transports being
"unreachable at call time (Ollama, OmniRoute, ...)", so the refused case was anticipated
and handled; the read-timeout case was not. Same subsystem, same user, two very different
experiences depending on *how* the provider is unavailable.

Two contributing facts, both read from source without changing it:

* `_DEFAULT_TIMEOUT_SECONDS = 60.0` in `omniroute.py` is a module constant, and
  `OmniRouteClient.from_settings()` never passes `timeout=`, so the constructor default
  always wins for this transport.
* `Settings` already carries `http_timeout_seconds` ([settings.py:71](../../src/atlas/config/settings.py)).
  Nothing connects it to this client. A configuration knob for exactly this exists and
  this transport ignores it, so there is no way to wait longer without editing code.

Per the capture rules, no code was edited to raise the timeout, and no run was repeated a
third time. Whether the gateway is genuinely slow for the `test_cc` model or wedged is not
determined here — from Atlas's side the two are indistinguishable, which is itself part of
the finding.

**Standing conclusion after two passes.** The reasoning layer remains undemonstrated. What
the two passes together do demonstrate is the layer's failure behaviour: it never
fabricates an answer when the provider is unavailable, but it only *reports* that
gracefully for one of the two ways unavailability shows up.

---

# Third pass — Gemini

Provider switched to `google_ai_studio` / `gemini-2.5-flash`, set as environment variables
for these four runs only. **`.env` was not edited** and still selects omniroute. This is
the model the M1.5 evaluation baseline was frozen against, so these outputs are comparable
to the published eval numbers.

Runs 1b, 2, 3 and 5 repeated a third time. All four exited 0. Both earlier passes stay in
the document.

## Run 1b (third pass) — EXPECTED GOOD, through the reasoning layer

Command: `atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?"`

```
[FACT] TCS declared an interim dividend of 10.0 per equity share on October 10, 2024. (confidence: high) [bse-news-373a3674-df22-42d5-ac50-1d77941355cd, bse-news-9946569a-50a1-4e19-a987-5f5bdce8f06a, bse-news-c8be78c9-b40f-486a-853b-825e1919c160]
[FACT] TCS recommended a final dividend of 31.0 per share on April 9, 2026. (confidence: high) [bse-news-6f1cf0de-6044-4195-8d91-f479cbfa778a, bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83, bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956]
[FACT] TCS announced a buyback on November 17, 2023, and December 13, 2023, with shares extinguished on December 13, 2023. (confidence: high) [bse-news-4d4a5575-3bbf-40c5-9e32-613f51c84105, bse-news-6233389e-6f1b-4545-a03b-d3fca0b40cfb, bse-news-8b2b0027-67c5-4eb6-8012-153d22b30750]
[FACT] A buyback was announced on November 20, 2020, with an offer period from December 18, 2020, to January 1, 2021. (confidence: high) [bse-news-853000ae-953d-4891-a58d-074e435e0de5, bse-news-b1dc2c18-b69e-41c1-8e44-0614630cea37]
[FACT] The total monetary value of the buybacks is not specified in the provided evidence. (confidence: high)
    ? not known: Total monetary value of buybacks.

Overall confidence: high

Sources:
  - bse-news-373a3674-df22-42d5-ac50-1d77941355cd
  - bse-news-4d4a5575-3bbf-40c5-9e32-613f51c84105
  - bse-news-6233389e-6f1b-4545-a03b-d3fca0b40cfb
  - bse-news-6f1cf0de-6044-4195-8d91-f479cbfa778a
  - bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83
  - bse-news-853000ae-953d-4891-a58d-074e435e0de5
  - bse-news-8b2b0027-67c5-4eb6-8012-153d22b30750
  - bse-news-9946569a-50a1-4e19-a987-5f5bdce8f06a
  - bse-news-b1dc2c18-b69e-41c1-8e44-0614630cea37
  - bse-news-c8be78c9-b40f-486a-853b-825e1919c160
  - bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3 · 59 documents
```

**What actually happened.** Every claim is atomic, dated, confidence-tagged and carries the
evidence ids behind it, and the whole answer is pinned to the build. The `? not known` line
is the completeness gate working: rather than dropping the part of the question it cannot
answer, it names the gap explicitly.

**But that gap is wrong, and comparing layers is how you can tell.** Run 1c —
`atlas query capital`, same repository, same build — prints `17,000 cr` at `4,150/share`
for the 2023 buyback. The reasoning layer says the total monetary value "is not specified
in the provided evidence" and marks that with *high* confidence. It is specified; it is
sitting in the profile one query away.

The footer names the cause: **`59 documents`**, against 140 in the assertion store. The
grounding context is a subset, so the reasoning layer's "not in the evidence" means "not in
the 59 documents I was given" — but it renders as a statement about the corpus. This is a
more dangerous failure than run 4's visible noise, because the output is well-formed,
confident, and wrong in a direction a reader cannot detect without cross-checking the
deterministic layer.

## Run 2 (third pass) — EXPECTED PARTIAL: the quarterly window question

Command: `atlas ask TCS "What has changed since last quarter?"`

```
Atlas cannot answer this question.
Reason: The model returned output that could not be parsed.

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3 · 59 documents
```

Exit code 0.

**What actually happened.** The model produced something the response parser rejected, and
Atlas surfaced that as a refusal rather than passing malformed content through. Failing
closed on an unparseable response is correct behaviour, and note the exit code is 0 — this
is a *refusal*, a normal outcome, not an error.

**The window-disclosure question is still not established, now across all three passes.**
Whether Atlas would have disclosed that "last quarter" spans six months for a Q2/Q4-only
transcript corpus is unknown: pass 1 and 2 never reached the model, and pass 3 reached it
and could not read the reply. Per the capture rules this was not re-run. Three attempts,
three different failure modes, no answer to the actual question — which is itself a fair
description of the layer's current reliability.

## Run 3 (third pass) — EXPECTED OUT-OF-CORPUS

Command: `atlas ask TCS "How does TCS's valuation compare with its peers, and what are brokerages saying about the stock?"`

```
Atlas cannot answer this question.
Reason: The provided evidence does not contain information about TCS's valuation metrics, a comparison of its valuation with peers, or any brokerage opinions or ratings on the stock.

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3 · 59 documents
```

Exit code 0.

**What actually happened.** This is the cleanest result in the entire capture. The question
asked for two things Atlas never ingests, and it refused on both, named both specifically,
and invented nothing — no hedged directional guess, no "TCS typically trades at a premium",
no recalled-from-training P/E. The refusal enumerates what was missing rather than emitting
a generic "insufficient evidence", so a reader can tell the refusal was reasoned rather
than reflexive.

This is the `honest_negative` behaviour class working on a live question.

## Run 5 (third pass) — DRILL-THROUGH

Command: `atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?" --show-evidence`

```
[FACT] TCS declared an interim dividend of 10.0 per equity share on October 10, 2024. (confidence: high) [bse-news-373a3674-df22-42d5-ac50-1d77941355cd, bse-news-9946569a-50a1-4e19-a987-5f5bdce8f06a, bse-news-c8be78c9-b40f-486a-853b-825e1919c160]
[FACT] TCS recommended a final dividend of 31.0 per share on April 9, 2026. (confidence: high) [bse-news-6f1cf0de-6044-4195-8d91-f479cbfa778a, bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83, bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956]
[FACT] TCS announced a buyback on November 17, 2023, and December 13, 2023, with shares extinguished on December 13, 2023. (confidence: high) [bse-news-4d4a5575-3bbf-40c5-9e32-613f51c84105, bse-news-6233389e-6f1b-4545-a03b-d3fca0b40cfb, bse-news-8b2b0027-67c5-4eb6-8012-153d22b30750]
[FACT] A buyback was announced on November 20, 2020, with an offer period from December 18, 2020, to January 1, 2021. (confidence: high) [bse-news-853000ae-953d-4891-a58d-074e435e0de5, bse-news-b1dc2c18-b69e-41c1-8e44-0614630cea37]
[FACT] The total monetary value of the buybacks is not specified in the provided evidence. (confidence: high)
    ? not known: Total monetary value of buybacks.

Overall confidence: high

Sources:
  - bse-news-373a3674-df22-42d5-ac50-1d77941355cd
      (declaration of second interim dividend) "We enclose the audited standalone financial results of the Company and audited consolidated financial 
results of the Company and its subsidiaries for the"
  - bse-news-4d4a5575-3bbf-40c5-9e32-613f51c84105
      (ugh the Tender Offer route using) "Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations, 2015,  
we hereby enclose copies of Post Buyback Public Announcement dated Tuesday, December 12, 2023, 
in Financial Express (English edition), Jansatta (Hindi edition)"
  - bse-news-6233389e-6f1b-4545-a03b-d3fca0b40cfb
      (Sub: Public Announcement for Buyback of Equity Shares) "This is in furtherance of  our letter no. TCS/BM/162/SE/2023-24 dated October 11, 2023 and letter no. 
TCS/BB/SE/201/2023-24 dated November 15, 2023, informing the decision of the"
  - bse-news-6f1cf0de-6044-4195-8d91-f479cbfa778a
      (Mumbai) "- 400001   
Symbol - TCS 
     Scrip Code No. 532540 
Dear Sirs, 
Sub: Financial Results for the year ended on March 31, 2026 and Recommendation of a Final Dividend 
We enclose the audited standalone financial results of the Company and audited"
  - bse-news-7ff81737-8eeb-4f5a-afad-f5f79b216e83
      (Scrip Code No. 532540) "Sub: Transcript of the earnings conference call for the quarter and year ended  
March 31, 2026"
  - bse-news-853000ae-953d-4891-a58d-074e435e0de5
      (TCS/BB/SE/127/2020-21) "November 20, 2020"
  - bse-news-8b2b0027-67c5-4eb6-8012-153d22b30750
      (361,80,87,518) "Pursuant to Regulation 11(iv) of the Buyback Regulations, we also enclose the certificate dated 
December 13, 2023 issued as per Regulation 11(iii) of the Buyback"
  - bse-news-9946569a-50a1-4e19-a987-5f5bdce8f06a
      (Tata Consultancy Services Limited) "Q2 2025 Earnings Conference Call 
October 10, 2024, 19:00 hrs IST (09:30 hrs US ET)"
  - bse-news-b1dc2c18-b69e-41c1-8e44-0614630cea37
      (Schedule of activities in relation to the Buyback is as follows:) "Date of Opening of the Buy Back Offer Period  
Friday, December 18, 2020 
Date of Closing of the Buy Back Offer Period 
Friday, January 1, 2021 
Last date and time for receipt of completed"
  - bse-news-c8be78c9-b40f-486a-853b-825e1919c160
      ("Ind AS") 34 - Interim Financial Reporting prescribed under) "3. 
The Board of Directors at its meeting held on October 10, 2024, has declared an interim dividend of 10.00 per equity share."
  - bse-news-e4ffa3fc-e4f0-4da0-89fe-75d2f7b7b956
      (Page 1 of 7) "’
Independent Auditors Report
To the Board of Directors of Tata Consultancy Services Limited
Report on the audit of the Consolidated Annual Financial Results
Opinion
We have audited the accompanying consolidated annual financial results of Tata"

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3 · 59 documents
```

**What actually happened.** The path from claim to source works end to end: every cited id
resolves to a real document and prints a real excerpt from it. That is the property the
citation validator exists to guarantee, and it holds.

The excerpts themselves are uneven, in two distinct ways.

*One is genuinely excellent.* `bse-news-c8be78c9` returns
`The Board of Directors at its meeting held on October 10, 2024, has declared an interim
dividend of 10.00 per equity share.` — the exact sentence that supports the exact claim.
An analyst can verify that claim in one glance.

*Several do not support the claim they are attached to.* `bse-news-7ff81737` is cited for
the April 2026 final dividend but its excerpt is a transcript cover line; `bse-news-e4ffa3fc`
is cited for the same claim but returns the opening of the Independent Auditors Report. The
documents are relevant, the *excerpts* land on boilerplate. Citation validation confirms the
id resolves; it does not confirm the retrieved passage contains the fact.

*The parenthetical labels are extraction damage.* `(Mumbai)`, `(Page 1 of 7)`,
`(361,80,87,518)`, `(Scrip Code No. 532540)` and — worst — `(ugh the Tender Offer route
using)`, which is a mid-word fragment of "through". These are meant to identify the source
and instead range from useless to visibly broken. Same underlying PDF-layer damage as the
ligature problem in run 4, surfacing in a different place.

---

# Final summary across all three passes

| Run | Pass 1 (no provider) | Pass 2 (OmniRoute up) | Pass 3 (Gemini) |
|---|---|---|---|
| 1a ownership | works | — | — |
| 1b ask dividends/buybacks | connection refused | 60s read timeout | **works**, one confident wrong gap |
| 1c capital | works, duplicate rows | — | — |
| 2 since last quarter | connection refused | 60s read timeout | **unparseable model output** |
| 3 out-of-corpus | connection refused | 60s read timeout | **clean, specific refusal** |
| 4 risks | works, 116 noise rows | — | — |
| 4b risk_recurrence | works, 2 rows, both wrong | — | — |
| 5 drill-through | connection refused | 60s read timeout | **works**, uneven excerpts |
| 6 fingerprint | works | — | — |

**What Atlas demonstrably does well.** Deterministic queries return typed, dated,
unit-carrying, build-pinned output. Out-of-corpus questions are refused specifically and
without invention (run 3) — the single most important property for a research tool, and the
one most systems fail. Claims carry evidence ids that resolve to real documents with real
excerpts (run 5). Every artifact in this file is pinned to one digest, so any of it can be
re-derived or diffed against a later build.

**What it demonstrably does not.** The risk-factor path is misclassified at the source and
propagates a surname into a recurrence table (runs 4, 4b). `atlas query capital` duplicates
rows (run 1c). The reasoning layer answered "not specified in the provided evidence" with
high confidence about a number the deterministic layer prints, because it saw 59 of 140
documents (run 1b) — the two layers disagree about what Atlas knows, and only one of them
is right. Retrieved excerpts frequently land on boilerplate rather than the supporting
sentence, and their source labels carry PDF extraction damage (run 5). Provider failure is
handled gracefully in one mode and dumps a raw traceback in another (passes 1 vs 2).

**What remains unknown.** Whether Atlas discloses that "since last quarter" spans six
months on a Q2/Q4-only corpus. Three attempts, three unrelated failures, no answer. It is
recorded here as unknown rather than assumed either way.

# Atlas — sample outputs

Captured 2026-08-16 against the TCS repository, build
`3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3`
(`code_rev m2.4.1-115-g60442f5`). Every block below is the command's output verbatim.

Deterministic queries need no model. The three `atlas ask` runs used
`google_ai_studio` / `gemini-2.5-flash`.


## 1. Ownership

```
$ atlas query TCS ownership

Ownership Structure  [TCS]
==========================

Shareholding Pattern (last 8 quarters)
--------------------------------------
Period    Promoter (QoQ)  FPI (QoQ)  DII     MF     Public  Pledged
--------  --------------  ---------  ------  -----  ------  -------
Mar 2026  71.77% (-)      9.66% (-)  13.41%  5.77%  28.23%  0.00%  

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3
```

## 2. Capital allocation events

```
$ atlas query TCS capital

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

## 3. Risk factors

```
$ atlas query TCS risks

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

## 4. Risk recurrence

```
$ atlas query TCS risk_recurrence

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

## 5. Shareholder returns — grounded reasoning

```
$ atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?"

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

## 6. Out-of-corpus question — refusal

```
$ atlas ask TCS "How does TCS's valuation compare with its peers, and what are brokerages saying about the stock?"

Atlas cannot answer this question.
Reason: The provided evidence does not contain information about TCS's valuation metrics, a comparison of its valuation with peers, or any brokerage opinions or ratings on the stock.

Atlas 3436f960ea560b3d9ea09a088f05251e35f219a00660675ea6531e46600b5ca3 · 59 documents
```

## 7. Drill-through from claim to source excerpt

```
$ atlas ask TCS "How much has TCS returned to shareholders through dividends and buybacks, and when?" --show-evidence

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

## 8. Build fingerprint

```
$ atlas fingerprint show

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

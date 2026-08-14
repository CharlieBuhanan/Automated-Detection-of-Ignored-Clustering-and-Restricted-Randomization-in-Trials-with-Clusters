/*==========================================================================
  P0103_CMH_TESTS.SAS
  Purpose : Exact statistical tests comparing NCI vs NHLBI rates of
            correct/incorrect power and data analyses.
            Writes formatted LaTeX tables for direct insertion into
            NHLBI_Ignore03 manuscript.
  Input   : NHLBI.p0101_crt_review (from P0101)
            NCI summary counts hard-coded from Ignore02 (Glueck & Muller 2025)
  Output  : p0103_cmh_tests.log
            p0103_cmh_tests.lst
            cmh_tab1.tex        (Table 1: correct/incorrect cross-tab, NCI and NHLBI side by side)
            cmh_tab2.tex        (Table 2: what ignored in power analyses)
            cmh_tab3.tex        (Table 3: what ignored in data analyses)
  Author  : DHG / KEM
  Created : 2025
  Version : 3.0

  Statistical tests:
  ------------------
  Table 1 (PowerStatAnalysis): Compare marginal P(correct) NCI vs NHLBI
    - Fisher's exact test (exact fisher option in proc freq)
    - Separate tests for data analysis and power analysis correctness
    - 2x2 table: agency (NCI/NHLBI) x correct (yes/no)

  Tables 2 and 3 (IgnoredPower, IgnoredData): CMH across 3 strata
    - Exact CMH test (exact cmh option in proc freq)
    - Strata: (1) Clustering alone / ignored clustering
              (2) Clustering+RR   / ignored RR only
              (3) Clustering+RR   / ignored both
    - Rows: agency (NCI vs NHLBI)
    - Cols: ignored (1=yes / 0=no)

  ODS strategy:
  - Use ODS OUTPUT to capture exact test p-values into SAS datasets
  - Use put statements to write formatted LaTeX tables matching
    manuscript style (normalsize, booktabs, \pctN convention)

  NCI counts (from Ignore02, Glueck & Muller 2025, N=96):
  ---------------------------------------------------------
  Table 1 cross-tab:
    Data correct / Power correct   : 20
    Data correct / Power incorrect : 11
    Data incorrect / Power correct :  5
    Data incorrect / Power incorrect: 60
    -> Data correct: 31/96 (32.3%)
    -> Power correct: 25/96 (26.0%)

  Table 2 (power analyses):
    Clustering alone (N=30):   ignored clustering = 20, correct = 10
    Clustering+RR (N=66):      ignored RR only = 32, not = 34
    Clustering+RR (N=66):      ignored both = 19, not = 47

  Table 3 (data analyses):
    Clustering alone (N=30):   ignored clustering = 14, correct = 16
    Clustering+RR (N=66):      ignored RR only = 26, not = 40
    Clustering+RR (N=66):      ignored both = 25, not = 41

  NOTE on "not ignored" counts for RR strata:
    For each binary stratum (ignored yes/no), "no" includes both
    correct analyses AND those with a different type of error.
    e.g. Stratum "ignored RR only": ignored=no includes correct (15)
    + ignored both (19) = 34. This is the correct formulation for
    a CMH comparing the rate of each specific error type between agencies.
==========================================================================*/

/* ---- 0. File and folder macro variables -------------------------------- */
%let sasdir  = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms;
%let datadir = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata;

/* ---- 1. Log and listing ----------------------------------------------- */
proc printto
  log   = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0103_cmh_tests.log"
  print = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0103_cmh_tests.lst"
             new;
run;

options linesize=120 pagesize=60 nodate nonumber nofmterr;
title "P0103: Exact Tests -- NCI vs NHLBI";
%put NOTE- P0103: Reading from NHLBI.p0101_crt_review;
%put NOTE- P0103: Writing LaTeX to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab*.tex;

/* ---- 2. Libname -------------------------------------------------------- */
libname NHLBI "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata";

/* ---- 3. Verify dataset ------------------------------------------------ */
%let dsid3 = %sysfunc(open(NHLBI.p0101_crt_review));
%let n_check = %sysfunc(attrn(&dsid3, nobs));
%let rc3   = %sysfunc(close(&dsid3));
%if &n_check = 0 %then %do;
  %put ERROR- P0103: Dataset NHLBI.p0101_crt_review empty or missing. Run P0101 first.;
  %goto fin;
%end;
%put NOTE- P0103: Total rows in p0101_crt_review = &n_check;

/* ---- 4. Print NHLBI verification tables ------------------------------- */
title2 "NHLBI: correctness frequencies (included only) -- verify before proceeding";
proc freq data=NHLBI.p0101_crt_review;
  where excluded=0;
  tables data_correct_n * power_correct_n / missing;
  tables design_type * ignored_data_c / missing;
  tables design_type * ignored_power_c / missing;
run;

/* ================================================================
   SECTION 1: TABLE 1 -- FISHER'S EXACT TESTS
   Compare P(data correct) and P(power correct) NCI vs NHLBI.
   ================================================================ */

title2 "Section 1: Table 1 -- Fisher exact tests, correctness NCI vs NHLBI";

/* 1a. Build NCI hard-coded data */
data NHLBI.p0103_nci_tab1;
  length agency $5;
  agency = "NCI";
  data_correct_n = 1; power_correct_n = 1; count = 20; output;
  data_correct_n = 1; power_correct_n = 0; count = 11; output;
  data_correct_n = 0; power_correct_n = 1; count =  5; output;
  data_correct_n = 0; power_correct_n = 0; count = 60; output;
run;

/* 1b. NHLBI counts from dataset */
proc freq data=NHLBI.p0101_crt_review noprint;
  where excluded=0 and
        data_correct_n  in (0,1) and
        power_correct_n in (0,1);
  tables data_correct_n * power_correct_n / out=NHLBI.p0103_nhlbi_tab1_raw;
run;

data NHLBI.p0103_nhlbi_tab1;
  set NHLBI.p0103_nhlbi_tab1_raw;
  length agency $5;
  agency = "NHLBI";
  keep agency data_correct_n power_correct_n count;
run;

/* 1c. Stack */
data NHLBI.p0103_tab1_combined;
  set NHLBI.p0103_nci_tab1 NHLBI.p0103_nhlbi_tab1;
run;

title2 "Table 1 combined counts (NCI + NHLBI)";
proc print data=NHLBI.p0103_tab1_combined noobs; run;

/* 1d. Collapse to marginals and get NHLBI totals for LaTeX */
proc sql noprint;
  /* NCI marginals */
  select sum(count) into :nci_n trimmed
  from NHLBI.p0103_tab1_combined where agency="NCI";

  select sum(count) into :nci_data_correct trimmed
  from NHLBI.p0103_tab1_combined where agency="NCI" and data_correct_n=1;

  select sum(count) into :nci_power_correct trimmed
  from NHLBI.p0103_tab1_combined where agency="NCI" and power_correct_n=1;

  /* NHLBI marginals */
  select sum(count) into :nhlbi_n trimmed
  from NHLBI.p0103_tab1_combined where agency="NHLBI";

  select sum(count) into :nhlbi_data_correct trimmed
  from NHLBI.p0103_tab1_combined where agency="NHLBI" and data_correct_n=1;

  select sum(count) into :nhlbi_power_correct trimmed
  from NHLBI.p0103_tab1_combined where agency="NHLBI" and power_correct_n=1;
quit;

/* Compute percentages */
data _null_;
  pct_nci_data  = round(&nci_data_correct  / &nci_n   * 100, 0.1);
  pct_nhlbi_data= round(&nhlbi_data_correct/ &nhlbi_n * 100, 0.1);
  pct_nci_pow   = round(&nci_power_correct / &nci_n   * 100, 0.1);
  pct_nhlbi_pow = round(&nhlbi_power_correct/&nhlbi_n * 100, 0.1);
  call symputx("pct_nci_data",  strip(put(pct_nci_data,  8.1)));
  call symputx("pct_nhlbi_data",strip(put(pct_nhlbi_data,8.1)));
  call symputx("pct_nci_pow",   strip(put(pct_nci_pow,   8.1)));
  call symputx("pct_nhlbi_pow", strip(put(pct_nhlbi_pow, 8.1)));
run;

/* 1e. Marginal datasets for Fisher tests */
proc sql noprint;
  create table NHLBI.p0103_tab1_data as
  select agency, data_correct_n as correct, sum(count) as count
  from NHLBI.p0103_tab1_combined
  group by agency, data_correct_n;

  create table NHLBI.p0103_tab1_power as
  select agency, power_correct_n as correct, sum(count) as count
  from NHLBI.p0103_tab1_combined
  group by agency, power_correct_n;
quit;

/* 1f. Fisher exact test -- data analysis correctness */
ods output FishersExact=NHLBI.p0103_fisher_data;
proc freq data=NHLBI.p0103_tab1_data order=data;
  tables agency * correct / fisher;
  exact fisher;
  weight count;
  title2 "Table 1a: Fisher exact -- data analysis correctness, NCI vs NHLBI";
run;
ods output close;

/* 1g. Fisher exact test -- power analysis correctness */
ods output FishersExact=NHLBI.p0103_fisher_power;
proc freq data=NHLBI.p0103_tab1_power order=data;
  tables agency * correct / fisher;
  exact fisher;
  weight count;
  title2 "Table 1b: Fisher exact -- power analysis correctness, NCI vs NHLBI";
run;
ods output close;

/* 1h. Print ODS output for verification */
title2 "Fisher exact output -- data analysis";
proc print data=NHLBI.p0103_fisher_data noobs; run;

title2 "Fisher exact output -- power analysis";
proc print data=NHLBI.p0103_fisher_power noobs; run;

/* 1i. Extract p-values */
/*
   ODS FishersExact dataset contains:
     Name1 = statistic label (e.g. "Two-sided Pr <= P")
     nValue1 = numeric p-value
*/
data _null_;
  set NHLBI.p0103_fisher_data;
  if strip(Name1) = "Two-sided Pr <= P" then
    call symputx("p_fisher_data", strip(put(nValue1, best8.)));
run;

data _null_;
  set NHLBI.p0103_fisher_power;
  if strip(Name1) = "Two-sided Pr <= P" then
    call symputx("p_fisher_power", strip(put(nValue1, best8.)));
run;

%put NOTE- P0103: Fisher exact p (data correct)  = &p_fisher_data;
%put NOTE- P0103: Fisher exact p (power correct) = &p_fisher_power;

/* ================================================================
   SECTION 2: TABLE 2 -- EXACT CMH, POWER ANALYSES
   ================================================================ */

title2 "Section 2: Table 2 -- Exact CMH, what ignored in power analyses";

/* 2a. NCI hard-coded counts */
data NHLBI.p0103_nci_tab2;
  length agency $5 stratum $25;
  agency = "NCI";
  stratum = "Clustering alone"; ignored=1; count=20; output;
  stratum = "Clustering alone"; ignored=0; count=10; output;
  stratum = "Ignored RR only";  ignored=1; count=32; output;
  stratum = "Ignored RR only";  ignored=0; count=34; output;
  stratum = "Ignored both";     ignored=1; count=19; output;
  stratum = "Ignored both";     ignored=0; count=47; output;
run;

/* 2b. NHLBI: derive from ignored_power_c (set by P0101) */
data NHLBI.p0103_nhlbi_power_long;
  set NHLBI.p0101_crt_review;
  where excluded=0 and ignored_power_c ne "";
  length agency $5 stratum $25;
  agency = "NHLBI";

  select (ignored_power_c);
    when ("ignored clustering") do;
      stratum="Clustering alone"; ignored=1; output;
    end;
    when ("correct") do;
      if design_type="Clustering alone" then do;
        stratum="Clustering alone"; ignored=0; output;
      end;
      else if design_type="Clustering + RR" then do;
        stratum="Ignored RR only"; ignored=0; output;
        stratum="Ignored both";    ignored=0; output;
      end;
    end;
    when ("ignored RR only") do;
      stratum="Ignored RR only"; ignored=1; output;
      stratum="Ignored both";    ignored=0; output;
    end;
    when ("ignored both") do;
      stratum="Ignored both";    ignored=1; output;
      stratum="Ignored RR only"; ignored=0; output;
    end;
    otherwise
      put "WARNING [P0103]: Unexpected ignored_power_c="
          ignored_power_c " entry=" entry_num;
  end;

  keep agency stratum ignored;
run;

proc freq data=NHLBI.p0103_nhlbi_power_long noprint;
  tables stratum * ignored / out=NHLBI.p0103_nhlbi_tab2_counts;
run;

data NHLBI.p0103_nhlbi_tab2;
  set NHLBI.p0103_nhlbi_tab2_counts;
  length agency $5;
  agency="NHLBI";
  where ignored in (0,1);
  keep agency stratum ignored count;
run;

data NHLBI.p0103_tab2_combined;
  set NHLBI.p0103_nci_tab2 NHLBI.p0103_nhlbi_tab2;
run;

title2 "Table 2 combined counts";
proc print data=NHLBI.p0103_tab2_combined noobs; run;

/* 2c. Exact CMH */
ods output CMH=NHLBI.p0103_cmh_tab2_stats ExactCMH=NHLBI.p0103_exact_cmh_tab2;
proc freq data=NHLBI.p0103_tab2_combined order=data;
  tables stratum * agency * ignored / cmh;
  exact cmh;
  weight count;
  title2 "Table 2: Exact CMH -- what ignored in power analyses";
run;
ods output close;

title2 "Table 2 exact CMH output";
proc print data=NHLBI.p0103_exact_cmh_tab2 noobs; run;

/* 2d. Extract exact CMH p-value */
/*
   ODS ExactCMH dataset contains:
     Name1 = statistic label
     nValue1 = numeric value
   Look for "Exact Pr >= ChiSq" or similar
*/
data _null_;
  set NHLBI.p0103_exact_cmh_tab2;
  put Name1= nValue1=;  /* print all rows to log for inspection */
  if index(upcase(Name1),"EXACT") > 0 and
     index(upcase(Name1),"PR") > 0 then
    call symputx("p_exact_cmh2", strip(put(nValue1, best8.)));
run;

%put NOTE- P0103: Exact CMH p (Table 2, power) = &p_exact_cmh2;

/* ================================================================
   SECTION 3: TABLE 3 -- EXACT CMH, DATA ANALYSES
   ================================================================ */

title2 "Section 3: Table 3 -- Exact CMH, what ignored in data analyses";

/* 3a. NCI hard-coded counts */
data NHLBI.p0103_nci_tab3;
  length agency $5 stratum $25;
  agency = "NCI";
  stratum = "Clustering alone"; ignored=1; count=14; output;
  stratum = "Clustering alone"; ignored=0; count=16; output;
  stratum = "Ignored RR only";  ignored=1; count=26; output;
  stratum = "Ignored RR only";  ignored=0; count=40; output;
  stratum = "Ignored both";     ignored=1; count=25; output;
  stratum = "Ignored both";     ignored=0; count=41; output;
run;

/* 3b. NHLBI: derive from ignored_data_c */
data NHLBI.p0103_nhlbi_data_long;
  set NHLBI.p0101_crt_review;
  where excluded=0 and ignored_data_c ne "";
  length agency $5 stratum $25;
  agency = "NHLBI";

  select (ignored_data_c);
    when ("ignored clustering") do;
      stratum="Clustering alone"; ignored=1; output;
    end;
    when ("correct") do;
      if design_type="Clustering alone" then do;
        stratum="Clustering alone"; ignored=0; output;
      end;
      else if design_type="Clustering + RR" then do;
        stratum="Ignored RR only"; ignored=0; output;
        stratum="Ignored both";    ignored=0; output;
      end;
    end;
    when ("ignored RR only") do;
      stratum="Ignored RR only"; ignored=1; output;
      stratum="Ignored both";    ignored=0; output;
    end;
    when ("ignored both") do;
      stratum="Ignored both";    ignored=1; output;
      stratum="Ignored RR only"; ignored=0; output;
    end;
    otherwise
      put "WARNING [P0103]: Unexpected ignored_data_c="
          ignored_data_c " entry=" entry_num;
  end;

  keep agency stratum ignored;
run;

proc freq data=NHLBI.p0103_nhlbi_data_long noprint;
  tables stratum * ignored / out=NHLBI.p0103_nhlbi_tab3_counts;
run;

data NHLBI.p0103_nhlbi_tab3;
  set NHLBI.p0103_nhlbi_tab3_counts;
  length agency $5;
  agency="NHLBI";
  where ignored in (0,1);
  keep agency stratum ignored count;
run;

data NHLBI.p0103_tab3_combined;
  set NHLBI.p0103_nci_tab3 NHLBI.p0103_nhlbi_tab3;
run;

title2 "Table 3 combined counts";
proc print data=NHLBI.p0103_tab3_combined noobs; run;

/* 3c. Exact CMH */
ods output CMH=NHLBI.p0103_cmh_tab3_stats ExactCMH=NHLBI.p0103_exact_cmh_tab3;
proc freq data=NHLBI.p0103_tab3_combined order=data;
  tables stratum * agency * ignored / cmh;
  exact cmh;
  weight count;
  title2 "Table 3: Exact CMH -- what ignored in data analyses";
run;
ods output close;

title2 "Table 3 exact CMH output";
proc print data=NHLBI.p0103_exact_cmh_tab3 noobs; run;

/* 3d. Extract exact CMH p-value */
data _null_;
  set NHLBI.p0103_exact_cmh_tab3;
  put Name1= nValue1=;
  if index(upcase(Name1),"EXACT") > 0 and
     index(upcase(Name1),"PR") > 0 then
    call symputx("p_exact_cmh3", strip(put(nValue1, best8.)));
run;

%put NOTE- P0103: Exact CMH p (Table 3, data) = &p_exact_cmh3;

/* ================================================================
   SECTION 4: Extract NHLBI stratum counts for LaTeX tables
   ================================================================ */

/* Get NHLBI counts for each cell of Tables 2 and 3 */
proc sql noprint;

  /* Table 2: power */
  select count into :nhlbi_pow_ca_ign trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Clustering alone" and ignored=1;

  select count into :nhlbi_pow_ca_cor trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Clustering alone" and ignored=0;

  select count into :nhlbi_pow_rr_ign trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Ignored RR only" and ignored=1;

  select count into :nhlbi_pow_rr_cor trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Ignored RR only" and ignored=0;

  select count into :nhlbi_pow_both_ign trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Ignored both" and ignored=1;

  select count into :nhlbi_pow_both_cor trimmed
  from NHLBI.p0103_nhlbi_tab2 where stratum="Ignored both" and ignored=0;

  /* Table 3: data */
  select count into :nhlbi_dat_ca_ign trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Clustering alone" and ignored=1;

  select count into :nhlbi_dat_ca_cor trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Clustering alone" and ignored=0;

  select count into :nhlbi_dat_rr_ign trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Ignored RR only" and ignored=1;

  select count into :nhlbi_dat_rr_cor trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Ignored RR only" and ignored=0;

  select count into :nhlbi_dat_both_ign trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Ignored both" and ignored=1;

  select count into :nhlbi_dat_both_cor trimmed
  from NHLBI.p0103_nhlbi_tab3 where stratum="Ignored both" and ignored=0;

quit;

/* Get NHLBI design type totals for percentage denominators */
proc sql noprint;
  select count(*) into :nhlbi_ca_n trimmed
  from NHLBI.p0101_crt_review
  where excluded=0 and design_type="Clustering alone";

  select count(*) into :nhlbi_rr_n trimmed
  from NHLBI.p0101_crt_review
  where excluded=0 and design_type="Clustering + RR";
quit;

%put NOTE- P0103: NHLBI clustering alone N = &nhlbi_ca_n;
%put NOTE- P0103: NHLBI clustering + RR N  = &nhlbi_rr_n;

/* Guard against division by zero */
%let nhlbi_ca_denom = &nhlbi_ca_n;
%let nhlbi_rr_denom = &nhlbi_rr_n;
%if &nhlbi_ca_denom = 0 %then %let nhlbi_ca_denom = 1;
%if &nhlbi_rr_denom = 0 %then %let nhlbi_rr_denom = 1;

/* Compute percentages */
data _null_;
  /* Table 2 NHLBI pcts */
  p2_ca_ign   = round(&nhlbi_pow_ca_ign   / &nhlbi_ca_denom * 100, 0.1);
  p2_rr_ign   = round(&nhlbi_pow_rr_ign   / &nhlbi_rr_denom * 100, 0.1);
  p2_both_ign = round(&nhlbi_pow_both_ign / &nhlbi_rr_denom * 100, 0.1);

  /* Table 3 NHLBI pcts */
  p3_ca_ign   = round(&nhlbi_dat_ca_ign   / &nhlbi_ca_denom * 100, 0.1);
  p3_rr_ign   = round(&nhlbi_dat_rr_ign   / &nhlbi_rr_denom * 100, 0.1);
  p3_both_ign = round(&nhlbi_dat_both_ign / &nhlbi_rr_denom * 100, 0.1);

  call symputx("p2_ca_ign",   strip(put(p2_ca_ign,   8.1)));
  call symputx("p2_rr_ign",   strip(put(p2_rr_ign,   8.1)));
  call symputx("p2_both_ign", strip(put(p2_both_ign, 8.1)));
  call symputx("p3_ca_ign",   strip(put(p3_ca_ign,   8.1)));
  call symputx("p3_rr_ign",   strip(put(p3_rr_ign,   8.1)));
  call symputx("p3_both_ign", strip(put(p3_both_ign, 8.1)));
run;

/* ================================================================
   SECTION 5: Write formatted LaTeX tables
   All tables use: normalsize, booktabs, \pctN{pct}{N} convention
   (grey N in parentheses after percentage, as in manuscript)
   ================================================================ */

/* ---- Table 1: PowerStatAnalysis -- minipage side by side ------------- */
/*
   Compute NHLBI 2x2 cell values needed to fill the table.
   NCI cells are hard-coded; NHLBI cells come from the dataset.

   Cell layout (matching blank table exactly):
     Rows: Data correct / Data incorrect / Total
     Cols: Power correct / Power incorrect / Total
*/

/* Get NHLBI 2x2 cell counts */
proc sql noprint;
  select sum(count) into :nhlbi_dc_pc trimmed   /* data correct,   power correct   */
  from NHLBI.p0103_tab1_combined
  where agency="NHLBI" and data_correct_n=1 and power_correct_n=1;

  select sum(count) into :nhlbi_dc_pi trimmed   /* data correct,   power incorrect */
  from NHLBI.p0103_tab1_combined
  where agency="NHLBI" and data_correct_n=1 and power_correct_n=0;

  select sum(count) into :nhlbi_di_pc trimmed   /* data incorrect, power correct   */
  from NHLBI.p0103_tab1_combined
  where agency="NHLBI" and data_correct_n=0 and power_correct_n=1;

  select sum(count) into :nhlbi_di_pi trimmed   /* data incorrect, power incorrect */
  from NHLBI.p0103_tab1_combined
  where agency="NHLBI" and data_correct_n=0 and power_correct_n=0;
quit;

/* Compute NHLBI row/col totals and percentages */
data _null_;
  /* Cell counts */
  dc_pc = &nhlbi_dc_pc;  dc_pi = &nhlbi_dc_pi;
  di_pc = &nhlbi_di_pc;  di_pi = &nhlbi_di_pi;
  n     = &nhlbi_n;

  /* Row totals */
  dc_tot = dc_pc + dc_pi;   /* data correct total   */
  di_tot = di_pc + di_pi;   /* data incorrect total */

  /* Column totals */
  pc_tot = dc_pc + di_pc;   /* power correct total   */
  pi_tot = dc_pi + di_pi;   /* power incorrect total */

  /* Percentages (% of total N) */
  p_dc_pc = round(dc_pc / n * 100, 0.1);
  p_dc_pi = round(dc_pi / n * 100, 0.1);
  p_dc_tot= round(dc_tot/ n * 100, 0.1);
  p_di_pc = round(di_pc / n * 100, 0.1);
  p_di_pi = round(di_pi / n * 100, 0.1);
  p_di_tot= round(di_tot/ n * 100, 0.1);
  p_pc_tot= round(pc_tot/ n * 100, 0.1);
  p_pi_tot= round(pi_tot/ n * 100, 0.1);

  call symputx("nhlbi_dc_pc",  strip(put(dc_pc,  best8.)));
  call symputx("nhlbi_dc_pi",  strip(put(dc_pi,  best8.)));
  call symputx("nhlbi_dc_tot", strip(put(dc_tot, best8.)));
  call symputx("nhlbi_di_pc",  strip(put(di_pc,  best8.)));
  call symputx("nhlbi_di_pi",  strip(put(di_pi,  best8.)));
  call symputx("nhlbi_di_tot", strip(put(di_tot, best8.)));
  call symputx("nhlbi_pc_tot", strip(put(pc_tot, best8.)));
  call symputx("nhlbi_pi_tot", strip(put(pi_tot, best8.)));

  call symputx("p_nhlbi_dc_pc",  strip(put(p_dc_pc,  8.1)));
  call symputx("p_nhlbi_dc_pi",  strip(put(p_dc_pi,  8.1)));
  call symputx("p_nhlbi_dc_tot", strip(put(p_dc_tot, 8.1)));
  call symputx("p_nhlbi_di_pc",  strip(put(p_di_pc,  8.1)));
  call symputx("p_nhlbi_di_pi",  strip(put(p_di_pi,  8.1)));
  call symputx("p_nhlbi_di_tot", strip(put(p_di_tot, 8.1)));
  call symputx("p_nhlbi_pc_tot", strip(put(p_pc_tot, 8.1)));
  call symputx("p_nhlbi_pi_tot", strip(put(p_pi_tot, 8.1)));
run;

filename tex1 "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab1.tex";
data _null_;
  file tex1;
  put "% Table 1: Correct and incorrect data and power analysis rates";
  put "% Fisher exact p (data correct)  = &p_fisher_data";
  put "% Fisher exact p (power correct) = &p_fisher_power";
  put "% Generated by P0103. Verify against p0103_cmh_tests.lst.";
  put "%";
  put "\begin{table}[p]";
  put "\normalsize\centering";
  put "\captionsetup{width=\linewidth}";
  put "\caption{Correct and incorrect data and power analysis rates in";
  put "  systematic reviews of NCI (left) and NHLBI (right) trials with";
  put "  clusters. Values are percentages with counts in grey;";
  put "  $\mathcal{N}$ = 96 manuscripts reviewed for NCI-funded studies,";
  put "  $\mathcal{N}$ = &nhlbi_n manuscripts reviewed for NHLBI-funded";
  put "  studies. Fisher exact $p$ (data analysis correct) = &p_fisher_data;";
  put "  Fisher exact $p$ (power analysis correct) = &p_fisher_power.}";
  put "\label{tab:PowerStatAnalysis}";
  put "\setlength{\tabcolsep}{6pt}";
  put "%";
  put "\begin{minipage}[t]{0.42\linewidth}";
  put "\centering";
  put "\textbf{NCI-funded studies}\\[6pt]";
  put "\begin{tabular}{ll ccc}";
  put "\toprule";
  put "& & \multicolumn{2}{c}{\shortstack{Power or sample\\size analyses}} & \\";
  put "\cmidrule(lr){3-4}";
  put "& & Correct & Incorrect & Total \\";
  put "\midrule";
  put "\multirow{2}{*}{\shortstack{Data\\analyses}}";
  put "  & Correct   & \pctN{20.8}{20} & \pctN{11.5}{11} & \pctN{32.3}{31} \\[6pt]";
  put "  & Incorrect & \pctN{5.2}{5}   & \pctN{62.5}{60} & \pctN{67.7}{65} \\";
  put "\midrule";
  put "  & Total     & \pctN{26.0}{25} & \pctN{74.0}{71} & \pctN{100.0}{96} \\";
  put "\bottomrule";
  put "\end{tabular}";
  put "\end{minipage}";
  put "\hfill";
  put "\begin{minipage}[t]{0.42\linewidth}";
  put "\centering";
  put "\textbf{NHLBI-funded studies}\\[6pt]";
  put "\begin{tabular}{ll ccc}";
  put "\toprule";
  put "& & \multicolumn{2}{c}{\shortstack{Power or sample\\size analyses}} & \\";
  put "\cmidrule(lr){3-4}";
  put "& & Correct & Incorrect & Total \\";
  put "\midrule";
  put "\multirow{2}{*}{\shortstack{Data\\analyses}}";
  put "  & Correct   & \pctN{&p_nhlbi_dc_pc}{&nhlbi_dc_pc}";
  put "              & \pctN{&p_nhlbi_dc_pi}{&nhlbi_dc_pi}";
  put "              & \pctN{&p_nhlbi_dc_tot}{&nhlbi_dc_tot} \\[6pt]";
  put "  & Incorrect & \pctN{&p_nhlbi_di_pc}{&nhlbi_di_pc}";
  put "              & \pctN{&p_nhlbi_di_pi}{&nhlbi_di_pi}";
  put "              & \pctN{&p_nhlbi_di_tot}{&nhlbi_di_tot} \\";
  put "\midrule";
  put "  & Total     & \pctN{&p_nhlbi_pc_tot}{&nhlbi_pc_tot}";
  put "              & \pctN{&p_nhlbi_pi_tot}{&nhlbi_pi_tot}";
  put "              & \pctN{100.0}{&nhlbi_n} \\";
  put "\bottomrule";
  put "\end{tabular}";
  put "\end{minipage}";
  put "\end{table}";

/* ---- Table 2: What ignored in power analyses ------------------------- */
filename tex2 "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab2.tex";
data _null_;
  file tex2;
  put "% Table 2: What was ignored in power analyses, NCI vs NHLBI";
  put "% Exact CMH p = &p_exact_cmh2";
  put "% Generated by P0103. Verify against p0103_cmh_tests.lst.";
  put "%";
  put "\clearpage";
  put "\begin{landscape}";
  put "\begin{table}[p]";
  put "\large\rmfamily\centering";
  put "\captionsetup{width=9in, font=large, labelfont=normalfont, textfont=normalfont}";
  put "\caption{Numbers and percentages [$\mathcal{N}$ (\%)] of manuscripts";
  put "  cross-classified by design type and what was ignored in the power";
  put "  or sample size analyses, for NCI-funded and NHLBI-funded trials";
  put "  with clusters. Designs with clustering alone cannot have restricted";
  put "  randomization ignored; impossible cases indicated by gray shading.";
  put "  Exact Cochran-Mantel-Haenszel $p$ = &p_exact_cmh2.}";
  put "\label{tab:IgnoredPower}";
  put "\setlength{\tabcolsep}{8pt}";
  put "\begin{tabular}{l ccc p{18pt} ccc}";
  put "\toprule";
  put "& \multicolumn{3}{c}{NCI-funded studies} & & \multicolumn{3}{c}{NHLBI-funded studies} \\";
  put "\cmidrule(lr){2-4}\cmidrule(lr){6-8}";
  put "& \makecell[t]{Ignored\\clustering\\alone}";
  put "& \makecell[t]{Ignored restricted\\randomization only}";
  put "& \makecell[t]{Ignored\\both}";
  put "&";
  put "& \makecell[t]{Ignored\\clustering\\alone}";
  put "& \makecell[t]{Ignored restricted\\randomization only}";
  put "& \makecell[t]{Ignored\\both} \\";
  put "\midrule";
  put "\shortstack[l]{Clustering\\alone}";
  put "  & \pctN{66.7}{20} & \cellcolor[gray]{0.85} & \cellcolor[gray]{0.85}";
  put "  & & \pctN{&p2_ca_ign}{&nhlbi_pow_ca_ign}";
  put "      & \cellcolor[gray]{0.85} & \cellcolor[gray]{0.85} \\[10pt]";
  put "\shortstack[l]{Both clustering\\and restricted\\randomization}";
  put "  & \pctN{0.0}{0} & \pctN{48.5}{32} & \pctN{28.8}{19}";
  put "  & & & \pctN{&p2_rr_ign}{&nhlbi_pow_rr_ign}";
  put "      & \pctN{&p2_both_ign}{&nhlbi_pow_both_ign} \\[10pt]";
  put "Total";
  put "  & \pctN{20.8}{20} & \pctN{33.3}{32} & \pctN{19.8}{19}";
  put "  & & & & \\";
  put "\bottomrule";
  put "\end{tabular}";
  put "\end{table}";
  put "\end{landscape}";
run;

/* ---- Table 3: What ignored in data analyses -------------------------- */
filename tex3 "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab3.tex";
data _null_;
  file tex3;
  put "% Table 3: What was ignored in data analyses, NCI vs NHLBI";
  put "% Exact CMH p = &p_exact_cmh3";
  put "% Generated by P0103. Verify against p0103_cmh_tests.lst.";
  put "%";
  put "\clearpage";
  put "\begin{landscape}";
  put "\begin{table}[p]";
  put "\large\rmfamily\centering";
  put "\captionsetup{width=9in, font=large, labelfont=normalfont, textfont=normalfont}";
  put "\caption{Numbers and percentages [$\mathcal{N}$ (\%)] of manuscripts";
  put "  cross-classified by design type and what was ignored in the data";
  put "  analyses, for NCI-funded and NHLBI-funded trials with clusters.";
  put "  Designs with clustering alone cannot have restricted randomization";
  put "  ignored; impossible cases indicated by gray shading.";
  put "  Exact Cochran-Mantel-Haenszel $p$ = &p_exact_cmh3.}";
  put "\label{tab:IgnoredData}";
  put "\setlength{\tabcolsep}{8pt}";
  put "\begin{tabular}{l ccc p{18pt} ccc}";
  put "\toprule";
  put "& \multicolumn{3}{c}{NCI-funded studies} & & \multicolumn{3}{c}{NHLBI-funded studies} \\";
  put "\cmidrule(lr){2-4}\cmidrule(lr){6-8}";
  put "& \makecell[t]{Ignored\\clustering\\alone}";
  put "& \makecell[t]{Ignored restricted\\randomization only}";
  put "& \makecell[t]{Ignored\\both}";
  put "&";
  put "& \makecell[t]{Ignored\\clustering\\alone}";
  put "& \makecell[t]{Ignored restricted\\randomization only}";
  put "& \makecell[t]{Ignored\\both} \\";
  put "\midrule";
  put "\shortstack[l]{Clustering\\alone}";
  put "  & \pctN{46.7}{14} & \cellcolor[gray]{0.85} & \cellcolor[gray]{0.85}";
  put "  & & \pctN{&p3_ca_ign}{&nhlbi_dat_ca_ign}";
  put "      & \cellcolor[gray]{0.85} & \cellcolor[gray]{0.85} \\[10pt]";
  put "\shortstack[l]{Both clustering\\and restricted\\randomization}";
  put "  & \pctN{0.0}{0} & \pctN{39.4}{26} & \pctN{37.9}{25}";
  put "  & & & \pctN{&p3_rr_ign}{&nhlbi_dat_rr_ign}";
  put "      & \pctN{&p3_both_ign}{&nhlbi_dat_both_ign} \\[10pt]";
  put "Total";
  put "  & \pctN{14.6}{14} & \pctN{27.1}{26} & \pctN{26.0}{25}";
  put "  & & & & \\";
  put "\bottomrule";
  put "\end{tabular}";
  put "\end{table}";
  put "\end{landscape}";
run;
%put NOTE- P0103: LaTeX tables written to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab1.tex;
%put NOTE- P0103: LaTeX tables written to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab2.tex;
%put NOTE- P0103: LaTeX tables written to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\cmh_tab3.tex;

%fin:
title;
proc printto; run;

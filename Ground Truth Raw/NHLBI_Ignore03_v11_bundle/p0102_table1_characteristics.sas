/*==========================================================================
  P0102_TABLE1_CHARACTERISTICS.SAS
  Purpose : Produce Table 1 (study characteristics) for NHLBI Ignore03
            manuscript, with LaTeX output.
  Input   : NHLBI.p0101_crt_review (from P0101)
  Output  : p0102_table1_characteristics.log
            p0102_table1_characteristics.lst
            table1_characteristics.tex
  Author  : DHG / KEM
  Created : 2025
  Version : 2.0

  Programs in this series:
    P0101  Read extraction table -> NHLBI.p0101_crt_review
    P0102  Characteristics table (Table 1) -> table1_characteristics.tex
    P0103  CMH tests (Tables 2-4) -> cmh_results.tex
    P0104  PRISMA diagram export -> prisma_nhlbi.tex
==========================================================================*/

/* ---- 0. File and folder macro variables -------------------------------- */
%let sasdir  = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms;
%let datadir = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata;

/* ---- 1. Log and listing ----------------------------------------------- */
proc printto
  log   = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0102_table1_characteristics.log"
  print = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0102_table1_characteristics.lst"
             new;
run;

options linesize=120 pagesize=60 nodate nonumber nofmterr;
title "P0102: Study Characteristics Table";
%put NOTE- P0102: Reading from NHLBI.p0101_crt_review;
%put NOTE- P0102: Writing LaTeX to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\table1_characteristics.tex;

/* ---- 2. Libname -------------------------------------------------------- */
libname NHLBI "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata";

/* ---- 3. Subset to included entries ------------------------------------ */
data NHLBI.p0102_included;
  set NHLBI.p0101_crt_review;
  where excluded = 0;
run;

%let dsid2 = %sysfunc(open(NHLBI.p0102_included));
%let n_included_check = %sysfunc(attrn(&dsid2, nobs));
%let rc2   = %sysfunc(close(&dsid2));
%put NOTE- P0102: Included manuscripts = &n_included_check;
%if &n_included_check = 0 %then %do;
  %put ERROR- P0102: No included manuscripts found. Check P0101 output.;
  %goto fin;
%end;

/* ---- 4. Frequencies of categorical variables -------------------------- */

title2 "Frequency: Number of levels";
proc freq data=NHLBI.p0102_included noprint;
  tables n_levels / out=NHLBI.p0102_freq_levels missing;
run;
proc print data=NHLBI.p0102_freq_levels noobs; run;

title2 "Frequency: Restricted randomization type (raw)";
proc freq data=NHLBI.p0102_included noprint;
  tables restricted_rand / out=NHLBI.p0102_freq_rr missing;
run;
proc print data=NHLBI.p0102_freq_rr noobs; run;

title2 "Frequency: Stepped wedge";
proc freq data=NHLBI.p0102_included noprint;
  tables stepped_wedge / out=NHLBI.p0102_freq_sw missing;
run;
proc print data=NHLBI.p0102_freq_sw noobs; run;

title2 "Frequency: Design type";
proc freq data=NHLBI.p0102_included noprint;
  tables design_type / out=NHLBI.p0102_freq_design missing;
run;
proc print data=NHLBI.p0102_freq_design noobs; run;

title2 "Frequency: rr_flag";
proc freq data=NHLBI.p0102_included;
  tables rr_flag / missing;
run;

/* ---- 5. Continuous variables: median and range ----------------------- */

title2 "Descriptive statistics: continuous variables";
proc means data=NHLBI.p0102_included n median min max maxdec=1 noprint;
  var n_outer_n n_2nd_n n_long n_trt;
  output out=NHLBI.p0102_means_out
    n      = n_outer_n_n   n_2nd_n_n   n_long_n   n_trt_n
    median = n_outer_n_med n_2nd_n_med n_long_med n_trt_med
    min    = n_outer_n_min n_2nd_n_min n_long_min n_trt_min
    max    = n_outer_n_max n_2nd_n_max n_long_max n_trt_max
  ;
run;
proc print data=NHLBI.p0102_means_out noobs; run;

/* ---- 6. Extract counts via proc sql ----------------------------------- */

proc sql noprint;

  /* Total N */
  select count(*) into :n_total trimmed
  from NHLBI.p0102_included;

  /* Design type -- use design_type values as set by P0101 */
  select count(*) into :n_clust_alone trimmed
  from NHLBI.p0102_included
  where design_type = "Clustering alone";

  select count(*) into :n_clust_rr trimmed
  from NHLBI.p0102_included
  where design_type = "Clustering + RR";

  /* RR type -- among all included, not just RR designs */
  select count(*) into :n_strat trimmed
  from NHLBI.p0102_included
  where index(lowcase(restricted_rand), "stratif") > 0;

  select count(*) into :n_const trimmed
  from NHLBI.p0102_included
  where index(lowcase(restricted_rand), "constrain") > 0;

  select count(*) into :n_pair trimmed
  from NHLBI.p0102_included
  where index(lowcase(restricted_rand), "pair") > 0 or
        index(lowcase(restricted_rand), "match") > 0;

  select count(*) into :n_rr_other trimmed
  from NHLBI.p0102_included
  where rr_flag = "yes" and
        index(lowcase(restricted_rand), "stratif")  = 0 and
        index(lowcase(restricted_rand), "constrain") = 0 and
        index(lowcase(restricted_rand), "pair")      = 0 and
        index(lowcase(restricted_rand), "match")     = 0;

  /* Number of levels */
  select count(*) into :n_lev1 trimmed
  from NHLBI.p0102_included where n_levels = 1;

  select count(*) into :n_lev2 trimmed
  from NHLBI.p0102_included where n_levels = 2;

  select count(*) into :n_lev3 trimmed
  from NHLBI.p0102_included where n_levels = 3;

  select count(*) into :n_lev4plus trimmed
  from NHLBI.p0102_included where n_levels >= 4;

  select count(*) into :n_lev_miss trimmed
  from NHLBI.p0102_included where n_levels = .;

  /* Stepped wedge */
  select count(*) into :n_sw trimmed
  from NHLBI.p0102_included
  where lowcase(strip(stepped_wedge)) = "yes";

quit;

%put NOTE- P0102: n_total=&n_total n_clust_alone=&n_clust_alone n_clust_rr=&n_clust_rr;
%put NOTE- P0102: n_strat=&n_strat n_const=&n_const n_pair=&n_pair n_rr_other=&n_rr_other;
%put NOTE- P0102: n_lev1=&n_lev1 n_lev2=&n_lev2 n_lev3=&n_lev3 n_lev4plus=&n_lev4plus n_lev_miss=&n_lev_miss;

/* Verify design type counts sum to total */
%let n_design_check = %eval(&n_clust_alone + &n_clust_rr);
%if &n_design_check ne &n_total %then
  %put WARNING- P0102: Design type counts (&n_design_check) do not sum to total (&n_total). Check design_type in P0101.;

/* Guard against division by zero for RR subgroup */
%let pct_denom_rr = &n_clust_rr;
%if &pct_denom_rr = 0 %then %do;
  %put WARNING- P0102: No clustering+RR designs found. RR subtype percentages set to missing.;
  %let pct_denom_rr = 1;  /* prevent division by zero; percentages will be 0 */
%end;

/* ---- 7. Extract medians into macro variables -------------------------- */

data _null_;
  set NHLBI.p0102_means_out;

  /* Guard against missing medians (all values missing for a variable) */
  if n_outer_n_n > 0 then do;
    call symputx("med_outer",   strip(put(n_outer_n_med, best8.)));
    call symputx("min_outer",   strip(put(n_outer_n_min, best8.)));
    call symputx("max_outer",   strip(put(n_outer_n_max, best8.)));
    call symputx("n_outer_obs", strip(put(n_outer_n_n,   best8.)));
  end;
  else do;
    call symputx("med_outer",   "NR");
    call symputx("min_outer",   "NR");
    call symputx("max_outer",   "NR");
    call symputx("n_outer_obs", "0");
  end;

  if n_2nd_n_n > 0 then do;
    call symputx("med_2nd",   strip(put(n_2nd_n_med, best8.)));
    call symputx("min_2nd",   strip(put(n_2nd_n_min, best8.)));
    call symputx("max_2nd",   strip(put(n_2nd_n_max, best8.)));
    call symputx("n_2nd_obs", strip(put(n_2nd_n_n,   best8.)));
  end;
  else do;
    call symputx("med_2nd",   "NR");
    call symputx("min_2nd",   "NR");
    call symputx("max_2nd",   "NR");
    call symputx("n_2nd_obs", "0");
  end;

  if n_long_n > 0 then do;
    call symputx("med_long",   strip(put(n_long_med, best8.)));
    call symputx("min_long",   strip(put(n_long_min, best8.)));
    call symputx("max_long",   strip(put(n_long_max, best8.)));
    call symputx("n_long_obs", strip(put(n_long_n,   best8.)));
  end;
  else do;
    call symputx("med_long",   "NR");
    call symputx("min_long",   "NR");
    call symputx("max_long",   "NR");
    call symputx("n_long_obs", "0");
  end;

  if n_trt_n > 0 then do;
    call symputx("med_trt", strip(put(n_trt_med, best8.)));
    call symputx("min_trt", strip(put(n_trt_min, best8.)));
    call symputx("max_trt", strip(put(n_trt_max, best8.)));
  end;
  else do;
    call symputx("med_trt", "NR");
    call symputx("min_trt", "NR");
    call symputx("max_trt", "NR");
  end;
run;

/* ---- 8. Compute percentages (rounded to 1 decimal place) ------------- */
/*
   All percentages computed as data step assignments to avoid
   %sysevalf rounding issues. Division-by-zero guarded above.
*/

data NHLBI.p0102_pcts;
  pct_ca   = round(&n_clust_alone / &n_total         * 100, 0.1);
  pct_crr  = round(&n_clust_rr    / &n_total         * 100, 0.1);
  pct_st   = round(&n_strat       / &pct_denom_rr    * 100, 0.1);
  pct_co   = round(&n_const       / &pct_denom_rr    * 100, 0.1);
  pct_pair = round(&n_pair        / &pct_denom_rr    * 100, 0.1);
  pct_oth  = round(&n_rr_other    / &pct_denom_rr    * 100, 0.1);
  pct_l1   = round(&n_lev1        / &n_total         * 100, 0.1);
  pct_l2   = round(&n_lev2        / &n_total         * 100, 0.1);
  pct_l3   = round(&n_lev3        / &n_total         * 100, 0.1);
  pct_l4p  = round(&n_lev4plus    / &n_total         * 100, 0.1);
  pct_sw   = round(&n_sw          / &n_total         * 100, 0.1);

  call symputx("pct_ca",   strip(put(pct_ca,   8.1)));
  call symputx("pct_crr",  strip(put(pct_crr,  8.1)));
  call symputx("pct_st",   strip(put(pct_st,   8.1)));
  call symputx("pct_co",   strip(put(pct_co,   8.1)));
  call symputx("pct_pair", strip(put(pct_pair, 8.1)));
  call symputx("pct_oth",  strip(put(pct_oth,  8.1)));
  call symputx("pct_l1",   strip(put(pct_l1,   8.1)));
  call symputx("pct_l2",   strip(put(pct_l2,   8.1)));
  call symputx("pct_l3",   strip(put(pct_l3,   8.1)));
  call symputx("pct_l4p",  strip(put(pct_l4p,  8.1)));
  call symputx("pct_sw",   strip(put(pct_sw,   8.1)));
run;

/* ---- 9. Write LaTeX Table 1 ------------------------------------------ */
/*
   LaTeX formatting notes:
   - \% needed for literal percent sign in LaTeX text mode
   - Values are N (\%) or median (min, max)
   - Continuous variables show N with numeric values in parentheses
     to flag that not all entries have parseable numeric counts
*/

filename texout "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\table1_characteristics.tex";

data _null_;
  file texout;

  put "% Table 1: Study Characteristics";
  put "% Generated by P0102_TABLE1_CHARACTERISTICS.SAS";
  put "% N total included = &n_total";
  put "% NOTE: Percentages for RR subtypes are among designs with";
  put "%       restricted randomization (N = &n_clust_rr).";
  put "% NOTE: Continuous variable medians computed only for entries";
  put "%       with parseable numeric values; N shown in parentheses.";
  put "% NOTE: Verify all values before inserting into manuscript.";
  put "%";
  put "\begin{table}[p]";
  put "\normalsize\centering";
  put "\captionsetup{width=\linewidth}";
  put "\caption{Characteristics of NHLBI-funded cluster-randomized trials";
  put "  included in the systematic review ($\mathcal{N}$ = &n_total).}";
  put "\label{tab:Characteristics}";
  put "\setlength{\tabcolsep}{8pt}";
  put "\begin{tabular}{l r}";
  put "\toprule";
  put "Characteristic & $\mathcal{N}$ (\%) or median (min, max) \\";
  put "\midrule";

  put "\multicolumn{2}{l}{\textit{Design type}} \\";
  put "\quad Clustering alone & &n_clust_alone (&pct_ca\%) \\";
  put "\quad Clustering and restricted randomization & &n_clust_rr (&pct_crr\%) \\";
  put "\addlinespace";

  put "\multicolumn{2}{l}{\textit{Restricted randomization type";
  put "  (among $\mathcal{N}$ = &n_clust_rr designs with restricted randomization)}} \\";
  put "\quad Stratified & &n_strat (&pct_st\%) \\";
  put "\quad Constrained & &n_const (&pct_co\%) \\";
  put "\quad Pair-matched & &n_pair (&pct_pair\%) \\";
  put "\quad Other & &n_rr_other (&pct_oth\%) \\";
  put "\addlinespace";

  put "\multicolumn{2}{l}{\textit{Number of levels}} \\";
  if &n_lev1 > 0 then
    put "\quad 1 & &n_lev1 (&pct_l1\%) \\";
  put "\quad 2 & &n_lev2 (&pct_l2\%) \\";
  put "\quad 3 & &n_lev3 (&pct_l3\%) \\";
  put "\quad 4 or more & &n_lev4plus (&pct_l4p\%) \\";
  if &n_lev_miss > 0 then
    put "\quad Missing & &n_lev_miss \\";
  put "\addlinespace";

  put "\multicolumn{2}{l}{\textit{Continuous characteristics;";
  put "  $\mathcal{N}$ with parseable numeric value in parentheses}} \\";
  put "\quad Number of outer-level clusters (&n_outer_obs)";
  put "  & &med_outer (&min_outer, &max_outer) \\";
  put "\quad Number of 2nd-level units (&n_2nd_obs)";
  put "  & &med_2nd (&min_2nd, &max_2nd) \\";
  put "\quad Number of longitudinal repeated measures (&n_long_obs)";
  put "  & &med_long (&min_long, &max_long) \\";
  put "\quad Number of treatment arms";
  put "  & &med_trt (&min_trt, &max_trt) \\";
  put "\addlinespace";

  put "\multicolumn{2}{l}{\textit{Other}} \\";
  put "\quad Stepped wedge design & &n_sw (&pct_sw\%) \\";

  put "\bottomrule";
  put "\multicolumn{2}{l}{\small Values are $\mathcal{N}$ (\%) or median (min, max).} \\";
  put "\end{tabular}";
  put "\end{table}";
run;

%put NOTE- P0102: LaTeX Table 1 written to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\table1_characteristics.tex;

%fin:
title;
proc printto; run;

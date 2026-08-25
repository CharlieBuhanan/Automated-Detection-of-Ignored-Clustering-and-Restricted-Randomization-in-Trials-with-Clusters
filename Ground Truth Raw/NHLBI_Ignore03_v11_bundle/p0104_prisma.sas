/*==========================================================================
  P0104_PRISMA.SAS
  Purpose : Read exclusion counts from NHLBI.p0101_crt_review and write
            a populated PRISMA flow diagram LaTeX file for the NHLBI
            Ignore03 manuscript, replacing all xx placeholders with
            actual counts.
  Input   : NHLBI.p0101_crt_review (from P0101)
  Output  : p0104_prisma.log
            p0104_prisma.lst
            prisma_nhlbi.tex
  Author  : DHG / KEM
  Created : 2025
  Version : 1.1

  Notes:
  - The PRISMA diagram follows the same structure as the NCI companion
    paper (Glueck & Muller 2025): all records identified = all records
    screened (N excluded at screening = 0).
  - Exclusion categories are mapped by regex from the exclude_reason
    field. All categories are verified against the freq table printed
    to p0104_prisma.lst. If the sum of category counts does not equal
    the total excluded count, a WARNING is written to the log.
  - After running and verifying, replace the fig:PRISMA block in the
    manuscript with the contents of prisma_nhlbi.tex.
  - TikZ style definitions (process, excluded, phaselabel, arrow) must
    be defined in the main manuscript .tex file preamble -- they are
    NOT redefined here.
==========================================================================*/

/* ---- 0. File and folder macro variables -------------------------------- */
%let sasdir  = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms;
%let datadir = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata;

/* ---- 1. Log and listing ----------------------------------------------- */
proc printto
  log   = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0104_prisma.log"
  print = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0104_prisma.lst"
             new;
run;

options linesize=120 pagesize=60 nodate nonumber nofmterr;
title "P0104: PRISMA Diagram Export";
%put NOTE- P0104: Reading from NHLBI.p0101_crt_review;
%put NOTE- P0104: Writing LaTeX to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\prisma_nhlbi.tex;

/* ---- 2. Libname -------------------------------------------------------- */
libname NHLBI "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata";

/* ---- 3. Verify dataset exists ----------------------------------------- */
%let dsid3 = %sysfunc(open(NHLBI.p0101_crt_review));
%let n_check = %sysfunc(attrn(&dsid3, nobs));
%let rc3   = %sysfunc(close(&dsid3));
%if &n_check = 0 %then %do;
  %put ERROR- P0104: Dataset NHLBI.p0101_crt_review is empty or missing.;
  %put ERROR- P0104: Run P0101 first.;
  %goto fin;
%end;

/* ---- 4. Print all exclusion reasons for verification ----------------- */
title2 "All exclusion reasons -- verify category mapping below";
proc freq data=NHLBI.p0101_crt_review;
  where excluded=1;
  tables exclude_reason / missing;
run;

/* ---- 5. Initialize all category counts to 0 (guard vs blank %eval) -- */
%let n_identified      = 0;
%let n_included        = 0;
%let n_excluded_total  = 0;
%let n_baseline        = 0;
%let n_implementation  = 0;
%let n_methods         = 0;
%let n_not_grt         = 0;
%let n_pilot           = 0;
%let n_qualitative     = 0;
%let n_secondary       = 0;
%let n_second_study    = 0;
%let n_sw              = 0;
%let n_review          = 0;
%let n_other_excl      = 0;

/* ---- 6. Compute counts ------------------------------------------------ */
proc sql noprint;

  select count(*) into :n_identified trimmed
  from NHLBI.p0101_crt_review;

  select count(*) into :n_included trimmed
  from NHLBI.p0101_crt_review
  where excluded = 0;

  select count(*) into :n_excluded_total trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1;

  /* Baseline analyses only */
  select count(*) into :n_baseline trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\bbaseline\b/i', exclude_reason) > 0 and
        prxmatch('/secondary data/i', exclude_reason) = 0;

  /* Implementation papers */
  select count(*) into :n_implementation trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\bimplementation\b|\bimplement\b/i', exclude_reason) > 0;

  /* Methods / methodology papers */
  select count(*) into :n_methods trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\bmethods?\b|\bmethodology\b/i', exclude_reason) > 0;

  /* Not group-randomized trial */
  select count(*) into :n_not_grt trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/not a group.{0,10}random|not group.{0,10}random/i',
                 exclude_reason) > 0;

  /* Pilot studies */
  select count(*) into :n_pilot trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\bpilot\b/i', exclude_reason) > 0;

  /* Qualitative only */
  select count(*) into :n_qualitative trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\bqualitative\b/i', exclude_reason) > 0;

  /* Secondary data analysis */
  select count(*) into :n_secondary trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/secondary.{0,10}(data|analys)/i', exclude_reason) > 0;

  /* Second study by same group (randomly excluded) */
  select count(*) into :n_second_study trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/second.{0,5}study|same.{0,5}group/i', exclude_reason) > 0;

  /* Stepped wedge design */
  select count(*) into :n_sw trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/stepped.{0,5}wedge/i', exclude_reason) > 0;

  /* Review articles */
  select count(*) into :n_review trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/\breview\b/i', exclude_reason) > 0;

  /* Secondary outcomes only (distinct from secondary data analysis) */
  select count(*) into :n_secondary_outcomes trimmed
  from NHLBI.p0101_crt_review
  where excluded = 1 and
        prxmatch('/secondary.{0,5}outcome/i', exclude_reason) > 0;

quit;

/* ---- 7. Compute sum of categories and check -------------------------- */
/*
   Use %sysevalf (not %eval) to handle potential non-integer values
   and blank macro variables safely.
*/
%let n_excl_check = %sysevalf(
  &n_baseline + &n_implementation + &n_methods + &n_not_grt +
  &n_pilot + &n_qualitative + &n_secondary + &n_second_study +
  &n_sw + &n_review + &n_secondary_outcomes, integer);

%put NOTE- P0104: Total identified     = &n_identified;
%put NOTE- P0104: Total included       = &n_included;
%put NOTE- P0104: Total excluded       = &n_excluded_total;
%put NOTE- P0104: Sum of categories    = &n_excl_check;

%if &n_excl_check ne &n_excluded_total %then %do;
  %put WARNING- P0104: Category counts (&n_excl_check) do not equal;
  %put WARNING- P0104: total excluded (&n_excluded_total).;
  %put WARNING- P0104: Entries may match multiple categories or none.;
  %put WARNING- P0104: Review exclude_reason values in p0104_prisma.lst.;
%end;
%else %do;
  %put NOTE- P0104: Category counts verified -- sum equals total excluded.;
%end;

/* Print category counts to listing */
title2 "Exclusion category counts (verify against freq table above)";
data _null_;
  put "Category                     Count";
  put "----------------------------  -----";
  put "Baseline                      &n_baseline";
  put "Implementation                &n_implementation";
  put "Methods                       &n_methods";
  put "Not group-randomized          &n_not_grt";
  put "Pilot                         &n_pilot";
  put "Qualitative                   &n_qualitative";
  put "Secondary data analysis       &n_secondary";
  put "Second study, same group      &n_second_study";
  put "Stepped wedge                 &n_sw";
  put "Review                        &n_review";
  put "Secondary outcomes only       &n_secondary_outcomes";
  put "----------------------------  -----";
  put "Sum                           &n_excl_check";
  put "Total excluded (dataset)      &n_excluded_total";
  put "Total included                &n_included";
  put "Total identified              &n_identified";
run;

/* ---- 8. Write populated PRISMA LaTeX figure -------------------------- */

filename texout "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\prisma_nhlbi.tex";

data _null_;
  file texout;

  put "% PRISMA flow diagram for NHLBI Ignore03 manuscript";
  put "% Generated by P0104_PRISMA.SAS";
  put "% N identified = &n_identified";
  put "% N included   = &n_included";
  put "% N excluded   = &n_excluded_total";
  put "% Sum of exclusion categories = &n_excl_check";
  put "%";
  put "% IMPORTANT: Verify all counts against p0104_prisma.lst before use.";
  put "% TikZ styles (process, excluded, phaselabel, arrow) must be";
  put "% defined in the manuscript preamble -- see NHLBI_Ignore03_vXX.tex";
  put "%";
  put "% To use: replace the \begin{figure}...\end{figure} block";
  put "% containing \label{fig:PRISMA} in the manuscript with this file.";
  put "";
  put "\begin{figure}[p]";
  put "\centering";
  put "\begin{tikzpicture}[node distance=1.5cm]";
  put "";
  put "% Phase labels (left margin)";
  put "\node[phaselabel] at (-5.5, 0)  {\textbf{Identification}};";
  put "\node[phaselabel] at (-5.5,-4)  {\textbf{Screening}};";
  put "\node[phaselabel] at (-5.5,-8)  {\textbf{Eligibility}};";
  put "\node[phaselabel] at (-5.5,-12) {\textbf{Included}};";
  put "";
  put "% Identification";
  put "\node[process] (nhlbi1) at (0, 0)";
  put "  {Records identified through electronic database searching\\";
  put "   ($\mathcal{N}$ = &n_identified)};";
  put "";
  put "% Screening";
  put "\node[process] (nhlbi2) at (0,-4)";
  put "  {Records screened\\";
  put "   ($\mathcal{N}$ = &n_identified)};";
  put "\node[excluded] (nhlbi2e) at (5.5,-4)";
  put "  {Records excluded\\";
  put "   ($\mathcal{N}$ = 0)};";
  put "";
  put "% Eligibility";
  put "\node[process] (nhlbi3) at (0,-8)";
  put "  {Full-text articles assessed for eligibility\\";
  put "   ($\mathcal{N}$ = &n_identified)};";
  put "\node[excluded, text width=5cm] (nhlbi3e) at (5.5,-8)";
  put "  {Full-text articles excluded, with reasons\\";
  put "   ($\mathcal{N}$ = &n_excluded_total):\\";

  /* Only print exclusion categories with count > 0 */
  if &n_baseline        > 0 then
    put "   Baseline ($\mathcal{N}$ = &n_baseline)\\";
  if &n_implementation  > 0 then
    put "   Implementation ($\mathcal{N}$ = &n_implementation)\\";
  if &n_methods         > 0 then
    put "   Methods ($\mathcal{N}$ = &n_methods)\\";
  if &n_not_grt         > 0 then
    put "   Not group randomized ($\mathcal{N}$ = &n_not_grt)\\";
  if &n_pilot           > 0 then
    put "   Pilot ($\mathcal{N}$ = &n_pilot)\\";
  if &n_qualitative     > 0 then
    put "   Qualitative ($\mathcal{N}$ = &n_qualitative)\\";
  if &n_secondary       > 0 then
    put "   Secondary data analysis ($\mathcal{N}$ = &n_secondary)\\";
  if &n_second_study    > 0 then
    put "   Second study by same group ($\mathcal{N}$ = &n_second_study)\\";
  if &n_sw              > 0 then
    put "   Stepped wedge ($\mathcal{N}$ = &n_sw)\\";
  if &n_review          > 0 then
    put "   Review ($\mathcal{N}$ = &n_review)\\";
  if &n_secondary_outcomes > 0 then
    put "   Secondary outcomes only ($\mathcal{N}$ = &n_secondary_outcomes)\\";

  put "  };";
  put "";
  put "% Included";
  put "\node[process] (nhlbi4) at (0,-12)";
  put "  {Studies included in analyses\\";
  put "   ($\mathcal{N}$ = &n_included)};";
  put "";
  put "% Arrows";
  put "\draw[arrow] (nhlbi1) -- (nhlbi2);";
  put "\draw[arrow] (nhlbi2) -- (nhlbi2e);";
  put "\draw[arrow] (nhlbi2) -- (nhlbi3);";
  put "\draw[arrow] (nhlbi3) -- (nhlbi3e);";
  put "\draw[arrow] (nhlbi3) -- (nhlbi4);";
  put "";
  put "\end{tikzpicture}";
  put "\caption{PRISMA\citep{page_prisma_2021} flow diagram of the";
  put "  identification process for the sample of NHLBI-funded cluster";
  put "  randomized trials included in this review. The corresponding";
  put "  diagram for NCI-funded trials was published in Glueck and";
  put "  Muller~(2025).}";
  put "\label{fig:PRISMA}";
  put "\end{figure}";
run;

%put NOTE- P0104: PRISMA LaTeX written to C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\prisma_nhlbi.tex;

%fin:
title;
proc printto; run;

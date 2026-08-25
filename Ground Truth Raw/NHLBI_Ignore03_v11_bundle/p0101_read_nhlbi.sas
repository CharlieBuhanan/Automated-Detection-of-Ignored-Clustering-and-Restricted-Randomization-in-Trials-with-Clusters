/*==========================================================================
  P0101_READ_NHLBI.SAS
  Purpose : Parse NHLBI CRT extraction table (LaTeX .tex file) directly
            and create a permanent SAS dataset for downstream analysis.
  Input   : Highest-numbered crt_review_table_NNN.tex in ReviewData folder
  Output  : NHLBI.p0101_crt_review  (permanent SAS dataset)
            NHLBI.p0101_raw_entries  (intermediate)
            NHLBI.p0101_raw_clean    (intermediate)
            p0101_read_nhlbi.log
            p0101_read_nhlbi.lst
  Author  : DHG / KEM
  Created : 2025
  Version : 4.0

  LOCALIZATION: Update the three path constants below if folders change.
  The input tex file is auto-detected as the highest-numbered
  crt_review_table_NNN.tex in the ReviewData folder.

  Programs in this series:
    P0101  Read extraction table -> NHLBI.p0101_crt_review
    P0102  Characteristics table -> table1_characteristics.tex
    P0103  Exact CMH tests       -> cmh_tab1.tex, cmh_tab2.tex, cmh_tab3.tex
    P0104  PRISMA diagram        -> prisma_nhlbi.tex

  Column order in LaTeX table (22 columns, & delimited):
    1  citation           12 restricted_rand
    2  exclude_reason     13 icc
    3  n_trt              14 n_long
    4  n_levels           15 stepped_wedge
    5  comment_levels     16 data_done
    6  n_outer            17 data_should
    7  n_2nd              18 data_correct
    8  n_3rd              19 data_comment
    9  n_4th              20 power_done
   10  unit_rand          21 power_should
   11  ind_samp_unit      22 power_correct
==========================================================================*/

/* ====================================================================
   LOCALIZATION -- update these three paths if folders change
   ==================================================================== */

/* Folder where SAS programs, logs, listings, and LaTeX output live */
libname NHLBI "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata";

/* Folder where the extraction table .tex files live */
%let reviewdir = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\ReviewData;

/* Folder for log, listing, and LaTeX output files */
%let sasdir = C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms;

/* ====================================================================
   END LOCALIZATION
   ==================================================================== */

/* ---- 1. Direct log and listing output --------------------------------- */
proc printto
  log   = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0101_read_nhlbi.log"
  print = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\p0101_read_nhlbi.lst"
  new;
run;

options linesize=120 pagesize=60 nodate nonumber nofmterr;
title "P0101: Read NHLBI CRT Extraction Table";

/* ---- 2a. Create sasdata folder if it does not exist ------------------ */
/*
   The NHLBI libname points to this folder. SAS will error if it does
   not exist. We use the X command to create it via Windows mkdir.
   The /q flag suppresses output; mkdir does nothing if folder exists.
*/
x 'mkdir "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\SasPrograms\sasdata" /q 2>nul';

/* Verify the libname resolves after folder creation */
%if %sysfunc(libref(NHLBI)) ne 0 %then %do;
  %put ERROR- P0101: Cannot establish NHLBI libname.;
  %put ERROR- P0101: Check that sasdata folder exists and path is correct.;
  %goto fin;
%end;
%put NOTE- P0101: NHLBI library confirmed.;

/* ---- 2b. Auto-detect highest-numbered extraction table ---------------- */
/*
   Uses Windows DIR command piped into SAS to list files matching
   crt_review_table_*.tex in ReviewData, sorted descending by name.
   The first filename returned is the highest-numbered version.
*/
filename dirpipe pipe
  'dir "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\ReviewData\crt_review_table_*.tex" /b /o-n';

data _null_;
  infile dirpipe truncover lrecl=500;
  input fname $500.;
  fname = strip(fname);
  if _n_ = 1 and fname ne "" then do;
    /* Build full path */
    fullpath = "C:\Users\glueckd\ColoradoTeam Dropbox\Deborah Glueck\Lead01\Math\IgnoreNHLBI03\LiteratureReview\ReviewData\" || strip(fname);
    call symputx("intex",    fullpath);
    call symputx("intex_fn", fname);
  end;
run;

%put NOTE- P0101: Input file detected: &intex_fn;
%put NOTE- P0101: Full path: &intex;

/* Guard: file must exist */
%if %sysfunc(fileexist(&intex)) = 0 %then %do;
  %put ERROR- P0101: Input file not found: &intex;
  %put ERROR- P0101: Check that crt_review_table_NNN.tex exists in ReviewData folder.;
  %goto fin;
%end;

/* ---- 3. Compile regex patterns once ---------------------------------- */
%let re_entry     = %sysfunc(prxparse(/^%\s*Entry\s+(\d+)/));
%let re_skip      = %sysfunc(prxparse(/^\\(toprule|midrule|bottomrule|endfirsthead|endhead|endfoot|endlastfoot|multicolumn|begin|end|caption|label|documentclass|usepackage|newcolumntype|bibliographystyle|bibliography|addlinespace)/));
%let re_supercite = %sysfunc(prxparse(s/\\textsuperscript\{\\cite\{[^}]+\}\}//));
%let re_cite      = %sysfunc(prxparse(s/\\cite\{[^}]+\}//));
%let re_trailbs   = %sysfunc(prxparse(s/\\\\+\s*$//));
%let re_textcmd   = %sysfunc(prxparse(s/\\text(?:it|bf)\{([^}]+)\}/$1/));
%let re_emph      = %sysfunc(prxparse(s/\\emph\{([^}]+)\}/$1/));
%let re_braces    = %sysfunc(prxparse(s/[{}]/ /));
%let re_spaces    = %sysfunc(prxparse(s/  +/ /));

/* ---- 4. Step 1: Read raw lines, find entry data rows ----------------- */

data NHLBI.p0101_raw_entries;
  length raw_line $5000;
  retain entry_num . in_entry 0;
  retain re_entry &re_entry;
  retain re_skip  &re_skip;

  infile "&intex" truncover lrecl=5000;
  input raw_line $5000.;
  raw_line = strip(raw_line);

  /* Detect % Entry N comment lines */
  if prxmatch(re_entry, raw_line) then do;
    call prxposn(re_entry, 1, start, length);
    entry_num = input(substr(raw_line, start, length), best8.);
    if entry_num = . then
      put "WARNING [P0101]: Could not parse entry number from: " raw_line;
    in_entry = 1;
    return;
  end;

  if raw_line = "" then return;
  if substr(raw_line, 1, 1) = "%" then return;
  if prxmatch(re_skip, raw_line) then return;

  if in_entry = 1 and countc(raw_line, "&") >= 20 then do;
    output;
    in_entry = 0;
  end;

  keep entry_num raw_line;
run;

%let dsid = %sysfunc(open(NHLBI.p0101_raw_entries));
%let nraw = %sysfunc(attrn(&dsid, nobs));
%let rc   = %sysfunc(close(&dsid));
%put NOTE- P0101: &nraw raw entry rows extracted from &intex_fn;

%if &nraw = 0 %then %do;
  %put ERROR- P0101: No data rows found. Check that the file contains;
  %put ERROR- P0101: % Entry N comment lines followed by data rows with >= 20 & delimiters.;
  %goto fin;
%end;

/* ---- 5. Step 2: Clean LaTeX markup ----------------------------------- */

data NHLBI.p0101_raw_clean;
  length clean_line $5000;
  retain re_supercite &re_supercite;
  retain re_cite      &re_cite;
  retain re_trailbs   &re_trailbs;
  retain re_textcmd   &re_textcmd;
  retain re_emph      &re_emph;
  retain re_braces    &re_braces;
  retain re_spaces    &re_spaces;

  set NHLBI.p0101_raw_entries;

  clean_line = raw_line;
  clean_line = prxchange(re_supercite, -1, clean_line);
  clean_line = prxchange(re_cite,      -1, clean_line);
  clean_line = prxchange(re_trailbs,   -1, strip(clean_line));
  clean_line = prxchange(re_textcmd,   -1, clean_line);
  clean_line = prxchange(re_emph,      -1, clean_line);
  clean_line = prxchange(re_braces,    -1, clean_line);
  clean_line = prxchange(re_spaces,    -1, clean_line);
  clean_line = strip(clean_line);

  keep entry_num clean_line;
run;

/* ---- 6. Step 3: Split on & preserving empty tokens, derive variables - */

data NHLBI.p0101_crt_review
     (label="NHLBI CRT Systematic Review -- &intex_fn");

  set NHLBI.p0101_raw_clean;

  length
    citation        $100
    exclude_reason  $100
    n_trt_c         $10
    n_levels_c      $10
    comment_levels  $200
    n_outer_c       $50
    n_2nd_c         $50
    n_3rd_c         $50
    n_4th_c         $50
    unit_rand       $80
    ind_samp_unit   $80
    restricted_rand $80
    icc_c           $150
    n_long_c        $10
    stepped_wedge   $10
    data_done       $500
    data_should     $500
    data_correct    $5
    data_comment    $500
    power_done      $500
    power_should    $500
    power_correct   $5
    rr_flag         $5
    design_type     $20
    ignored_data_c  $25
    ignored_power_c $25
  ;

  /* Index-based split on & preserving empty tokens */
  array token_start{22} _temporary_;
  array token_len{22}   _temporary_;

  pos     = 1;
  col     = 1;
  linelen = length(clean_line);

  do while (col <= 22);
    token_start{col} = pos;
    next_amp = index(substr(clean_line, pos), "&");
    if next_amp = 0 then do;
      token_len{col} = linelen - pos + 1;
      col = col + 1;
      do fill = col to 22;
        token_start{fill} = 1;
        token_len{fill}   = 0;
      end;
      col = 23;
    end;
    else do;
      token_len{col} = next_amp - 1;
      pos = pos + next_amp;
      col = col + 1;
    end;
  end;

  %macro getfield(var, n);
    if token_len{&n} > 0
    then &var = strip(substr(clean_line, token_start{&n}, token_len{&n}));
    else &var = "";
  %mend;

  %getfield(citation,        1)
  %getfield(exclude_reason,  2)
  %getfield(n_trt_c,         3)
  %getfield(n_levels_c,      4)
  %getfield(comment_levels,  5)
  %getfield(n_outer_c,       6)
  %getfield(n_2nd_c,         7)
  %getfield(n_3rd_c,         8)
  %getfield(n_4th_c,         9)
  %getfield(unit_rand,      10)
  %getfield(ind_samp_unit,  11)
  %getfield(restricted_rand,12)
  %getfield(icc_c,          13)
  %getfield(n_long_c,       14)
  %getfield(stepped_wedge,  15)
  %getfield(data_done,      16)
  %getfield(data_should,    17)
  %getfield(data_correct,   18)
  %getfield(data_comment,   19)
  %getfield(power_done,     20)
  %getfield(power_should,   21)
  %getfield(power_correct,  22)

  /* Numeric conversions */
  n_trt = .;
  if n_trt_c not in ("", ".") then do;
    n_trt = input(n_trt_c, ?? best8.);
    if n_trt = . then put "WARNING [P0101]: n_trt unparseable: entry=" entry_num " citation=" citation " value=" n_trt_c;
  end;

  n_levels = .;
  if n_levels_c not in ("", ".") then do;
    n_levels = input(n_levels_c, ?? best8.);
    if n_levels = . then put "WARNING [P0101]: n_levels unparseable: entry=" entry_num " citation=" citation " value=" n_levels_c;
  end;

  n_long = .;
  if n_long_c not in ("", ".") then do;
    n_long = input(n_long_c, ?? best8.);
    if n_long = . then put "WARNING [P0101]: n_long unparseable: entry=" entry_num " citation=" citation " value=" n_long_c;
  end;

  n_outer_n = .;
  if upcase(n_outer_c) not in ("", ".", "NR", "UNKNOWN") then
    n_outer_n = input(scan(n_outer_c, 1, " ~/<>"), ?? best8.);

  n_2nd_n = .;
  if upcase(n_2nd_c) not in ("", ".", "NR", "UNKNOWN") then
    n_2nd_n = input(scan(n_2nd_c, 1, " ~/<>"), ?? best8.);

  /* Excluded flag */
  excluded = (exclude_reason ne "");

  /* Correctness flags */
  data_correct_n = .;
  select (lowcase(strip(data_correct)));
    when ("yes") data_correct_n = 1;
    when ("no")  data_correct_n = 0;
    otherwise    data_correct_n = .;
  end;

  power_correct_n = .;
  select (lowcase(strip(power_correct)));
    when ("yes") power_correct_n = 1;
    when ("no")  power_correct_n = 0;
    otherwise    power_correct_n = .;
  end;

  /* RR flag */
  rr_flag = "";
  if excluded = 0 then do;
    if lowcase(strip(restricted_rand)) in ("none", "no", "")
    then rr_flag = "no";
    else if restricted_rand ne ""
    then rr_flag = "yes";
  end;

  /* Design type */
  design_type = "";
  if excluded = 0 then do;
    if      rr_flag = "no"  then design_type = "Clustering alone";
    else if rr_flag = "yes" then design_type = "Clustering + RR";
  end;

  /* What was ignored (heuristic -- verify in P0103 listing) */
  ignored_data_c  = "";
  ignored_power_c = "";

  if excluded = 0 then do;

    if design_type = "Clustering alone" then do;
      if      data_correct_n = 1 then ignored_data_c = "correct";
      else if data_correct_n = 0 then ignored_data_c = "ignored clustering";
    end;
    else if design_type = "Clustering + RR" then do;
      if data_correct_n = 1 then ignored_data_c = "correct";
      else if data_correct_n = 0 then do;
        if index(lowcase(data_done), "clustering") > 0 and
           index(lowcase(data_done), "restricted") = 0 and
           index(lowcase(data_done), "stratif")    = 0 and
           index(lowcase(data_done), "matching")   = 0 and
           index(lowcase(data_done), "pair")        = 0
        then ignored_data_c = "ignored RR only";
        else if index(lowcase(data_done), "clustering") = 0
        then ignored_data_c = "ignored both";
        else ignored_data_c = "ignored RR only";
      end;
    end;

    if design_type = "Clustering alone" then do;
      if      power_correct_n = 1 then ignored_power_c = "correct";
      else if power_correct_n = 0 then ignored_power_c = "ignored clustering";
    end;
    else if design_type = "Clustering + RR" then do;
      if power_correct_n = 1 then ignored_power_c = "correct";
      else if power_correct_n = 0 then do;
        if index(lowcase(power_done), "clustering") > 0 and
           index(lowcase(power_done), "restricted") = 0 and
           index(lowcase(power_done), "stratif")    = 0 and
           index(lowcase(power_done), "matching")   = 0 and
           index(lowcase(power_done), "pair")        = 0
        then ignored_power_c = "ignored RR only";
        else if index(lowcase(power_done), "clustering") = 0
        then ignored_power_c = "ignored both";
        else ignored_power_c = "ignored RR only";
      end;
    end;

    if data_correct_n  = . then put "WARNING [P0101]: data_correct_n missing: entry=" entry_num " citation=" citation;
    if power_correct_n = . then put "WARNING [P0101]: power_correct_n missing: entry=" entry_num " citation=" citation;
    if ignored_data_c  = "" then put "WARNING [P0101]: ignored_data_c blank: entry=" entry_num " citation=" citation;
    if ignored_power_c = "" then put "WARNING [P0101]: ignored_power_c blank: entry=" entry_num " citation=" citation;

  end;

  label
    entry_num       = "Entry number"
    citation        = "First author and year"
    exclude_reason  = "Exclusion reason (blank = included)"
    n_trt           = "Number of treatment arms"
    n_levels        = "Number of levels"
    comment_levels  = "Comment on levels"
    n_outer_c       = "N outer clusters (raw)"
    n_outer_n       = "N outer clusters (numeric where parseable)"
    n_2nd_c         = "N 2nd level (raw)"
    n_2nd_n         = "N 2nd level (numeric where parseable)"
    n_3rd_c         = "N 3rd level (raw)"
    n_4th_c         = "N 4th level (raw)"
    unit_rand       = "Unit of randomization"
    ind_samp_unit   = "Independent sampling unit"
    restricted_rand = "Restricted randomization type (raw)"
    rr_flag         = "Restricted randomization present (yes/no)"
    icc_c           = "ICC (raw)"
    n_long          = "Number of longitudinal repeated measures"
    stepped_wedge   = "Stepped wedge design"
    data_done       = "Data analysis method used"
    data_should     = "Data analysis method that should have been used"
    data_correct    = "Data analysis correct (raw yes/no)"
    data_correct_n  = "Data analysis correct (1=yes 0=no)"
    data_comment    = "Data analysis reviewer comment"
    power_done      = "Power analysis method used"
    power_should    = "Power analysis method that should have been used"
    power_correct   = "Power analysis correct (raw yes/no)"
    power_correct_n = "Power analysis correct (1=yes 0=no)"
    excluded        = "Excluded from analysis (1=yes 0=no)"
    design_type     = "Design type"
    ignored_data_c  = "What ignored in data analysis (heuristic)"
    ignored_power_c = "What ignored in power analysis (heuristic)"
  ;

  drop clean_line n_trt_c n_levels_c n_long_c
       pos col linelen next_amp fill;

run;

/* ---- 7. Validation ---------------------------------------------------- */

title2 "Input file used";
data _null_;
  put "NOTE- P0101: Dataset created from &intex_fn";
run;

title2 "First 10 rows -- spot check parsing";
proc print data=NHLBI.p0101_crt_review (obs=10) noobs label;
  var entry_num citation excluded n_trt n_levels rr_flag design_type
      data_correct_n power_correct_n;
run;

title2 "Included entries with missing correctness flags -- must verify";
proc print data=NHLBI.p0101_crt_review noobs label;
  where excluded=0 and (data_correct_n=. or power_correct_n=.);
  var entry_num citation data_correct data_correct_n
      power_correct power_correct_n;
run;

title2 "Heuristic ignored flags -- verify all included entries";
proc print data=NHLBI.p0101_crt_review noobs label;
  where excluded=0;
  var entry_num citation design_type
      data_correct_n ignored_data_c
      power_correct_n ignored_power_c;
run;

title2 "Frequency: excluded vs included";
proc freq data=NHLBI.p0101_crt_review;
  tables excluded / missing;
run;

title2 "Frequency: key variables (included only)";
proc freq data=NHLBI.p0101_crt_review;
  where excluded=0;
  tables design_type rr_flag restricted_rand
         data_correct_n power_correct_n
         ignored_data_c ignored_power_c
         n_levels stepped_wedge / missing;
run;

title2 "Descriptive statistics: continuous variables (included only)";
proc means data=NHLBI.p0101_crt_review n median min max maxdec=1;
  where excluded=0;
  var n_trt n_levels n_outer_n n_2nd_n n_long;
  label
    n_trt     = "N treatment arms"
    n_levels  = "N levels"
    n_outer_n = "N outer clusters"
    n_2nd_n   = "N 2nd level units"
    n_long    = "N repeated measures";
run;

title2 "Exclusion reason frequencies";
proc freq data=NHLBI.p0101_crt_review;
  where excluded=1;
  tables exclude_reason / missing;
run;

title2 "Dataset contents";
proc contents data=NHLBI.p0101_crt_review varnum;
run;

%fin:
title;
proc printto; run;

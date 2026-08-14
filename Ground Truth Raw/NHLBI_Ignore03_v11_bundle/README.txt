================================================================================
  NHLBI IGNORE03 -- SYSTEMATIC REVIEW OF NHLBI-FUNDED CLUSTER-RANDOMIZED TRIALS
  README.TXT
  Updated: 2025
================================================================================

PROJECT OVERVIEW
----------------
This project contains the SAS programs, LaTeX manuscript files, and supporting
materials for a systematic review of NHLBI-funded cluster-randomized trials,
comparing rates of correct and incorrect power and data analyses to those found
in NCI-funded trials (Glueck and Muller 2025, the Ignore02 companion paper).

--------------------------------------------------------------------------------
FOLDER STRUCTURE
--------------------------------------------------------------------------------

SasPrograms\
  |- README.TXT                      (this file)
  |- p0101_read_nhlbi.sas            (read extraction table, create dataset)
  |- p0102_table1_characteristics.sas (characteristics table, Table 1)
  |- p0103_cmh_tests.sas             (CMH tests for Tables 2-4)
  |- p0104_prisma.sas                (PRISMA diagram export)
  |- sasdata\
  |    |- p0101_crt_review.sas7bdat  (permanent dataset, created by P0101)
  |- p0101_read_nhlbi.log            (SAS log, created by P0101)
  |- p0101_read_nhlbi.lst            (SAS listing, created by P0101)
  |- p0102_table1_characteristics.log
  |- p0102_table1_characteristics.lst
  |- p0103_cmh_tests.log
  |- p0103_cmh_tests.lst
  |- p0104_prisma.log
  |- p0104_prisma.lst

LaTeX output files (written to SasPrograms\ by SAS programs):
  |- table1_characteristics.tex      (created by P0102)
  |- cmh_results.tex                 (created by P0103)
  |- prisma_nhlbi.tex                (created by P0104)

Manuscript files (in Overleaf / parent folder):
  |- NHLBI_Ignore03_vXX.tex          (full manuscript, version-numbered)
  |- NHLBI_Ignore03_vXX.pdf
  |- references.bib                  (shared with Ignore02)
  |- SageV.bst                       (Vancouver citation style)

Extraction table (in LiteratureReview\ folder):
  |- crt_review_table_NNN.tex        (NNN = version number, e.g. 110)

--------------------------------------------------------------------------------
SAS PROGRAMS -- EXECUTION ORDER
--------------------------------------------------------------------------------

Run programs in order. Each program reads from the permanent dataset created
by the previous program. Never skip P0101.

  1. P0101_READ_NHLBI.SAS
     Reads: crt_review_table_&version..tex  (LaTeX extraction table)
     Writes: NHLBI.p0101_crt_review         (permanent SAS dataset)
             p0101_read_nhlbi.log / .lst
     Key outputs: dataset with all 22 extracted columns, derived variables
     (excluded, rr_flag, design_type, data_correct_n, power_correct_n,
     ignored_data_c, ignored_power_c), and validation printouts.
     NOTE: Check log for WARNING messages before proceeding to P0102+.
     NOTE: The ignored_data_c and ignored_power_c variables use heuristic
     text-matching; verify the printed table in p0101_read_nhlbi.lst.

  2. P0102_TABLE1_CHARACTERISTICS.SAS
     Reads: NHLBI.p0101_crt_review
     Writes: table1_characteristics.tex     (Table 1 for manuscript)
             p0102_table1_characteristics.log / .lst
     Produces: frequency and median/range summaries of design type,
     restricted randomization type, number of levels, cluster counts,
     repeated measures, treatment arms, stepped wedge.

  3. P0103_CMH_TESTS.SAS
     Reads: NHLBI.p0101_crt_review
            NCI counts hard-coded from Ignore02 (Glueck & Muller 2025)
     Writes: cmh_results.tex               (CMH results for manuscript)
             p0103_cmh_tests.log / .lst
     Produces: three Cochran-Mantel-Haenszel tests:
       - Table 1 (PowerStatAnalysis): 2x2 CMH, correct/incorrect
         data analysis x power analysis, stratified by funding agency.
       - Table 2 (IgnoredPower): CMH across 3 strata (clustering alone /
         ignored RR only / ignored both), comparing NCI vs NHLBI rates
         of what was ignored in power analyses.
       - Table 3 (IgnoredData): same structure for data analyses.
     NOTE: Review stratum assignments (ignored_data_c, ignored_power_c)
     from P0101 before interpreting CMH results.

  4. P0104_PRISMA.SAS
     Reads: NHLBI.p0101_crt_review
     Writes: prisma_nhlbi.tex              (PRISMA figure for manuscript)
             p0104_prisma.log / .lst
     Produces: populated TikZ PRISMA flow diagram with actual counts
     replacing all xx placeholders. Exclusion categories are mapped by
     regex from the exclude_reason field; verify counts in p0104_prisma.lst
     before using in the manuscript.
     To use: copy contents of prisma_nhlbi.tex into the manuscript in place
     of the fig:PRISMA block.

--------------------------------------------------------------------------------
UPDATING FOR A NEW EXTRACTION TABLE VERSION
--------------------------------------------------------------------------------

When a new version of the extraction table is ready (e.g. crt_review_table_112.tex):

  1. In P0101: change %let version = 112;
     (the &intex path uses &version automatically)
  2. Run P0101 through P0104 in order.
  3. Upversion the manuscript: copy NHLBI_Ignore03_vXX.tex to
     NHLBI_Ignore03_v(XX+1).tex before editing.
  4. Update this README with the new version number and date.

--------------------------------------------------------------------------------
MANUSCRIPT LATEX FILES
--------------------------------------------------------------------------------

The main manuscript is NHLBI_Ignore03_vXX.tex (currently v04).
It is compiled in Overleaf using:
  - references.bib   (bibliography, shared with Ignore02)
  - SageV.bst        (Vancouver citation style for Clinical Trials journal)

Compile sequence in Overleaf (or locally):
  pdflatex -> bibtex -> pdflatex -> pdflatex

Tables and figure are at the end of the manuscript .tex file, after the
references section. They are referenced in the results section using \ref{}.

LaTeX files generated by SAS programs (table1_characteristics.tex,
cmh_results.tex, prisma_nhlbi.tex) are intended to be copied into the
manuscript .tex file by hand after verification.

Paragraph outline headers in the manuscript (formatted as \outline{...})
are placeholders for writing and should be deleted before submission.

--------------------------------------------------------------------------------
COMPANION PAPER
--------------------------------------------------------------------------------

Glueck DH, Muller KE. Ignoring clustering, restricted randomization, or both
is common in NCI-funded trials with clusters, and may lead to decision errors.
Clinical Trials. 2025. (Ignore02)

The NCI data values hard-coded in P0103 come from this paper (N=96 included
manuscripts).

--------------------------------------------------------------------------------
CONTACTS
--------------------------------------------------------------------------------
Deborah H. Glueck  Deborah.Glueck@cuanschutz.edu
Keith E. Muller

================================================================================

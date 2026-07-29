I have a task: I want to use an AI model to scan though PDFs (I will probably use a python program to convert them into text first) of scientific papers. There are 2115 papers. The goal is to perform a study: we want to rate the papers (whether they were correct or incorrect) in two metrics: data analysis and power analysis. We have 500 additional papers (validation set) that have been rated already. These metrics seem simple but there is a bit of nuance to them: there are many things (including rare events) that could cause the paper to be marked "incorrect power analysis". I would like to iteratively give batches of these valid sets (groups of less than 100) to a base model to give it context and "train" it to pick up on specific patterns. I also want to do this with the exclusion and inclusion criteria, which will determine which papers will be removed from the study before we start. So, in total, there are 4 things I want it to be able to do: inclusion, exclusion, power analysis analysis, and data analysis analysis. I am thinking of starting this with the exclusion criteria, one of which is: if the paper is a secondary analysis we would like to exclude it from the set. I would like to test the ai by asking whether or not a file should be excluded, then giving feedback by telling them if they were right and a simple reason why. The pdf parsing in python shouldn't be that difficult. All review should be fed back into the model. 

Separate rubric per task (exclusion, inclusion, power analysis, data analysis). Keep them as independent prompts/pipelines—don't conflate criteria, since failure modes differ. 
Iterative rubric-building loop: Feed model paper text + current rubric → get judgment + reasoning (force JSON output: {decision, reasoning, confidence})
Compare to validation label 
When wrong, add the specific case (or a generalized rule derived from it) to the rubric as a worked example or explicit edge-case note
Re-run periodically against the full 500 to track accuracy — this is your regression test suite 
Few-shot selection: once you have 30-50+ worked examples, don't dump them all in every prompt — either (a) hand-pick a representative subset (~10-15) covering edge cases, or (b) do retrieval: embed validation cases, pull the k most similar ones per new paper. Simpler to start with (a). More likely, create a refined meta-rubric that details the precise reasons behind why or why not examples are accurate. 
Model choice: Use Opus (or Sonnet 4.6, which is often nearly as good and cheaper) to build/refine the rubric interactively. For the actual 2115-paper run, Sonnet is likely sufficient and much cheaper — reserve Opus for low-confidence/borderline cases (two-pass: cheap model flags uncertain ones, Opus reviews those). 
Batch API, not MCP. This is a batch classification job, not a tool-use/agentic task — MCP adds no value here. Use the Message Batches API for the full run (2115 × 4 metrics = ~8460 calls) — 50% cheaper, async, built for exactly this.

Here's my thinking on tools, followed by the layout and startup steps.

Tool recommendations

PDF → text

PyMuPDF (fitz) as the primary extractor — fast, handles most scientific-paper PDFs well, preserves reasonable reading order.
pdfplumber as a fallback for papers where PyMuPDF garbles tables/columns.
If any papers are scanned images (rare but possible in older papers), keep pytesseract in your back pocket for OCR — don't build for it up front, just handle exceptions.
Cache extracted text to disk (json/txt) keyed by paper ID so you never re-parse a PDF twice.

LLM calls

anthropic Python SDK, using tool-use (forced tool_choice) rather than "please output JSON" prompting. Define a tool schema with decision, reasoning, confidence — this is far more reliable than parsing free-text JSON and eliminates a whole class of parsing failures.
Message Batches API for the full 2115×4 run — exactly as you noted, 50% cheaper and built for this.
Model split: Sonnet 4.6 for rubric-building iteration and the main run; Opus reserved for the two-pass low-confidence review.

Storage

SQLite, single file. At ~8,500 rows total this is trivial for SQLite and gives you free querying/resumability without standing up a database server. Use raw sqlite3 or lightweight SQLAlchemy — no need for anything heavier.
Store: paper_id, task, decision, reasoning, confidence, model_used, rubric_version, timestamp. This becomes your audit trail and lets you resume interrupted runs.

Rubrics

Plain Markdown files, one per task, tracked in git. Git gives you free version history and diffing of how each rubric evolves — genuinely useful when you want to see what changed and why accuracy moved.

Supporting libraries

pydantic — validates/parses tool_use outputs into typed objects.
tenacity — retry logic for API calls (rate limits, transient errors).
tqdm — progress bars for batch loops.
python-dotenv — API key management.
pandas — for the regression-accuracy tracking and result exports.
Optional, only if you go the retrieval route for few-shot examples later: Voyage AI embeddings (Anthropic's recommended embedding provider) + a simple numpy/FAISS similarity search. Not needed at the start — hand-picking 10-15 examples is simpler and you only have 500 cases to choose from.
Project layout
project/
├── data/
│   ├── raw_pdfs/
│   │   ├── validation/          # 500 labeled papers
│   │   └── full_set/            # 2115 papers
│   ├── extracted_text/          # cached .txt/.json per paper, by ID
│   └── labels/
│       └── validation_labels.csv
│
├── rubrics/
│   ├── exclusion.md
│   ├── inclusion.md
│   ├── power_analysis.md
│   └── data_analysis.md         # git history = your rubric version log
│
├── src/
│   ├── pdf_extract.py           # PDF -> cached text, with fallback logic
│   ├── schemas.py               # pydantic models: Decision, Reasoning, Confidence
│   ├── llm_client.py            # wraps anthropic client; sync calls + batch calls
│   ├── rubric_builder.py        # the interactive train-the-rubric loop
│   ├── evaluate.py              # regression test: rubric vs full 500, per-task metrics
│   ├── two_pass.py              # Sonnet first pass -> flag low-confidence -> Opus review
│   ├── batch_runner.py          # builds/submits/polls Batch API jobs
│   └── db.py                    # SQLite access layer
│
├── scripts/
│   ├── 01_extract_pdfs.py
│   ├── 02_build_rubric.py       # --task exclusion|inclusion|power|data
│   ├── 03_run_regression.py
│   ├── 04_run_full_batch.py
│   └── 05_collect_results.py
│
├── results/
│   ├── rubric_accuracy_history.csv   # accuracy per task per rubric version
│   └── full_run_predictions.csv
│
├── tests/
├── .env
├── requirements.txt
└── README.md
How the pieces work together

1. Extraction (once, up front) — pdf_extract.py converts all 2,615 PDFs (500 validation + 2115 study) to cached text keyed by paper ID. Do this once; every downstream step reads cached text, never re-parses PDFs.

2. Structured judgments — schemas.py defines the tool schema Claude must fill: {decision: bool, reasoning: str, confidence: float}. llm_client.py calls Claude with tool_choice forcing that schema, for a given (paper text, task, current rubric) triple. One function, reused across all 4 tasks and both the rubric-building loop and the final run.

3. Rubric-building loop (rubric_builder.py) — for one task at a time:

Load current rubric markdown.
Sample a batch (<100) of validation papers not yet reviewed this round.
Get judgment + reasoning + confidence from the model.
Compare to the known validation label.
On a miss, add the specific case (or a generalized rule) to the rubric as a worked example or edge-case note. Log the review to SQLite either way.

4. Regression testing (evaluate.py) — periodically re-run the current rubric against all 500 validation papers (not just the latest batch), compute accuracy/precision/recall per task, and append to rubric_accuracy_history.csv with a rubric version tag (git commit hash works well here). This is how you know if a rubric change helped or regressed something.

5. Two-pass classification (two_pass.py) — once rubrics stabilize, run Sonnet across a sample, flag anything below a confidence threshold (tune this against the validation set), and route only those to Opus.

6. Full run (batch_runner.py) — once all 4 rubrics are stable and the confidence threshold is tuned, submit the real job: 2115 papers × 4 tasks = 8,460 calls via the Message Batches API, poll for completion, then run flagged low-confidence cases through Opus.

Steps to get started
Set up the repo, requirements.txt, .env with your API key, and git init (rubrics live in git from day one).
Run PDF extraction on the 500 validation papers first (leave the 2115 for later — no need to touch them yet).
Load validation_labels.csv into SQLite.
Write rubric v0 for exclusion only — literally just: "exclude if secondary analysis."
Run rubric_builder.py --task exclusion on a first batch of <100 validation papers.
Review the misses, hand-update rubrics/exclusion.md with the specific edge cases, commit.
Run evaluate.py --task exclusion against the full 500 to get a real accuracy number — this is your baseline.
Repeat steps 5–7, batch by batch, until exclusion accuracy plateaus.
Only then move to inclusion, then power analysis, then data analysis — same loop, independent rubric each time, never mixing criteria across tasks.
Once all 4 rubrics are stable, tune the confidence threshold for two-pass review on a validation subsample.
Extract text for the remaining 2115 papers.
Submit the full Batch API job, collect results, run the Opus second pass on flagged cases, merge and export.

One thing worth deciding before you start coding: do you want the rubric updates in step 6 to be manual (you read the miss and write the rule) or model-assisted (feed the miss + current rubric to Opus and ask it to propose the update)? Both work — model-assisted is faster but you'll want to spot-check its proposed rules before committing them.
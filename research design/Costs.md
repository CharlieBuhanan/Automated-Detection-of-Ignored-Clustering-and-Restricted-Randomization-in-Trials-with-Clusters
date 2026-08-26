# Costs

Budget for run 1: **$100. Target ~$60.** Proof of concept, not the final study.

All figures measured from the corpus on 2026-08-26, not estimated:
**15,470 input tokens per call** (13,570 paper text + 1,600 promptbook + ~300
scaffolding), ~300 output. Corpus: 1,306 US papers; survivors projected at 36%
(the HLS rate, 176/483) = **476**, so 1,306 + 476×2 = **2,258 single-pass calls**.

Prices per 1M tokens, Batch API at half:

| Model | Input | Output |
|---|---:|---:|
| Claude Opus 5 | $5.00 | $25.00 |
| Claude Sonnet 5 | $2.00 | $10.00 |
| Claude Haiku 4.5 | $1.00 | $5.00 |

---

## The plan for run 1

Refinement on the **Claude Code CLI** against subscription quota ($0 API,
DC22). The $100 is reserved entirely for the Batch API production run.

| Stage | Calls | Model | Cost |
|---|---:|---|---:|
| Gate run — exclusion, all 1,306 | 1,306 | Sonnet 5 batch | $22.16 |
| Opus second pass on low-confidence gate calls (~15%) | 196 | Opus 5 batch | $8.32 |
| Analysis run — power + data, 476 survivors × 2 | 952 | Sonnet 5 batch | $16.16 |
| Opus second pass (~15%) | 143 | Opus 5 batch | $6.07 |
| Holdout — 145 exclusion + 53×2 power/data | 251 | Sonnet 5 batch | $4.26 |
| Opus second pass (~15%) | 38 | Opus 5 batch | $1.61 |
| **Total** | **2,886** | | **$58.58** |

**$58.58 against a $100 budget, $41 of headroom.** The headroom is not spare
money — it absorbs a survivor rate higher than 36% (every extra survivor is two
more calls) and a second-pass rate higher than 15%.

**One vote, not three.** Self-consistency is the single biggest cost multiplier
and it is out of reach here (see below). Run 1 reports single-pass numbers.

**The Opus second pass stays.** It is $16 of the $59 and it is the piece that
cannot be added later: a false exclusion is unrecoverable (DC11), because the
paper never reaches power or data analysis and leaves the study silently. Cut
votes before cutting this.

---

## Self-consistency voting

From slide 12. Ask the model the same question several times, take the majority.
Cost is **linear in votes** — there is no discount for asking twice.

| Votes | Calls | Input tokens | Sonnet 5 batch | Opus 5 batch |
|---:|---:|---:|---:|---:|
| 1 | 2,258 | 34.9M | **$38.32** | $95.80 |
| 3 | 6,774 | 104.8M | $114.95 | $287.39 |
| 11 | 24,838 | 384.2M | $421.50 | $1,053.75 |

**3 votes on Sonnet is $115 — over budget before the second pass or the holdout
is counted.** Hence one vote for run 1.

What voting bought Cao et al. on full-text screening with ISO-ScreenPrompt
(1 → 11 votes): accuracy 96.5 → 97.5 on SeroTracker, 83.3 → 87.5 on Reinfection.
**One to four points for 2.6× the cost**, with the largest gains in specificity
on their worst dataset, and most of the gain arriving well before the eleventh
vote. Three votes is the efficient point if the budget ever allows it.

Voting is also a **tunable dial, not just a majority** — Cao swept the threshold
from 0 to 12 to trade sensitivity against specificity and drew an ROC curve from
it. That is the argument for voting on the *gate* specifically, where the
sensitivity/specificity trade has real consequences. It is deferred, not
rejected.

> Cao varied the random seed per vote. Claude exposes neither seed nor
> temperature, so votes here vary through the model's own stochasticity. This is
> sound: the API is stateless, so three calls on one paper are three independent
> opinions, not one opinion repeated.

### Corrections to slide 10

Two numbers on that slide are wrong and should be restated before it is shown
again:

| | Slide 10 says | Correct |
|---|---|---|
| Sonnet price | $3 / $15 per 1M | **$2 / $10** — that was Sonnet 4.6; Sonnet 5 is cheaper |
| Sonnet single pass, batch | $58 | **$38.32** |
| Sonnet 3-vote, batch | $174 | **$114.95** |
| Call counts | 1,284 + ~920 = 2.2k | **1,306 + 952 = 2,258** (post-DC42 restore) |
| Promptbook development | "roughly $200 of Opus calls" | **$0** — refinement runs on the CLI against subscription quota (DC22) |

The Opus rows on that slide (~$97 batch single-pass) were close to right; the
Sonnet rows were ~35% too high. The slide's conclusion holds and gets stronger:
batch is the obvious choice, and cost is not the binding constraint.

---

## Why subsetting the build split is a false economy

The standing rule is that after any promptbook change, the **whole build split**
is re-run, not just the latest batch. That is 338 exclusion calls plus 123
survivors × 2 for power and data = **584 calls**.

| Regression scope | Calls | Sonnet 5 batch |
|---|---:|---:|
| Full build split | 584 | $9.91 |
| Half the build split | 292 | $4.96 |
| **Saved per round** | | **$4.96** |

**Halving the regression set saves about $5 a round.** Across twenty rounds that
is $99 — real money against this budget, but it buys the saving with the one
number the loop depends on.

Plateau is defined as two consecutive rounds each improving accuracy by under
1pp (DC17). On 338 exclusion papers, one paper flipping moves accuracy 0.30pp;
on 169, it moves 0.59pp. Halving the set nearly doubles the noise floor while
leaving the threshold at 1pp, so the plateau rule starts firing on sampling
noise — and "we stopped iterating" becomes a claim about the sample rather than
the promptbook. The same halving makes each round's Δ noisier than the effect
being measured on the small tasks: power and data are scored on 123 survivors
already, and 61 is not a number to make a stopping decision on.

**And in this budget it saves nothing at all**, because refinement runs on the
CLI: the $9.91 is what a regression *would* cost on the API, not what run 1
pays. The real cost of a full regression here is wall-clock — one process per
paper, no caching, ~40s each, eight in parallel ≈ **50 minutes**. That is the
thing worth optimizing, and the fix is parallelism, not a smaller sample.

Keep the full build split.

---

## Two levers that do not work

**Prompt caching saves ~9%, not 90%.** Caching is a prefix match, and the only
stable prefix here is the promptbook: 1,600 of 15,470 input tokens. The paper
text is 88% of the input and is unique to every call, so it can never be cached.
Worth turning on, not worth designing around.

**Truncating the paper text is not on the table for run 1.** It is the only lever
big enough to matter — cutting to Methods + Statistical Analysis would remove
most of the 13,570 tokens — but it changes what the model is judging, which
makes run 1 unable to answer the question it exists to answer. Revisit only with
a measured comparison on the build split.

---

## If the budget is cut further

In order, cheapest damage first:

1. **Drop the holdout to the end of run 2** (−$5.87). It is the honest accuracy
   number, so this only works if run 1 is explicitly framed as a pipeline test.
2. **Gate only, no analysis run** (−$22.23). Produces a survivor count and a
   drop-reason breakdown, which is a study result in its own right, and defers
   power/data entirely.
3. **Haiku 4.5 for the primary pass** (−$11 on the gate). Halves Sonnet's price
   and the 200K context is ample. Not recommended: it changes the model whose
   accuracy the promptbook was tuned against, and every number becomes
   provisional.

Do not cut the Opus second pass.

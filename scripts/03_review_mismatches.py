"""Review the flagged PDFs by hand, one at a time, in a small desktop window.

HOW TO USE
    python scripts/03_review_mismatches.py

    A window opens showing one flagged paper at a time. For each one:

      1. Click "Open PDF" to see what is actually in the file, and
         "Open DOI" / "Open PubMed" to see what the paper should be.
         "Open in Zotero" jumps straight to the record so you can grab the
         right attachment.

      2. Then pick one:
         - No Issue        the PDF really is this paper; clears the flag
         - Replace PDF...  choose the correct PDF (e.g. one you just saved
                           out of Zotero). It is copied into place, the old
                           file is backed up, and identity verification is
                           re-run immediately so you can see whether the new
                           file passes before moving on.
         - Drop            no correct PDF exists; the paper leaves the corpus
         - Skip            decide later

    Every choice saves the moment you make it, so closing the window never
    loses work. On the next launch (if any paper has already been decided)
    you're asked to choose:
         - Only unreviewed    hide anything already marked No Issue,
                               Replace, or Drop -- Skipped papers still show,
                               since Skip means "decide later," not "done."
         - Show all           the full queue, including decided papers, so
                               you can revisit and change an earlier choice.

INPUT   results/review/01_papers_to_review.csv
OUTPUT  results/review/04_papers_reviewed_results.csv   your decisions, appended
            one row per click and never rewritten, so revisiting a paper leaves
            both rows behind. The last row for a paper is its current decision.
        data/zotero_manifest.csv                        verdicts updated
        data/removed_pdfs/replaced/                     backups of replaced PDFs

Deciding here is what unblocks the corpus: research design/PLAN.md step 2 extracts VERIFIED
papers only, so a flagged paper contributes nothing until it is resolved.
"""

import csv
import hashlib
import os
import shutil
import subprocess
import sys
import webbrowser
from datetime import datetime, timezone
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import identity
from pdf_extract import extract_head_text
from zotero_fetch import MANIFEST_COLUMNS, SET_UNLABELLED, load_meta, set_dir

ROOT = Path(__file__).resolve().parent.parent
REVIEW_LIST = ROOT / "results" / "review" / "01_papers_to_review.csv"
RESULTS = ROOT / "results" / "review" / "04_papers_reviewed_results.csv"
MANIFEST = ROOT / "data" / "zotero_manifest.csv"
META = ROOT / "data" / "zotero_meta.jsonl"
BACKUP_DIR = ROOT / "data" / "removed_pdfs" / "replaced"

# Zotero group IDs, so "Open in Zotero" can build a working link. The manifest
# records the collection a paper came from but not its group, so the group is
# recovered from set + collection name. Edit these if the corpus grows.
ZOTERO_GROUPS = {
    SET_UNLABELLED: "6586218",
    "FinalCollectionFor Publication": "5573699",   # NCI
    "Locked_26_01_08_337": "6363893",              # NHLBI
    # The 15 NCI/NHLBI duplicate pairs were merged into one row each, keeping
    # the NCI item key -- so the NCI group is where "Open in Zotero" finds them.
    "Both NCI and NHLBI": "5573699",
}

RESULT_COLUMNS = [
    "reviewed_at", "paper_id", "set", "decision", "old_verdict", "new_verdict",
    "new_pdf_source", "notes", "doi", "pmid", "title",
]

DECISION_COLORS = {
    "no_issue": "#1a7f37",
    "replaced": "#0969da",
    "dropped": "#a40e26",
    "skipped": "#9a6700",
    "resolved_elsewhere": "#6e7781",
}

# A paper counts as "settled" once it has one of these decisions -- the ones
# the startup chooser can hide. "skipped" is deliberately excluded: it means
# "decide later," so it stays visible in both scopes. "resolved_elsewhere"
# means a different step already removed the paper from the corpus, which is
# also settled -- but those rows never reach the chooser at all, since
# _drop_stale removes them from self.papers before scope filtering runs.
SETTLED_DECISIONS = {"no_issue", "replaced", "dropped"}


def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def append_results(rows: list[dict]) -> None:
    """Add decision rows to the results log, keeping everything already in it.

    Append-only on purpose. The log is the record of every decision ever made,
    including ones later revised, so it must never be rebuilt from what this
    run happens to be holding: an in-memory rewrite can only contain the papers
    in the current -- possibly scope-filtered -- view, and silently erases the
    rest. That is exactly how 23 of 24 rows were lost once. Duplicate
    paper_ids are expected and fine; load_decisions() takes the last one.
    """
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    fresh = not RESULTS.exists() or RESULTS.stat().st_size == 0
    with RESULTS.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
        if fresh:
            writer.writeheader()
        writer.writerows(rows)


def load_decisions() -> dict:
    """Current decision per paper: the last row wins.

    The log is append-only and written in the order decisions were made, so a
    later row for a paper supersedes any earlier one.
    """
    return {r["paper_id"]: r for r in read_csv(RESULTS)}


def filter_by_scope(papers: list[dict], decisions: dict, scope: str) -> list[dict]:
    """Apply the startup chooser's answer. Pure function, no I/O -- kept
    separate from the dialog so the filtering logic can be tested without a
    display."""
    if scope == "all":
        return papers
    return [p for p in papers if decisions.get(p["paper_id"], {}).get("decision") not in SETTLED_DECISIONS]


def open_path(path: Path):
    """Open a file in whatever the OS uses for it."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", str(path)], check=False)
        else:
            subprocess.run(["xdg-open", str(path)], check=False)
    except Exception as exc:
        messagebox.showerror("Could not open", f"{path}\n\n{exc}")


class ReviewApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.all_papers = self._drop_stale(read_csv(REVIEW_LIST))
        if not self.all_papers:
            messagebox.showerror("Nothing to review", f"No rows in {REVIEW_LIST}")
            root.destroy()
            return

        self.meta = load_meta(META)
        self.decisions = load_decisions()

        scope = self._choose_scope()
        self.papers = filter_by_scope(self.all_papers, self.decisions, scope)
        if not self.papers:
            messagebox.showinfo(
                "Nothing unreviewed",
                f"All {len(self.all_papers)} paper(s) are already decided.\n\n"
                "Re-launch and choose \"Show all\" to revisit any of them.")
            root.destroy()
            return

        self.index = self._first_undecided()

        root.title("Automated Ignore - flagged PDF triage")
        root.geometry("980x760")
        root.minsize(860, 680)
        self._build()
        self._show()

    # ---------------------------------------------------------------- startup scope
    def _choose_scope(self) -> str:
        """Ask once at launch whether to see everything or only what's left.

        Skipped only when there is nothing settled yet to hide -- a first-ever
        run, or one where every paper is still undecided/skipped -- since the
        choice would be meaningless.
        """
        settled = sum(1 for p in self.all_papers
                     if self.decisions.get(p["paper_id"], {}).get("decision") in SETTLED_DECISIONS)
        if settled == 0:
            return "all"

        pending = len(self.all_papers) - settled
        choice = {"value": "pending"}   # default if the window is closed outright

        dialog = tk.Toplevel(self.root)
        dialog.title("Resume review")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.protocol("WM_DELETE_WINDOW", lambda: pick("pending"))

        tk.Label(dialog, text="Welcome back", font=("Segoe UI", 13, "bold")).pack(padx=24, pady=(20, 4))
        tk.Label(
            dialog,
            text=f"{settled} of {len(self.all_papers)} paper(s) already have a decision\n"
                 f"(No Issue / Replace / Drop). {pending} remain (including any Skipped).",
            font=("Segoe UI", 10), justify="center", fg="#57606a",
        ).pack(padx=24, pady=(0, 16))

        def pick(value):
            choice["value"] = value
            dialog.destroy()

        row = tk.Frame(dialog)
        row.pack(padx=20, pady=(0, 20))
        tk.Button(row, text=f"Only unreviewed ({pending})", command=lambda: pick("pending"),
                  bg="#0969da", fg="white", font=("Segoe UI", 10, "bold"),
                  width=20, height=2, relief="flat", cursor="hand2").pack(side="left", padx=6)
        tk.Button(row, text=f"Show all ({len(self.all_papers)})", command=lambda: pick("all"),
                  font=("Segoe UI", 10), width=16, height=2, cursor="hand2").pack(side="left", padx=6)

        dialog.update_idletasks()
        x = self.root.winfo_screenwidth() // 2 - dialog.winfo_width() // 2
        y = self.root.winfo_screenheight() // 2 - dialog.winfo_height() // 2
        dialog.geometry(f"+{x}+{y}")

        dialog.grab_set()
        self.root.wait_window(dialog)
        return choice["value"]

    # ---------------------------------------------------------------- staleness
    def _drop_stale(self, papers: list[dict]) -> list[dict]:
        """Remove rows for papers no longer in the manifest, and say why.

        This is what caught 6AUXHCLQ: it was in the review queue when this
        file was built, then removed from the Unlabelled Set as a cross-set duplicate of
        J2XGTHGE by a step that runs independently of this one. Without this
        check the GUI reports "not on disk" for a paper that was never lost --
        it just moved, or was intentionally dropped -- which reads as a bug
        rather than as already-resolved. Logged as `resolved_elsewhere` so the
        results file stays a record of every paper ever flagged, not only the
        ones decided by hand.
        """
        manifest_ids = {r["paper_id"] for r in read_csv(MANIFEST)}
        removed_reason = {
            r["removed_paper_id"]: f"removed as a cross-set duplicate of "
                                    f"{r['matched_validation_paper_id']} (kept in the Human Labelled Set)"
            for r in read_csv(REVIEW_LIST.parent / "02_removed_testing_duplicates.csv")
        }

        kept, skipped = [], []
        for p in papers:
            if p["paper_id"] in manifest_ids:
                kept.append(p)
            else:
                skipped.append(p)

        if skipped:
            already_logged = load_decisions()
            try:
                append_results([
                    {
                        "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "paper_id": p["paper_id"], "set": p["set"],
                        "decision": "resolved_elsewhere",
                        "old_verdict": p["verdict"], "new_verdict": "",
                        "new_pdf_source": "",
                        "notes": removed_reason.get(
                            p["paper_id"], "no longer in data/zotero_manifest.csv"),
                        "doi": p["doi"], "pmid": p["pmid"], "title": p["title"],
                    }
                    for p in skipped if p["paper_id"] not in already_logged
                ])
            except PermissionError:
                # Not worth blocking the review over: these rows are a note to
                # self, and the papers are already out of the corpus.
                messagebox.showwarning(
                    "Could not write the results log",
                    f"{RESULTS}\n\nis locked by another program (Excel?). The papers below "
                    "were still removed from the queue, but were not logged.")

            lines = "\n".join(
                f"  - {p['paper_id']}: {removed_reason.get(p['paper_id'], 'no longer in the manifest')}"
                for p in skipped
            )
            messagebox.showinfo(
                "Some papers were already resolved",
                f"{len(skipped)} paper(s) were removed from the queue because they are no longer "
                f"in the corpus (likely resolved by another step):\n\n{lines}\n\n"
                "Logged to 04_papers_reviewed_results.csv as 'resolved_elsewhere'.")

        return kept

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 14, "pady": 6}

        header = tk.Frame(self.root)
        header.pack(fill="x", **pad)
        self.counter = tk.Label(header, text="", font=("Segoe UI", 15, "bold"))
        self.counter.pack(side="left")
        self.badge = tk.Label(header, text="", font=("Segoe UI", 10, "bold"),
                              fg="white", bg="#a40e26", padx=10, pady=3)
        self.badge.pack(side="left", padx=12)
        self.decided_lbl = tk.Label(header, text="", font=("Segoe UI", 10), fg="#57606a")
        self.decided_lbl.pack(side="right")

        self.title_lbl = tk.Label(self.root, text="", font=("Segoe UI", 12, "bold"),
                                  wraplength=930, justify="left", anchor="w")
        self.title_lbl.pack(fill="x", **pad)

        box = tk.LabelFrame(self.root, text=" What was found ", font=("Segoe UI", 10, "bold"),
                            fg="#a40e26")
        box.pack(fill="x", **pad)
        self.finding_lbl = tk.Label(box, text="", wraplength=910, justify="left",
                                    anchor="w", font=("Segoe UI", 10))
        self.finding_lbl.pack(fill="x", padx=10, pady=(6, 2))
        self.action_lbl = tk.Label(box, text="", wraplength=910, justify="left",
                                   anchor="w", font=("Segoe UI", 10, "italic"), fg="#57606a")
        self.action_lbl.pack(fill="x", padx=10, pady=(0, 8))

        self.facts = tk.Label(self.root, text="", justify="left", anchor="w",
                              font=("Consolas", 10), fg="#24292f")
        self.facts.pack(fill="x", **pad)

        links = tk.Frame(self.root)
        links.pack(fill="x", **pad)
        for text, cmd in (
            ("Open PDF", self.open_pdf),
            ("Open DOI", self.open_doi),
            ("Open PubMed", self.open_pubmed),
            ("Open in Zotero", self.open_zotero),
        ):
            tk.Button(links, text=text, command=cmd, font=("Segoe UI", 10),
                      width=15, height=1).pack(side="left", padx=4)

        notes_row = tk.Frame(self.root)
        notes_row.pack(fill="x", **pad)
        tk.Label(notes_row, text="Notes:", font=("Segoe UI", 10)).pack(side="left")
        self.notes = tk.Entry(notes_row, font=("Segoe UI", 10))
        self.notes.pack(side="left", fill="x", expand=True, padx=8)

        actions = tk.Frame(self.root)
        actions.pack(fill="x", **pad)
        specs = [
            ("No Issue\n(PDF is correct)", "#1a7f37", lambda: self.decide("no_issue")),
            ("Replace PDF...\n(pick the right file)", "#0969da", self.replace_pdf),
            ("Drop\n(no valid PDF exists)", "#a40e26", lambda: self.decide("dropped")),
            ("Skip\n(decide later)", "#6e7781", lambda: self.decide("skipped")),
        ]
        for text, color, cmd in specs:
            tk.Button(actions, text=text, command=cmd, bg=color, fg="white",
                      font=("Segoe UI", 10, "bold"), width=22, height=3,
                      relief="flat", cursor="hand2").pack(side="left", padx=5, expand=True, fill="x")

        self.status = tk.Label(self.root, text="", font=("Segoe UI", 10), anchor="w",
                               wraplength=930, justify="left")
        self.status.pack(fill="x", **pad)

        nav = tk.Frame(self.root)
        nav.pack(fill="x", side="bottom", **pad)
        tk.Button(nav, text="< Prev", command=self.prev, width=12).pack(side="left")
        tk.Button(nav, text="Next >", command=self.next, width=12).pack(side="right")
        self.progress = ttk.Progressbar(nav, mode="determinate")
        self.progress.pack(side="left", fill="x", expand=True, padx=14)

    # ---------------------------------------------------------------- state
    @property
    def paper(self):
        return self.papers[self.index]

    def _first_undecided(self):
        for i, p in enumerate(self.papers):
            d = self.decisions.get(p["paper_id"])
            if not d or d["decision"] == "skipped":
                return i
        return 0

    def pdf_path(self, paper=None):
        p = paper or self.paper
        return set_dir(ROOT, p["set"]) / f"{p['paper_id']}.pdf"

    def _show(self):
        p = self.paper
        n = len(self.papers)
        self.counter.config(text=f"Paper {self.index + 1} of {n}")
        self.badge.config(text=f"  {p['category']}  ",
                          bg="#a40e26" if p["priority"] == "1" else "#9a6700")
        self.title_lbl.config(text=p["title"])
        self.finding_lbl.config(text=p["finding"])
        self.action_lbl.config(text=f"Suggested: {p['recommended_action']}")

        exists = self.pdf_path().exists()
        self.facts.config(text=(
            f"paper_id : {p['paper_id']}          set: {p['set']}          "
            f"folder: {p['folder']}\n"
            f"verdict  : {p['verdict']} ({p['verdict_reason']})   title_score: {p['title_score']}\n"
            f"DOI      : {p['doi'] or '(none)'}\n"
            f"PMID     : {p['pmid'] or '(none)'}\n"
            f"PDF      : {self.pdf_path().relative_to(ROOT)}"
            f"{'' if exists else '   [MISSING ON DISK]'}"
        ))

        self.decided_lbl.config(text=f"decided {self._decided_count()} / {n}")
        self.progress.config(maximum=n, value=self.index + 1)

        prior = self.decisions.get(p["paper_id"])
        self.notes.delete(0, "end")
        if prior:
            self.notes.insert(0, prior.get("notes", ""))
            self.status.config(
                text=f"Already decided: {prior['decision'].upper()}"
                     + (f" -> {prior['new_verdict']}" if prior.get("new_verdict") else "")
                     + "   (choosing again will overwrite this)",
                fg=DECISION_COLORS.get(prior["decision"], "#57606a"))
        else:
            self.status.config(text="", fg="#57606a")

    # ---------------------------------------------------------------- links
    def open_pdf(self):
        path = self.pdf_path()
        if not path.exists():
            messagebox.showwarning("No PDF", f"Not on disk:\n{path}")
            return
        open_path(path)

    def open_doi(self):
        doi = self.paper["doi"].strip()
        if doi:
            webbrowser.open(f"https://doi.org/{doi}")
        else:
            messagebox.showinfo("No DOI", "This record has no DOI.")

    def open_pubmed(self):
        p = self.paper
        if p["pmid"].strip():
            webbrowser.open(f"https://pubmed.ncbi.nlm.nih.gov/{p['pmid'].strip()}/")
            return
        meta = self.meta.get(p["paper_id"], {})
        if meta.get("pmcid"):
            webbrowser.open(f"https://www.ncbi.nlm.nih.gov/pmc/articles/{meta['pmcid']}/")
            return
        messagebox.showinfo("No PMID", "This record has no PMID or PMCID.")

    def open_zotero(self):
        p = self.paper
        group = ZOTERO_GROUPS.get(p["folder"]) or ZOTERO_GROUPS.get(p["set"])
        key = p["attachment_key"] or p["paper_id"]
        # The parent item is what you want to see, not the attachment.
        webbrowser.open(f"zotero://select/groups/{group}/items/{p['paper_id']}"
                        if group else f"zotero://select/items/{key}")

    # ---------------------------------------------------------------- actions
    def replace_pdf(self):
        p = self.paper
        chosen = filedialog.askopenfilename(
            title=f"Choose the correct PDF for {p['paper_id']}",
            filetypes=[("PDF files", "*.pdf"), ("All files", "*.*")])
        if not chosen:
            return
        src = Path(chosen)
        with src.open("rb") as handle:
            if handle.read(5)[:4] != b"%PDF":
                messagebox.showerror("Not a PDF", f"{src.name} does not look like a PDF.")
                return

        dest = self.pdf_path()
        if src.resolve() == dest.resolve():
            messagebox.showinfo(
                "Same file",
                "That is the PDF already in place, so nothing would change.\n\n"
                "If this file is in fact correct, choose \"No Issue\" instead.")
            return

        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            shutil.copy2(dest, BACKUP_DIR / f"{p['paper_id']}_{stamp}.pdf")
        shutil.copy2(src, dest)

        # Re-check straight away: the whole point is to see whether the file you
        # picked actually is the paper, while you still have Zotero open.
        meta = self.meta.get(p["paper_id"])
        if meta:
            head, _pages, _m = extract_head_text(dest)
            result = identity.verify(head, meta)
            verdict, explain = result["verdict"], result["explanation"]
        else:
            verdict, explain = "UNKNOWN", "no Zotero metadata to compare against"

        good = verdict == identity.VERIFIED
        # Keep the row on screen honest: navigating back should not still show
        # the verdict of a file that is no longer there.
        p["verdict"], p["verdict_reason"] = verdict, "MANUAL_REPLACED"

        self.status.config(
            text=("PASSED - " if good else "STILL FLAGGED - ")
                 + f"{verdict}: {explain}"
                 + ("" if good else "\nThe file was still saved. Try another attachment, or Drop."),
            fg="#1a7f37" if good else "#a40e26")
        self.decide("replaced", new_verdict=verdict, source=str(src), advance=good)

    def decide(self, decision, new_verdict="", source="", advance=True):
        p = self.paper
        if decision == "no_issue":
            new_verdict = "VERIFIED"
        elif decision == "dropped":
            new_verdict = "DROPPED"

        row = {
            "reviewed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "paper_id": p["paper_id"], "set": p["set"], "decision": decision,
            "old_verdict": p["verdict"], "new_verdict": new_verdict,
            "new_pdf_source": source, "notes": self.notes.get().strip(),
            "doi": p["doi"], "pmid": p["pmid"], "title": p["title"],
        }
        if not self._save_result(row):
            return
        self.decisions[p["paper_id"]] = row
        if new_verdict and decision != "skipped":
            self._update_manifest(p["paper_id"], decision, new_verdict)
        if decision in ("replaced", "dropped"):
            self._invalidate_cache(p["paper_id"], decision)

        if decision != "replaced":
            self.status.config(text=f"Recorded: {decision.upper()}"
                                    + (f" -> {new_verdict}" if new_verdict else ""),
                               fg=DECISION_COLORS.get(decision, "#57606a"))
        if advance:
            self.root.after(450 if decision != "replaced" else 1400, self.next)
        else:
            self._show_counts_only()

    def _show_counts_only(self):
        self.decided_lbl.config(text=f"decided {self._decided_count()} / {len(self.papers)}")

    def _decided_count(self) -> int:
        """How many papers in the *current, possibly filtered* view have a
        non-skip decision -- scoped to self.papers, not every decision ever
        made, so the count stays meaningful in "only unreviewed" scope."""
        return sum(
            1 for p in self.papers
            if self.decisions.get(p["paper_id"], {}).get("decision") not in (None, "skipped")
        )

    # ---------------------------------------------------------------- writing
    def _save_result(self, row) -> bool:
        """Log one decision. False means it did not reach disk, so the caller
        must not go on to update the manifest -- a manifest verdict with no
        matching log row is how the two records drift apart."""
        try:
            append_results([row])
            return True
        except PermissionError:
            # Almost always the results file being open in Excel.
            messagebox.showerror(
                "Could not save your decision",
                f"{RESULTS}\n\nis locked by another program (Excel?).\n\n"
                "Nothing was recorded. Close the file and choose this paper again.")
            return False

    def _invalidate_cache(self, paper_id, decision):
        """Throw away text extracted from a PDF that is no longer the paper's.

        `src/pdf_extract.py` also detects this on its own (it compares the
        cached pdf_md5 against the file), so this is belt and braces -- but the
        window between replacing a PDF here and re-running extraction is
        exactly when someone might read the cache, and during that window the
        cached text is another document entirely. Deleting it makes the text
        missing instead of wrong, which is the failure that gets noticed.
        """
        cache_path = ROOT / "data" / "extracted_text" / f"{paper_id}.json"
        if not cache_path.exists():
            return
        try:
            cache_path.unlink()
        except OSError as exc:
            messagebox.showwarning(
                "Could not clear the cached text",
                f"{cache_path}\n\n{exc}\n\nRe-run scripts/02_extract_pdfs.py --overwrite "
                f"before trusting this paper's text.")
            return
        self.status.config(
            text=self.status.cget("text")
                 + f"\nCleared cached text; re-run 02_extract_pdfs.py to "
                   f"{'re-extract' if decision == 'replaced' else 'drop'} it.",
            fg=self.status.cget("fg"))

    def _update_manifest(self, paper_id, decision, new_verdict):
        """Push the decision into the manifest so later steps see it.

        Verdicts drive what gets extracted and classified, so a decision that
        stopped at the log would have no effect on the study.
        """
        rows = read_csv(MANIFEST)
        for row in rows:
            if row["paper_id"] != paper_id:
                continue
            row["verdict"] = new_verdict
            row["verdict_reason"] = {
                "no_issue": "MANUAL_OK",
                "replaced": "MANUAL_REPLACED",
                "dropped": "MANUAL_DROPPED",
            }.get(decision, row.get("verdict_reason", ""))

            # Re-hash after a replacement, or the fetch script destroys this work.
            # completed_ids() skips a paper only when the file on disk still
            # hashes to this column; leaving the old Zotero md5 here would make
            # the next ordinary 00_fetch_zotero.py run treat the paper as stale
            # and re-download the very PDF that was just rejected.
            path = set_dir(ROOT, row["set"]) / f"{paper_id}.pdf"
            if decision == "replaced" and path.exists():
                row["md5"] = hashlib.md5(path.read_bytes()).hexdigest()
                row["detail"] = "manually replaced during review"
            break

        try:
            with MANIFEST.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(handle, fieldnames=MANIFEST_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except PermissionError:
            # Almost always the manifest being open in Excel. Say so plainly --
            # the decision is already safe in the results log either way.
            messagebox.showerror(
                "Could not write the manifest",
                f"{MANIFEST}\n\nis locked by another program (Excel?).\n\n"
                "Your decision was saved to the results log. Close the file and "
                "choose this paper again to update the manifest.")

    # ---------------------------------------------------------------- nav
    def next(self):
        if self.index < len(self.papers) - 1:
            self.index += 1
            self._show()
        else:
            self._finish()

    def prev(self):
        if self.index > 0:
            self.index -= 1
            self._show()

    def _finish(self):
        left = [p["paper_id"] for p in self.papers
                if p["paper_id"] not in self.decisions
                or self.decisions[p["paper_id"]]["decision"] == "skipped"]
        if left:
            messagebox.showinfo(
                "End of list",
                f"{len(left)} paper(s) still undecided (skipped or untouched).\n\n"
                "Use < Prev to go back, or re-run the script later - it reopens "
                "at the first undecided paper.")
        else:
            scope_note = (f" (of {len(self.all_papers)} total; the rest were already decided)"
                         if len(self.papers) < len(self.all_papers) else "")
            messagebox.showinfo("All done",
                                f"All {len(self.papers)} paper(s) in this view reviewed{scope_note}.\n\n"
                                f"Decisions saved to:\n{RESULTS}")
        self._show()


def main():
    if not REVIEW_LIST.exists():
        sys.exit(f"Missing {REVIEW_LIST}. Run the identity verification step first.")
    root = tk.Tk()
    ReviewApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()

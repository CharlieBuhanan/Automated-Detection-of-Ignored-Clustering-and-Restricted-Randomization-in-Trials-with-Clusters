"""Group I: how a round is driven. Serial by default, and serial actually stops.

The cases here are about spend, not correctness of a judgment. `--workers 6`
commits six papers of a five-hour subscription window before the first result is
readable, and the whole point of making serial the default is that a round which
has gone wrong can be stopped while the rest of the quota is still unspent.

That property has a precise mechanical form -- `serial_runner` must be **lazy**,
so a consumer that breaks out of the loop stops the *spawning* and not merely
the reporting -- and it is the one thing a "just use --workers 1" implementation
would silently fail. Most of this file exists to pin it down.

Nothing here spawns `claude`: the runners take any callable, so the work is a
counter and a barrier.
"""

from __future__ import annotations

import threading
import time

import pytest

import reading_room as rr


# --------------------------------------------------- I1-I5: resolving the mode


def test_i1_serial_is_the_default_when_no_flag_is_passed():
    mode = rr.resolve_run_mode()

    assert mode.serial is True
    assert mode.workers == 1
    assert "serial" in mode.label


def test_i2_parallel_is_opt_in_and_carries_its_width():
    mode = rr.resolve_run_mode(parallel=True, workers=4)

    assert mode.serial is False
    assert mode.workers == 4
    assert "--parallel" in mode.label


def test_i3_serial_ignores_workers_rather_than_arguing_with_it():
    """`--serial --workers 6` is one paper at a time, and says so."""
    mode = rr.resolve_run_mode(serial=True, workers=6)

    assert mode.serial is True
    assert mode.workers == 1


def test_i4_contradictory_flags_are_refused_not_ranked():
    with pytest.raises(rr.Refuse, match="contradict"):
        rr.resolve_run_mode(parallel=True, serial=True)


@pytest.mark.parametrize("workers", [0, -1])
def test_i5_parallel_with_a_nonsense_width_refuses(workers):
    with pytest.raises(rr.Refuse, match="not a number of papers"):
        rr.resolve_run_mode(parallel=True, workers=workers)


# ------------------------------------------------- I6-I10: the serial runner


def test_i6_serial_runner_yields_every_item_once_in_order():
    items = ["a", "b", "c"]
    seen = []

    for item, call in rr.serial_runner(items, lambda i: i.upper()):
        seen.append((item, call()))

    assert seen == [("a", "A"), ("b", "B"), ("c", "C")]


def test_i7_serial_runner_starts_nothing_until_the_consumer_asks():
    """The pair is yielded *before* the work runs, so nothing is pre-spent."""
    started = []

    runner = rr.serial_runner(["a", "b"], started.append)
    item, call = next(runner)

    assert item == "a"
    assert started == []          # yielded, not yet run
    call()
    assert started == ["a"]


def test_i8_breaking_out_of_a_serial_round_stops_the_spend():
    """The stop-on-sealing-breach case, reduced to its mechanism.

    A consumer that gives up on paper 2 of 50 must leave papers 3-50 unspawned.
    A `--workers 1` pool would have submitted them already.
    """
    spawned = []

    for i, (item, call) in enumerate(rr.serial_runner(range(50), spawned.append), 1):
        call()
        if i == 2:
            break

    assert spawned == [0, 1]


def test_i9_serial_runner_never_runs_two_papers_at_once():
    live, peak = 0, 0
    lock = threading.Lock()

    def work(item):
        nonlocal live, peak
        with lock:
            live += 1
            peak = max(peak, live)
        time.sleep(0.01)
        with lock:
            live -= 1
        return item

    for _, call in rr.serial_runner(range(6), work):
        call()

    assert peak == 1


def test_i10_serial_runner_raises_from_the_call_not_from_the_iteration():
    """The script's `try: call()` / `except rr.Refuse` handler depends on this.

    If the exception escaped the generator instead, one refused paper would end
    the round rather than being logged and skipped.
    """
    def work(item):
        raise rr.Refuse(f"no cached text for {item}")

    runner = rr.serial_runner(["a", "b"], work)
    item, call = next(runner)                       # iterating is fine
    with pytest.raises(rr.Refuse, match="no cached text for a"):
        call()
    assert next(runner)[0] == "b"                   # and the round continues


# ----------------------------------------------- I11-I13: the parallel runner


def test_i11_parallel_runner_yields_every_item_exactly_once():
    items = list(range(12))

    seen = {item: call() for item, call in
            rr.parallel_runner(items, lambda i: i * 2, workers=4)}

    assert seen == {i: i * 2 for i in items}


def test_i12_parallel_runner_really_overlaps():
    """Otherwise `--parallel` is a lie and I9's assertion proves nothing."""
    barrier = threading.Barrier(3, timeout=5)

    def work(item):
        barrier.wait()            # only returns if three threads arrive together
        return item

    seen = [item for item, call in
            rr.parallel_runner(range(3), work, workers=3)]

    assert sorted(seen) == [0, 1, 2]


def test_i13_parallel_runner_submits_up_front_so_stopping_saves_nothing():
    """The trade `resolve_run_mode` exists to make explicit, asserted.

    Breaking out of a pooled round stops the reading, not the spending -- which
    is exactly why serial is the default and why the breach-stop is serial-only.
    """
    spawned = []
    lock = threading.Lock()

    def work(item):
        with lock:
            spawned.append(item)
        return item

    for i, (_, call) in enumerate(
            rr.parallel_runner(range(20), work, workers=4), 1):
        call()
        if i == 1:
            break

    # The pool shuts down on the generator's `with` block, which drains what was
    # already submitted. The count is timing-dependent; that far more than one
    # paper was spawned is not.
    assert len(spawned) > 1


# ---------------------------------------------------------- I14: the dispatch


def test_i14_runner_for_dispatches_on_the_mode():
    """One place chooses; the two modes are told apart by when work starts."""
    serial_started = []
    serial = rr.runner_for(rr.RunMode(serial=True, workers=1),
                           range(4), serial_started.append)
    next(serial)
    assert serial_started == []        # lazy: nothing spawned before it is asked
    serial.close()

    pooled_started = []
    pooled = rr.runner_for(rr.RunMode(serial=False, workers=4),
                           range(4), pooled_started.append)
    list(pooled)
    assert sorted(pooled_started) == [0, 1, 2, 3]


# ------------------------------------- I15-I18: the running token counter


def test_i15_billed_total_tokens_counts_everything_in_and_out():
    """All three input fields plus output. A cold call bills cache_creation."""
    usage = {"input_tokens": 4, "cache_creation_input_tokens": 15_000,
             "cache_read_input_tokens": 0, "output_tokens": 400}

    assert rr.billed_total_tokens(usage) == 15_404


def test_i16_billed_total_tokens_is_none_when_the_stream_reported_nothing():
    """G7. Unknown is not zero -- a counter that treats it as free says 'go on'."""
    assert rr.billed_total_tokens({}) is None
    assert rr.billed_total_tokens({"service_tier": "standard"}) is None


def test_i17_billed_total_tokens_sums_the_fields_that_are_present():
    assert rr.billed_total_tokens({"output_tokens": 96}) == 96
    assert rr.billed_total_tokens({"input_tokens": 12_000}) == 12_000


@pytest.mark.parametrize("count,text", [
    (0, "0"), (999, "999"), (1_000, "1k"), (184_312, "184k"),
    (770_000, "770k"), (5_200_000, "5.20M"),
])
def test_i18_token_counts_are_formatted_for_a_human_mid_round(count, text):
    assert rr.format_tokens(count) == text


def test_i19_the_counter_reads_a_real_stream_end_to_end(fake_claude, clean_room):
    """From the stdout the harness actually captures, not a hand-made dict."""
    attempt = rr.run_paper("BEGIN PAPER deadbeefdeadbeef\nMethods.",
                           room=clean_room, token="deadbeefdeadbeef",
                           paper_id="TEST0001", claude=str(fake_claude.path))

    spent = rr.billed_total_tokens(rr.stream_usage(attempt.stdout))

    # The fake's defaults are copied from a real CLI 2.1.197 stream: 4 input,
    # 179 cache_creation, 0 cache_read, 96 output.
    assert spent == 279

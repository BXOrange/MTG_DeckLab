"""ANA-6: the bounded, fair job queue behind the dynamic analysis.

Deterministic: no worker threads (`start_threads=False`, `run_next()` drives a
slot by hand) and an injected clock, except the few thread tests that gate on
`threading.Event`s rather than sleeping.
"""

from __future__ import annotations

import threading

import pytest

from mtg_analyzer.services.job_runner import (
    REFUSAL_OWNER_LIMIT,
    REFUSAL_QUEUE_FULL,
    STATE_CANCELLED,
    STATE_DONE,
    STATE_FAILED,
    STATE_QUEUED,
    STATE_RUNNING,
    JobCancelled,
    JobRunner,
    QueueRefused,
)

EVENT_TIMEOUT = 5.0


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make_runner(*, queue_max=10, per_owner_max=10, results=3, ttl=100.0, clock=None, threads=False, workers=1):
    return JobRunner(
        workers,
        queue_max=queue_max,
        per_owner_max=per_owner_max,
        results_per_owner=results,
        result_ttl_seconds=ttl,
        clock=clock or Clock(),
        start_threads=threads,
    )


def ok(tag):
    return lambda ctx: {"tag": tag}


def run_all(runner):
    order = []
    while (job := runner.run_next()) is not None:
        order.append(job)
    return order


def test_round_robin_across_owners():
    runner = make_runner()
    a = [runner.submit("a", ok(f"a{i}")) for i in range(3)]
    b = [runner.submit("b", ok(f"b{i}")) for i in range(2)]
    c = runner.submit("c", ok("c0"))
    ran = [j.result["tag"] for j in run_all(runner)]
    assert ran == ["a0", "b0", "c0", "a1", "b1", "a2"]
    assert all(j.status == STATE_DONE for j in a + b + [c])


def test_a_late_owner_is_not_starved_by_a_backlog():
    runner = make_runner()
    for i in range(4):
        runner.submit("flood", ok(f"f{i}"))
    runner.run_next()  # f0 done
    runner.submit("late", ok("late"))
    # The late owner waits at most one more flood job, not behind the whole backlog.
    assert [j.result["tag"] for j in run_all(runner)][:2] == ["f1", "late"]


def test_queue_position_follows_the_fair_order_and_updates():
    runner = make_runner()
    a0, a1 = runner.submit("a", ok(0)), runner.submit("a", ok(1))
    b0 = runner.submit("b", ok(2))
    assert [runner.view(j)["queuePosition"] for j in (a0, b0, a1)] == [1, 2, 3]
    assert runner.view(a0)["queueLength"] == 3
    runner.run_next()
    assert runner.view(a0)["queuePosition"] is None and runner.view(a0)["status"] == STATE_DONE
    assert [runner.view(j)["queuePosition"] for j in (b0, a1)] == [1, 2]


def test_progress_is_reported_while_running():
    runner = make_runner()
    seen = []

    def run(ctx):
        ctx.report(2, 5)
        seen.append(runner.view(job))
        return {}

    job = runner.submit("a", run, total=5)
    runner.run_next()
    assert seen[0]["status"] == STATE_RUNNING and seen[0]["completed"] == 2 and seen[0]["total"] == 5
    assert seen[0]["queuePosition"] is None


def test_full_queue_is_refused_not_evicted():
    runner = make_runner(queue_max=2)
    first = runner.submit("a", ok(0))
    second = runner.submit("b", ok(1))
    with pytest.raises(QueueRefused) as refused:
        runner.submit("c", ok(2))
    assert refused.value.code == REFUSAL_QUEUE_FULL
    assert first.status == second.status == STATE_QUEUED
    assert runner.get(first.id) is first and runner.get(second.id) is second
    runner.run_next()  # a slot frees up: admission works again
    runner.submit("c", ok(2))


def test_per_owner_limit_counts_queued_and_running_and_spares_others():
    runner = make_runner(per_owner_max=2)
    runner.submit("a", ok(0))
    runner.submit("a", ok(1))
    with pytest.raises(QueueRefused) as refused:
        runner.submit("a", ok(2))
    assert refused.value.code == REFUSAL_OWNER_LIMIT
    runner.submit("b", ok(3))  # another owner is unaffected
    runner.run_next()  # a0 finished -> a has room again
    runner.submit("a", ok(4))


def test_running_job_counts_against_the_owner_limit():
    runner = make_runner(per_owner_max=1)
    started, release = threading.Event(), threading.Event()

    def block(ctx):
        started.set()
        release.wait(EVENT_TIMEOUT)
        return {}

    runner.submit("a", block)
    thread = threading.Thread(target=runner.run_next)
    thread.start()
    assert started.wait(EVENT_TIMEOUT)
    with pytest.raises(QueueRefused):
        runner.submit("a", ok(1))
    release.set()
    thread.join(EVENT_TIMEOUT)
    runner.submit("a", ok(1))


def test_retention_is_per_owner_and_floods_never_evict():
    runner = make_runner(results=2, per_owner_max=50, queue_max=100)
    mine = runner.submit("me", ok("mine"))
    run_all(runner)
    for i in range(30):
        runner.submit("flood", ok(i))
    run_all(runner)
    assert runner.get(mine.id) is mine and mine.status == STATE_DONE
    flood_kept = [j for j in runner._store.jobs.values() if j.owner == "flood"]
    assert len(flood_kept) == 2  # the flooder only rolled off its own oldest
    assert sorted(j.result["tag"] for j in flood_kept) == [28, 29]


def test_own_new_result_rolls_the_oldest_own_result_off():
    runner = make_runner(results=2)
    jobs = [runner.submit("me", ok(i)) for i in range(3)]
    run_all(runner)
    assert runner.get(jobs[0].id) is None
    assert runner.get(jobs[1].id) is jobs[1] and runner.get(jobs[2].id) is jobs[2]


def test_ttl_sweep_purges_only_expired_results():
    clock = Clock()
    runner = make_runner(ttl=100.0, clock=clock)
    old = runner.submit("a", ok(0))
    run_all(runner)
    clock.now += 60
    fresh = runner.submit("b", ok(1))
    run_all(runner)
    clock.now += 50  # old is 110 s old, fresh 50 s
    assert runner.sweep() == 1
    assert runner.get(old.id) is None and runner.get(fresh.id) is fresh
    clock.now += 100
    assert runner.get(fresh.id) is None  # get purges lazily too


def test_queued_jobs_are_never_purged_by_ttl():
    clock = Clock()
    runner = make_runner(ttl=10.0, clock=clock)
    queued = runner.submit("a", ok(0))
    clock.now += 10_000
    assert runner.sweep() == 0 and runner.get(queued.id) is queued


def test_cancel_queued_job_frees_its_place_and_is_kept_as_cancelled():
    runner = make_runner()
    a0, b0, a1 = runner.submit("a", ok(0)), runner.submit("b", ok(1)), runner.submit("a", ok(2))
    assert runner.cancel(a0.id, "a") is a0 and a0.status == STATE_CANCELLED
    assert runner.view(a0)["queuePosition"] is None
    assert [runner.view(j)["queuePosition"] for j in (b0, a1)] == [2, 1]
    assert [j.result["tag"] for j in run_all(runner)] == [2, 1]
    assert a0.run is None


def test_cancel_running_job_stops_it_and_keeps_the_cancelled_state():
    runner = make_runner()
    started, release = threading.Event(), threading.Event()
    observed = []

    def run(ctx):
        started.set()
        release.wait(EVENT_TIMEOUT)
        observed.append(ctx.cancelled())
        ctx.check_cancelled()
        return {"never": True}

    job = runner.submit("a", run)
    thread = threading.Thread(target=runner.run_next)
    thread.start()
    assert started.wait(EVENT_TIMEOUT)
    assert job.status == STATE_RUNNING
    assert runner.cancel(job.id, "a") is job
    assert job.status == STATE_CANCELLED
    release.set()
    thread.join(EVENT_TIMEOUT)
    assert observed == [True]
    assert job.status == STATE_CANCELLED and job.result is None


def test_cancel_is_owner_only_and_a_finished_job_is_unchanged():
    runner = make_runner()
    job = runner.submit("a", ok(0))
    assert runner.cancel(job.id, "b") is None
    assert runner.cancel("missing", "a") is None
    assert job.status == STATE_QUEUED
    runner.run_next()
    assert runner.cancel(job.id, "a") is job and job.status == STATE_DONE


def test_failed_job_reports_failed_and_the_worker_survives():
    runner = make_runner()

    def boom(ctx):
        raise RuntimeError("kaputt")

    bad = runner.submit("a", boom)
    good = runner.submit("a", ok(1))
    run_all(runner)
    assert bad.status == STATE_FAILED and bad.error == "kaputt"
    assert good.status == STATE_DONE


def test_job_cancelled_raised_by_the_callable_ends_cancelled():
    runner = make_runner()

    def stop(ctx):
        raise JobCancelled()

    job = runner.submit("a", stop)
    runner.run_next()
    assert job.status == STATE_CANCELLED


def test_worker_threads_respect_the_slot_count_and_dispatch_fairly():
    runner = make_runner(threads=True, workers=1)
    started, release = threading.Event(), threading.Event()
    order = []

    def gate(ctx):
        started.set()
        release.wait(EVENT_TIMEOUT)
        return {}

    def tagged(tag):
        def run(ctx):
            order.append(tag)
            return {}
        return run

    first = runner.submit("a", gate)
    assert started.wait(EVENT_TIMEOUT)
    queued = [runner.submit("a", tagged("a1")), runner.submit("a", tagged("a2")), runner.submit("b", tagged("b1"))]
    assert [j.status for j in queued] == [STATE_QUEUED] * 3  # one slot, busy
    assert [runner.view(j)["queuePosition"] for j in queued] == [1, 3, 2]
    done = threading.Event()
    last = queued[1]
    release.set()
    for _ in range(int(EVENT_TIMEOUT * 100)):
        if last.status == STATE_DONE:
            break
        done.wait(0.01)
    assert first.status == STATE_DONE and order == ["a1", "b1", "a2"]
    runner.shutdown()


def test_shutdown_drops_queued_and_cancels_running():
    runner = make_runner(threads=True, workers=1)
    started = threading.Event()

    def spin(ctx):
        started.set()
        while not ctx.cancelled():
            threading.Event().wait(0.005)
        ctx.check_cancelled()

    running = runner.submit("a", spin)
    assert started.wait(EVENT_TIMEOUT)
    queued = runner.submit("b", ok(1))
    runner.shutdown()
    assert running.status == STATE_CANCELLED
    assert queued.status == STATE_CANCELLED and queued.error == "shutdown"
    assert all(not t.is_alive() for t in runner._threads)
    with pytest.raises(QueueRefused):
        runner.submit("a", ok(2))
    runner.shutdown()  # idempotent

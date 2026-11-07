from datetime import datetime, timedelta, timezone
import pytest
from cloudops.models import Resource, Sample, Quote
from cloudops.rules import assess, select_candidate, estimate, window, summarize

START, END = window(datetime(2026, 10, 31, 12, tzinfo=timezone.utc))


def resource(**kwargs):
    data = dict(
        id="i-test",
        name="test",
        environment="demo",
        region="cn-beijing",
        instance_type="ecs.g8a.4xlarge",
        family="ecs.g8a",
        cpu=16,
        memory_gb=64,
        status="Running",
        updated_at=END,
    )
    return Resource(**(data | kwargs))


def samples(cpu=3, memory=18, maximum=None, count=2016):
    return [
        Sample(
            timestamp=START + timedelta(seconds=300 * i),
            cpu=cpu,
            memory=memory,
            cpu_max=maximum or cpu,
            memory_max=memory,
        )
        for i in range(count)
    ]


def test_window_uses_complete_days():
    assert END.hour == 0 and END - START == timedelta(days=7)


def test_idle_and_half_capacity():
    r = resource()
    result = assess(r, samples(), START, END)
    assert result["diagnosis"] == "low_utilization"
    candidate = select_candidate(
        r,
        result,
        [{"id": "ecs.g8a.2xlarge", "family": "ecs.g8a", "cpu": 8, "memory_gb": 32}],
    )
    assert (
        candidate["projected_cpu_max"] == 6 and candidate["projected_memory_max"] == 36
    )


@pytest.mark.parametrize(
    "cpu,mem,peak,expected",
    [
        (10, 18, 10, "normal"),
        (3, 30, 3, "normal"),
        (3, 18, 40, "normal"),
        (3, 18, 80, "peak_risk"),
        (3, 85, 3, "peak_risk"),
    ],
)
def test_boundaries(cpu, mem, peak, expected):
    assert (
        assess(resource(), samples(cpu, mem, peak), START, END)["diagnosis"] == expected
    )


def test_low_average_high_peak_not_idle():
    points = samples()
    points[100].cpu_max = 95
    result = assess(resource(), points, START, END)
    assert (
        result["metrics"]["cpu"]["average"] == 3 and result["diagnosis"] == "peak_risk"
    )
    assert select_candidate(resource(), result, []) is None


def test_memory_missing_and_low_coverage():
    a = assess(resource(), samples(memory=None), START, END)
    assert (
        a["metrics"]["memory"]["average"] is None
        and a["diagnosis"] == "insufficient_data"
    )
    assert (
        assess(resource(), samples(count=1800), START, END)["diagnosis"]
        == "insufficient_data"
    )


def test_stopped_never_recommends():
    r = resource(status="Stopped")
    a = assess(r, samples(), START, END)
    assert a["diagnosis"] == "stopped" and select_candidate(r, a, []) is None


def test_invalid_times_and_ambiguous_duplicates():
    points = samples(count=2)
    points += [
        points[0],
        Sample(timestamp=END + timedelta(days=1), cpu=0),
        Sample(timestamp=START + timedelta(seconds=1), cpu=0),
    ]
    a = summarize(points, START, END)
    assert a["cpu"]["points"] == 1 and a["rejected_points"] == 3


@pytest.mark.parametrize(
    "kwargs", [{"family": "ecs.c7"}, {"cpu": 4}, {"memory_gb": 16}]
)
def test_candidate_must_be_exact_same_family_half(kwargs):
    r = resource()
    a = assess(r, samples(), START, END)
    spec = {"id": "target", "family": "ecs.g8a", "cpu": 8, "memory_gb": 32} | kwargs
    assert select_candidate(r, a, [spec]) is None


def test_projected_memory_peak_blocks_candidate():
    r = resource()
    p = samples()
    p[10].memory_max = 50
    a = assess(r, p, START, END)
    assert a["diagnosis"] == "low_utilization"
    assert (
        select_candidate(
            r, a, [{"id": "target", "family": "ecs.g8a", "cpu": 8, "memory_gb": 32}]
        )
        is None
    )


def quote(amount=4, **kw):
    return Quote(
        **(
            dict(
                amount=amount,
                currency="CNY",
                unit="Hour",
                region="cn-beijing",
                os="linux",
                source="test",
            )
            | kw
        )
    )


def test_price_difference_excludes_non_compute_items():
    a = estimate(resource(), quote(4), quote(2))
    assert a["monthly_equivalent_saving"] == 1460 and a["hours"] == 730


@pytest.mark.parametrize(
    "change",
    [
        {"currency": "USD"},
        {"unit": "Month"},
        {"region": "cn-hangzhou"},
        {"os": "windows"},
        {"amount": 5},
    ],
)
def test_incomparable_price_is_not_saving(change):
    assert estimate(resource(), quote(4), quote(**({"amount": 2} | change))) is None


@pytest.mark.parametrize("change", [{"billing": "PrePaid"}, {"spot": True}])
def test_non_regular_payg_not_estimated(change):
    assert estimate(resource(**change), quote(4), quote(2)) is None


def test_missing_peaks_are_not_averages():
    p = samples()
    for s in p:
        s.cpu_max = None
    r = assess(resource(), p, START, END)
    assert (
        r["diagnosis"] == "insufficient_data" and r["metrics"]["cpu"]["maximum"] is None
    )

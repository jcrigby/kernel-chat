"""Tests for src.ingest.extract — parsing logic only (no git repo needed)."""

from datetime import datetime, timezone
from src.ingest.extract import _build_record, _parse_numstat_line


def test_parse_numstat_normal():
    assert _parse_numstat_line("10\t5\tkernel/sched/core.c") == (10, 5, "kernel/sched/core.c")


def test_parse_numstat_binary():
    assert _parse_numstat_line("-\t-\tsome/binary.bin") == (0, 0, "some/binary.bin")


def test_parse_numstat_rename():
    result = _parse_numstat_line("3\t1\tarch/{x86 => arm64}/boot/Makefile")
    assert result is not None
    assert result[2] == "arch/{x86 => arm64}/boot/Makefile"


def test_parse_numstat_bad():
    assert _parse_numstat_line("garbage") is None


def test_build_record_basic():
    commit_lines = [
        "abc123def456",
        "2024-01-15T10:30:00+00:00",
        "2024-01-15T10:35:00+00:00",
        "Linus Torvalds",
        "torvalds@linux-foundation.org",
        "Linus Torvalds",
        "torvalds@linux-foundation.org",
        "parent1",
        "sched: Fix race in task migration",
        "This fixes a race condition in the scheduler",
        "that could cause a deadlock.",
    ]
    numstat_lines = [
        "10\t5\tkernel/sched/core.c",
        "2\t0\tkernel/sched/fair.c",
    ]
    record = _build_record(commit_lines, numstat_lines)
    assert record is not None
    assert record.hash == "abc123def456"
    assert record.subject == "sched: Fix race in task migration"
    assert record.body == "This fixes a race condition in the scheduler\nthat could cause a deadlock."
    assert record.merge is False
    assert record.files_changed == ["kernel/sched/core.c", "kernel/sched/fair.c"]
    assert record.insertions == 12
    assert record.deletions == 5


def test_build_record_merge():
    commit_lines = [
        "abc123",
        "2024-01-15T10:30:00+00:00",
        "2024-01-15T10:35:00+00:00",
        "Linus Torvalds",
        "torvalds@linux-foundation.org",
        "Linus Torvalds",
        "torvalds@linux-foundation.org",
        "parent1 parent2",
        "Merge branch 'fixes'",
    ]
    record = _build_record(commit_lines, [])
    assert record is not None
    assert record.merge is True
    assert record.body == ""


def test_build_record_too_short():
    assert _build_record(["only", "three", "lines"], []) is None

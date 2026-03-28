"""Tests for src.db.queries — query execution logic."""

import pytest
from src.db.queries import execute_raw_sql


def test_reject_non_select():
    with pytest.raises(ValueError, match="Only SELECT"):
        execute_raw_sql("DROP TABLE commits")


def test_reject_delete():
    with pytest.raises(ValueError, match="Only SELECT"):
        execute_raw_sql("DELETE FROM commits")


def test_reject_insert():
    with pytest.raises(ValueError, match="Only SELECT"):
        execute_raw_sql("INSERT INTO commits (hash) VALUES ('x')")

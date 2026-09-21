"""
tests/conftest.py
--------------------
Shared fixtures. Keeps individual test files focused on behavior, not
setup boilerplate.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timezone

import pytest

# The test suite is offline by contract (Task 83-R3B fail-closed networking).
# Force the HuggingFace / sentence-transformers stack to stay on its local
# cache so no code path under test can reach huggingface.co for an embedding
# model -- a single such attempt trips the session network guard. Set at
# import time, before any test module pulls in the model libraries.
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# Task 131 Final Remediation Directive 4: NO global/session-wide default
# for TALONX_V2_DURABLE_STORE_ENABLED here (removed -- a prior revision
# of this file set one). talonx_v2.service.V2Service's own runtime
# default is False; any test that needs the gated (ON) behavior sets it
# explicitly and locally (a module-scoped autouse fixture in that test
# file, via monkeypatch) so the mode a given test suite exercises is
# visible in that file itself, not hidden in a repo-wide default. See
# tests/test_task131_remediation_directive6.py for the dedicated,
# parameterized coverage of BOTH the OFF (default) and ON states.

from _network_guard import GuardInitializationError, NetworkGuard
from talonx_ingest.edgar.models import CompanyRef, FilingMetadata
from talonx_ingest.news.models import NewsArticle


def pytest_configure(config):
    """Install the opt-in fail-closed guard before test execution."""
    if os.environ.get("TALONX_TEST_NETWORK_GUARD") != "1":
        return
    guard = NetworkGuard(os.environ.get("TALONX_TEST_NETWORK_GUARD_REPORT"))
    try:
        guard.install()
    except GuardInitializationError as exc:
        raise pytest.UsageError(f"TalonX test network guard initialization failed: {exc}") from exc
    config._talonx_network_guard = guard


def pytest_unconfigure(config):
    guard = getattr(config, "_talonx_network_guard", None)
    if guard is not None:
        try:
            guard.assert_reconciled()
            guard.write_report()
        finally:
            guard.uninstall()


def pytest_addoption(parser):
    """Explicit opt-in destination for Task 83-R2 rehearsal evidence.

    The default is ``None``, so ordinary and partial test runs cannot write
    the committed matrix.
    """
    parser.addoption(
        "--task83-r2-matrix-output", action="store", default=None,
        help="temporary CSV destination for a complete scenarios 21-33 run",
    )
    parser.addoption(
        "--task83-r2-retained-matrix-output", action="store", default=None,
        help="temporary CSV destination for a complete retained scenarios 1-20 run",
    )


@pytest.fixture(scope="session")
def talonx_network_guard(request) -> NetworkGuard:
    guard = getattr(request.config, "_talonx_network_guard", None)
    if guard is None:
        # The fail-closed socket guard is opt-in (it must not be installed
        # during ordinary runs -- it would interfere with the real-localhost
        # Redis integration tests). When it is not enabled, the tests that
        # depend on it have no prerequisite, so SKIP with an explicit reason
        # rather than ERROR -- a missing opt-in dependency is a skip, not a
        # failure (Task 91 test-hygiene: keep the full-suite result
        # interpretable without tribal knowledge).
        pytest.skip(
            "network-isolation tests require TALONX_TEST_NETWORK_GUARD=1 "
            "(opt-in fail-closed socket guard); set it to run them",
            allow_module_level=False,
        )
    return guard


@pytest.fixture
def company() -> CompanyRef:
    return CompanyRef(ticker="AAPL", cik="0000320193", name="Apple Inc.")


@pytest.fixture
def filing(company: CompanyRef) -> FilingMetadata:
    return FilingMetadata(
        company=company,
        accession_number="0000320193-24-000123",
        form_type="10-K",
        filing_date=date(2024, 11, 1),
        report_date=date(2024, 9, 28),
        primary_document="aapl-20240928.htm",
    )


def make_filing(
    company: CompanyRef, accession_number: str, form_type: str = "10-K"
) -> FilingMetadata:
    """Non-fixture helper for tests that need several distinct filings."""
    return FilingMetadata(
        company=company,
        accession_number=accession_number,
        form_type=form_type,
        filing_date=date(2024, 1, 1),
        report_date=None,
        primary_document="doc.htm",
    )


@pytest.fixture
def news_article() -> NewsArticle:
    return NewsArticle(
        ticker="AAPL",
        title="Apple announces new product",
        url="https://example.com/articles/apple-new-product",
        source="rss:finance.yahoo.com",
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        summary="Apple today announced a new product that analysts expect to drive revenue.",
    )


def make_article(url: str, ticker: str = "AAPL") -> NewsArticle:
    """Non-fixture helper for tests that need several distinct articles."""
    return NewsArticle(
        ticker=ticker,
        title=f"Article at {url}",
        url=url,
        source="rss:test",
        published_at=datetime.now(timezone.utc),
        summary="Some article body text.",
    )


@pytest.fixture
def ledger_path(tmp_path):
    return tmp_path / "test_ledger.db"


# ---------------------------------------------------------------------------
# Pre-full-day cleanup: tests must NEVER touch the shared / release ops (Sentinel) outbox.
#
# Canary finding: tests calling `close._record_v2_reconciliation_blocks` etc. enqueued fixture RECONCILIATION_FAILURE rows
# (campaign "V2", episode "ep1", 12.5 shares ...) into the real repo-root `notifications.db` (the cwd-relative default), and
# the first real release start drained them to the real Sentinel channel.  Two layers, both automatic for every test:
#   1. TALONX_NOTIFY_DB_PATH points at a per-test temp file (every default-store consumer honours it);
#   2. constructing a NotifyStore on the shared/production/release outbox path raises, even if a test scrubbed the env var.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolate_ops_notification_store(tmp_path_factory, monkeypatch):
    from pathlib import Path

    from talonx_ops.notify import outbox

    repo = Path(__file__).resolve().parents[1]
    forbidden = {os.path.normcase(str(repo / n)) for n in ("notifications.db", "v2_release_rc1_notifications.db")}
    d = tmp_path_factory.mktemp("opsnotify")
    monkeypatch.setenv("TALONX_NOTIFY_DB_PATH", str(d / "notifications_test.db"))
    orig_init = outbox.NotifyStore.__init__

    def guarded(self, path="notifications.db", *a, **k):
        if os.path.normcase(os.path.abspath(str(path))) in forbidden:
            raise RuntimeError(f"tests must not open the shared/production ops outbox: {path!r}")
        orig_init(self, path, *a, **k)

    monkeypatch.setattr(outbox.NotifyStore, "__init__", guarded)

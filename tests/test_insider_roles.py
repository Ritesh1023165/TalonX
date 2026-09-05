"""
tests/test_insider_roles.py
---------------------------
Task 96D -- insider-role normalisation. No role inferred beyond the SEC
relationship flags.
"""
from __future__ import annotations

import pytest

from talonx_ingest.intelligence.insider.domain import InsiderRole
from talonx_ingest.intelligence.insider.roles import normalize_role


def _r(**kw):
    base = dict(
        is_director=False, is_officer=False, is_ten_percent_owner=False,
        is_other=False, officer_title=None,
    )
    base.update(kw)
    return normalize_role(**base)


@pytest.mark.parametrize(
    "title,role",
    [
        ("Chief Executive Officer", InsiderRole.CEO),
        ("CEO", InsiderRole.CEO),
        ("President and Chief Executive Officer", InsiderRole.CEO),
        ("Senior Vice President, CFO", InsiderRole.CFO),
        ("Chief Financial Officer", InsiderRole.CFO),
        ("Chief Operating Officer", InsiderRole.COO),
        ("Chief Accounting Officer", InsiderRole.CHIEF_ACCOUNTING_OFFICER),
        ("General Counsel", InsiderRole.GENERAL_COUNSEL),
        ("President", InsiderRole.PRESIDENT),
    ],
)
def test_officer_title_maps_to_role(title, role):
    res = _r(is_officer=True, officer_title=title)
    assert res.primary_role is role
    assert res.raw_title == title


def test_officer_with_custom_title_is_officer_other():
    res = _r(is_officer=True, officer_title="SVP, Global Widget Strategy")
    assert res.primary_role is InsiderRole.OFFICER
    assert res.raw_title == "SVP, Global Widget Strategy"
    assert "role_unresolved" not in res.flags   # has a title, just unmatched


def test_officer_with_no_title_flags_unresolved():
    res = _r(is_officer=True, officer_title=None)
    assert res.primary_role is InsiderRole.OFFICER
    assert "role_unresolved" in res.flags


def test_director_only():
    res = _r(is_director=True)
    assert res.primary_role is InsiderRole.DIRECTOR
    assert res.roles == (InsiderRole.DIRECTOR,)


def test_ten_percent_owner():
    res = _r(is_ten_percent_owner=True)
    assert res.primary_role is InsiderRole.TEN_PERCENT_OWNER


def test_multi_role_precedence_cfo_and_director():
    res = _r(is_officer=True, is_director=True, officer_title="EVP and CFO")
    assert res.primary_role is InsiderRole.CFO
    assert set(res.roles) == {InsiderRole.CFO, InsiderRole.DIRECTOR}


def test_ceo_and_director_and_chair():
    res = _r(is_officer=True, is_director=True, officer_title="Chairman, President & CEO")
    assert res.primary_role is InsiderRole.CEO
    assert InsiderRole.DIRECTOR in res.roles


def test_no_flags_is_other_and_unresolved():
    res = _r()
    assert res.primary_role is InsiderRole.OTHER
    assert "role_unresolved" in res.flags


def test_is_other_flag():
    res = _r(is_other=True)
    assert res.primary_role is InsiderRole.OTHER

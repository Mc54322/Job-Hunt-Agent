"""Tests for the index expander."""

from __future__ import annotations

import pytest

from jobassist.index import KNOWN_INDICES, companies_for_index


def test_ftse100_returns_list() -> None:
    result = companies_for_index("ftse100")
    assert isinstance(result, list)
    assert len(result) > 0


def test_aim100_returns_list() -> None:
    result = companies_for_index("aim100")
    assert isinstance(result, list)
    assert len(result) > 0


def test_ftse100_contains_well_known_company() -> None:
    result = companies_for_index("ftse100")
    assert any("Shell" in c for c in result)


def test_aim100_contains_well_known_company() -> None:
    result = companies_for_index("aim100")
    assert any("YouGov" in c for c in result)


def test_case_insensitive_ftse100() -> None:
    lower = companies_for_index("ftse100")
    upper = companies_for_index("FTSE100")
    assert lower == upper


def test_case_insensitive_aim100() -> None:
    lower = companies_for_index("aim100")
    upper = companies_for_index("AIM100")
    assert lower == upper


def test_unknown_index_raises_value_error() -> None:
    with pytest.raises(ValueError, match="Unknown index"):
        companies_for_index("ftse250")


def test_known_indices_is_frozenset() -> None:
    assert isinstance(KNOWN_INDICES, frozenset)


def test_known_indices_contains_expected_names() -> None:
    assert "ftse100" in KNOWN_INDICES
    assert "aim100" in KNOWN_INDICES


def test_returns_new_list_each_call() -> None:
    a = companies_for_index("ftse100")
    b = companies_for_index("ftse100")
    assert a is not b


def test_all_companies_are_strings() -> None:
    for index in KNOWN_INDICES:
        for company in companies_for_index(index):
            assert isinstance(company, str)


def test_no_empty_company_names() -> None:
    for index in KNOWN_INDICES:
        for company in companies_for_index(index):
            assert company.strip() != ""


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------


def test_cli_search_help_shows_index_option() -> None:
    from typer.testing import CliRunner

    from jobassist.cli import app

    result = CliRunner().invoke(app, ["search", "--help"])
    assert "--index" in result.output


def test_cli_index_invalid_exits_nonzero(tmp_path: "Path") -> None:  # noqa: F821

    from typer.testing import CliRunner

    from jobassist.cli import app

    resume = tmp_path / "resume.txt"
    resume.write_text("My resume")
    result = CliRunner().invoke(
        app,
        ["search", "Engineer", "full-time", "--resume", str(resume), "--index", "ftse250"],
    )
    assert result.exit_code != 0


def test_cli_index_valid_does_not_show_unknown_error(tmp_path: "Path") -> None:  # noqa: F821
    """A valid --index name must not produce an 'Unknown index' error."""

    from typer.testing import CliRunner

    from jobassist.cli import app

    resume = tmp_path / "resume.txt"
    resume.write_text("My resume")

    result = CliRunner().invoke(
        app,
        ["search", "Engineer", "full-time", "--resume", str(resume), "--index", "ftse100"],
    )
    assert "Unknown index" not in result.output

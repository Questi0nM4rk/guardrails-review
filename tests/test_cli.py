"""Tests for the CLI entry point."""

from __future__ import annotations

import json

from guardrails_review.cli import main
from guardrails_review.types import ReviewComment, ReviewResult


def test_no_command_prints_help(capsys):
    """No subcommand prints help and returns 1."""
    result = main([])

    assert result == 1
    captured = capsys.readouterr()
    assert "usage" in captured.out.lower() or "guardrails-review" in captured.out


def test_review_subcommand(monkeypatch):
    """Review subcommand delegates to run_review."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.run_review",
        lambda pr, dry_run=False: calls.append((pr, dry_run)) or 0,
    )

    result = main(["review", "--pr", "53"])

    assert result == 0
    assert calls == [(53, False)]


def test_review_dry_run(monkeypatch):
    """Review --dry-run passes dry_run=True."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.run_review",
        lambda pr, dry_run=False: calls.append((pr, dry_run)) or 0,
    )

    main(["review", "--pr", "10", "--dry-run"])

    assert calls == [(10, True)]


def test_comments_subcommand_json(monkeypatch, capsys):
    """Comments --json outputs JSON array."""
    review = ReviewResult(
        verdict="approve",
        summary="LGTM",
        comments=[ReviewComment(path="f.py", line=1, body="ok", severity="error")],
        model="m",
        timestamp="t",
        pr=5,
    )
    monkeypatch.setattr("guardrails_review.cli.load_all_reviews", lambda pr: [review])

    result = main(["comments", "--pr", "5", "--json"])

    assert result == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert len(data) == 1
    assert data[0]["verdict"] == "approve"


def test_comments_subcommand_text(monkeypatch, capsys):
    """Comments without --json outputs text summary."""
    review = ReviewResult(
        verdict="approve",
        summary="LGTM",
        comments=[ReviewComment(path="f.py", line=1, body="nice", severity="error")],
        model="m",
        timestamp="t",
        pr=5,
    )
    monkeypatch.setattr("guardrails_review.cli.load_latest_review", lambda pr: review)

    result = main(["comments", "--pr", "5"])

    assert result == 0
    captured = capsys.readouterr()
    assert "approve" in captured.out
    assert "f.py:1" in captured.out


def test_comments_empty_summary(monkeypatch, capsys):
    """Comments with empty summary does not crash (IndexError guard)."""
    review = ReviewResult(
        verdict="approve",
        summary="",
        comments=[],
        model="m",
        timestamp="t",
        pr=5,
    )
    monkeypatch.setattr("guardrails_review.cli.load_latest_review", lambda pr: review)

    result = main(["comments", "--pr", "5"])

    assert result == 0
    captured = capsys.readouterr()
    assert "approve" in captured.out


def test_comments_no_cache(monkeypatch, capsys):
    """Comments with no cached reviews returns 1."""
    monkeypatch.setattr("guardrails_review.cli.load_latest_review", lambda pr: None)

    result = main(["comments", "--pr", "99"])

    assert result == 1
    captured = capsys.readouterr()
    assert "No cached reviews" in captured.out


def test_approve_subcommand(monkeypatch, capsys):
    """Approve subcommand calls approve_pr."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.approve_pr",
        lambda pr, body: calls.append(("approve", pr, body)) or True,
    )

    result = main(["approve", "--pr", "7"])

    assert result == 0
    assert calls[0][0] == "approve"
    assert calls[0][1] == 7


def test_approve_request_changes(monkeypatch, capsys):
    """Approve --request-changes calls request_changes."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.request_changes",
        lambda pr, body: calls.append(("rc", pr, body)) or True,
    )

    result = main(["approve", "--pr", "7", "--request-changes", "Fix X"])

    assert result == 0
    assert calls[0] == ("rc", 7, "Fix X")


def test_approve_dry_run(monkeypatch, capsys):
    """Approve --dry-run prints what would happen without calling API."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.approve_pr",
        lambda pr, body: calls.append(("approve", pr, body)) or True,
    )

    result = main(["approve", "--pr", "7", "--dry-run"])

    assert result == 0
    assert len(calls) == 0
    captured = capsys.readouterr()
    assert "Would approve" in captured.out
    assert "7" in captured.out


def test_approve_request_changes_dry_run(monkeypatch, capsys):
    """Approve --request-changes --dry-run prints without calling API."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.request_changes",
        lambda pr, body: calls.append(("rc", pr, body)) or True,
    )

    result = main(["approve", "--pr", "7", "--request-changes", "Fix X", "--dry-run"])

    assert result == 0
    assert len(calls) == 0
    captured = capsys.readouterr()
    assert "Would request changes" in captured.out
    assert "7" in captured.out


def test_resolve_subcommand(monkeypatch, capsys):
    """Resolve subcommand calls run_resolve."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.run_resolve",
        lambda pr, dry_run=False: calls.append((pr, dry_run)) or 0,
    )

    result = main(["resolve", "--pr", "42"])

    assert result == 0
    assert calls == [(42, False)]


def test_resolve_dry_run(monkeypatch, capsys):
    """Resolve --dry-run passes dry_run=True."""
    calls = []
    monkeypatch.setattr(
        "guardrails_review.cli.run_resolve",
        lambda pr, dry_run=False: calls.append((pr, dry_run)) or 0,
    )

    result = main(["resolve", "--pr", "42", "--dry-run"])

    assert result == 0
    assert calls == [(42, True)]


def test_context_subcommand(monkeypatch, capsys):
    """Context subcommand outputs JSON to stdout."""
    monkeypatch.setattr(
        "guardrails_review.cli.build_agent_context",
        lambda pr, max_comments=20: {"pr": pr, "unresolved": [], "total_unresolved": 0},
    )

    result = main(["context", "--pr", "42"])

    assert result == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["pr"] == 42


def test_context_max_comments(monkeypatch, capsys):
    """Context --max-comments passes value through."""
    captured_kwargs = {}

    def fake_build(pr, max_comments=20):
        captured_kwargs["max_comments"] = max_comments
        return {"pr": pr}

    monkeypatch.setattr("guardrails_review.cli.build_agent_context", fake_build)

    main(["context", "--pr", "42", "--max-comments", "5"])

    assert captured_kwargs["max_comments"] == 5

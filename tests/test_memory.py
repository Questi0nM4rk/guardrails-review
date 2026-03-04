"""Tests for per-repo memory via dedicated branch storage."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import asdict
from unittest.mock import MagicMock, patch

from guardrails_review.memory import (
    FALSE_POSITIVE_LIMIT,
    MEMORY_BRANCH,
    MEMORY_FILENAME,
    FalsePositive,
    Memory,
    ResolutionStats,
    _prune_memory,
    build_memory_context,
    load_memory,
    save_memory,
    update_from_review,
)
from guardrails_review.types import ReviewResult, ReviewThread

_MEMORY_MOD = "guardrails_review.memory"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_memory(
    owner: str = "owner",
    repo: str = "repo",
) -> Memory:
    return Memory(
        version=1,
        repo=f"{owner}/{repo}",
        false_positives=[],
        conventions=[],
        resolution_stats=ResolutionStats(
            total_threads=0,
            fixed=0,
            false_positive=0,
            wont_fix=0,
            avg_rounds_to_resolve=0.0,
        ),
    )


def _make_fp(
    pattern: str = "urllib use",
    rule: str = "S605",
    last_seen: str = "2026-03-01",
    occurrences: int = 1,
) -> FalsePositive:
    return FalsePositive(
        pattern=pattern,
        rule=rule,
        file_pattern="src/**/*.py",
        occurrences=occurrences,
        first_seen="2026-01-01",
        last_seen=last_seen,
    )


def _make_thread(
    thread_id: str = "PRRT_1",
    *,
    is_resolved: bool = False,
) -> ReviewThread:
    return ReviewThread(
        thread_id=thread_id,
        path="src/foo.py",
        line=10,
        body="<!-- guardrails-review -->\nSQL injection",
        is_resolved=is_resolved,
        is_outdated=False,
        author="guardrails-review[bot]",
        created_at="2026-03-01T00:00:00Z",
    )


def _make_result(verdict: str = "request_changes", pr: int = 1) -> ReviewResult:
    return ReviewResult(
        verdict=verdict,
        summary="Found issues",
        comments=[],
        model="test/model",
        pr=pr,
    )


def _make_proc(stdout: str = "", returncode: int = 0):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = returncode
    proc.stderr = ""
    return proc


def _encode_b64(content: str) -> str:
    """Base64-encode content as GitHub API returns it."""
    return base64.b64encode(content.encode()).decode()


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_memory_branch_name() -> None:
    """Memory branch has expected name."""
    assert MEMORY_BRANCH == "guardrails-memory"


def test_memory_filename() -> None:
    """Memory filename is memory.json."""
    assert MEMORY_FILENAME == "memory.json"


def test_false_positive_limit() -> None:
    """False positive cap is 50."""
    assert FALSE_POSITIVE_LIMIT == 50


# ---------------------------------------------------------------------------
# Memory dataclass
# ---------------------------------------------------------------------------


def test_memory_defaults() -> None:
    """Memory has expected default structure."""
    mem = _make_memory()
    assert mem.version == 1
    assert mem.repo == "owner/repo"
    assert mem.false_positives == []
    assert mem.conventions == []
    assert mem.resolution_stats.total_threads == 0


def test_memory_has_no_gist_id_field() -> None:
    """Memory no longer has a gist_id field."""
    mem = _make_memory()
    assert not hasattr(mem, "gist_id")


def test_memory_round_trip() -> None:
    """Memory serializes to JSON and back without data loss."""
    mem = Memory(
        version=1,
        repo="o/r",
        false_positives=[_make_fp()],
        conventions=["Uses gh CLI"],
        resolution_stats=ResolutionStats(
            total_threads=5, fixed=3, false_positive=1, wont_fix=1,
            avg_rounds_to_resolve=1.5,
        ),
    )
    raw = json.dumps(asdict(mem))
    data = json.loads(raw)
    assert data["version"] == 1
    assert data["false_positives"][0]["rule"] == "S605"
    assert data["resolution_stats"]["total_threads"] == 5


# ---------------------------------------------------------------------------
# _prune_memory
# ---------------------------------------------------------------------------


def test_prune_memory_noop_when_under_limit() -> None:
    """_prune_memory does nothing when false_positives is under the cap."""
    mem = _make_memory()
    fps = [_make_fp(pattern=f"p{i}", last_seen=f"2026-01-{i+1:02d}") for i in range(10)]
    mem_with_fps = Memory(
        version=mem.version, repo=mem.repo,
        false_positives=fps, conventions=[], resolution_stats=mem.resolution_stats,
    )
    pruned = _prune_memory(mem_with_fps)
    assert len(pruned.false_positives) == 10


def test_prune_memory_keeps_most_recent_by_last_seen() -> None:
    """_prune_memory evicts oldest false positives by last_seen when over cap."""
    fps = [_make_fp(pattern=f"p{i}", last_seen=f"2026-01-{i+1:02d}") for i in range(60)]
    mem = Memory(
        version=1, repo="o/r",
        false_positives=fps, conventions=[], resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0,
            avg_rounds_to_resolve=0.0,
        ),
    )
    pruned = _prune_memory(mem)
    assert len(pruned.false_positives) == FALSE_POSITIVE_LIMIT
    # Should keep the most recent (highest last_seen dates)
    kept_patterns = {fp.pattern for fp in pruned.false_positives}
    assert "p59" in kept_patterns  # most recent
    assert "p0" not in kept_patterns  # oldest, evicted


def test_prune_memory_returns_new_instance() -> None:
    """_prune_memory returns a new Memory object."""
    mem = _make_memory()
    pruned = _prune_memory(mem)
    assert pruned is not mem


# ---------------------------------------------------------------------------
# load_memory — branch backend
# ---------------------------------------------------------------------------


def test_load_memory_reads_from_branch() -> None:
    """load_memory reads memory.json from guardrails-memory branch via gh api."""
    mem = _make_memory(owner="myorg", repo="myrepo")
    content_b64 = _encode_b64(json.dumps(asdict(mem)))
    api_response = json.dumps({"content": content_b64 + "\n", "sha": "abc123"})

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.return_value = _make_proc(api_response)
        result = load_memory("myorg", "myrepo")

    assert result.repo == "myorg/myrepo"
    assert result.false_positives == []
    # Verify it called the right API endpoint
    call_args = mock_gh.call_args
    assert "guardrails-memory" in " ".join(call_args.args)


def test_load_memory_returns_empty_on_404() -> None:
    """load_memory returns empty Memory when branch/file doesn't exist yet."""
    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = RuntimeError("HTTP 404: Not Found")
        result = load_memory("owner", "repo")

    assert result.repo == "owner/repo"
    assert result.false_positives == []


def test_load_memory_returns_empty_on_any_failure() -> None:
    """load_memory returns empty Memory on any gh api failure."""
    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = RuntimeError("network error")
        result = load_memory("owner", "repo")

    assert result.repo == "owner/repo"


def test_load_memory_handles_corrupt_json() -> None:
    """load_memory returns empty Memory if stored JSON is corrupt."""
    corrupt_b64 = _encode_b64("not valid json {{{")
    api_response = json.dumps({"content": corrupt_b64, "sha": "abc123"})

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.return_value = _make_proc(api_response)
        result = load_memory("owner", "repo")

    assert result.repo == "owner/repo"
    assert result.false_positives == []


# ---------------------------------------------------------------------------
# save_memory — branch backend
# ---------------------------------------------------------------------------


def test_save_memory_creates_branch_on_first_run() -> None:
    """save_memory creates the guardrails-memory branch if it doesn't exist."""
    mem = _make_memory()

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        # Calls:
        # 1. _get_file_sha → 404 (branch/file not found)
        # 2. _create_orphan_branch: GET default branch name
        # 3. _create_orphan_branch: GET default branch SHA
        # 4. _create_orphan_branch: POST create ref
        # 5. _put_file: PUT file
        mock_gh.side_effect = [
            RuntimeError("HTTP 404"),        # _get_file_sha
            _make_proc("main"),              # get default branch name
            _make_proc("abc123sha"),         # get default branch SHA
            _make_proc(""),                  # create ref
            _make_proc(""),                  # put file
        ]
        save_memory(mem)

    assert mock_gh.call_count == 5


def test_save_memory_updates_existing_file() -> None:
    """save_memory updates file on branch when it already exists (passes SHA)."""
    mem = _make_memory()
    existing_sha = "deadbeef1234"  # pragma: allowlist secret
    api_get_response = json.dumps({
        "content": _encode_b64(json.dumps(asdict(mem))),
        "sha": existing_sha,
    })

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = [
            _make_proc(api_get_response),  # get file + SHA
            _make_proc(""),                # put file
        ]
        save_memory(mem)

    # Second call should include the SHA for update
    put_call_args = mock_gh.call_args_list[1]
    put_input = put_call_args.kwargs.get("input_data", "")
    put_data = json.loads(put_input)
    assert put_data["sha"] == existing_sha


def test_save_memory_logs_warning_on_failure(caplog) -> None:
    """save_memory logs warning and does not raise if gh api fails."""
    mem = _make_memory()

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = RuntimeError("push failed")
        with caplog.at_level(logging.WARNING, logger="guardrails_review.memory"):
            save_memory(mem)

    assert any("Failed to save memory" in r.message for r in caplog.records)


def test_save_memory_prunes_before_saving() -> None:
    """save_memory prunes false positives before writing."""
    fps = [_make_fp(pattern=f"p{i}", last_seen=f"2026-01-{i+1:02d}") for i in range(60)]
    mem = Memory(
        version=1, repo="owner/repo",
        false_positives=fps, conventions=[],
        resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0,
            avg_rounds_to_resolve=0.0,
        ),
    )
    written_data: list[dict] = []

    def capture_put(*args, **kwargs):
        if "input_data" in kwargs:
            body = json.loads(kwargs["input_data"])
            # content is base64-encoded JSON
            content = base64.b64decode(body["content"]).decode()
            written_data.append(json.loads(content))
        return _make_proc("")

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = [
            RuntimeError("HTTP 404"),  # first call: get SHA (not found)
            _make_proc(""),            # create branch
            capture_put,               # put file — captured by side_effect list? No.
        ]
        # Use a custom approach: track all calls
        calls: list[dict] = []

        not_found = RuntimeError("HTTP 404")

        def fake_gh(*args, **kwargs):
            calls.append({"args": args, "kwargs": kwargs})
            if len(calls) == 1:
                raise not_found
            return _make_proc("")

        mock_gh.side_effect = fake_gh
        save_memory(mem)

    # Find the PUT call and check the content
    put_calls = [c for c in calls if "PUT" in c["args"]]
    assert len(put_calls) == 1
    payload = json.loads(put_calls[0]["kwargs"]["input_data"])
    content_json = json.loads(base64.b64decode(payload["content"]).decode())
    assert len(content_json["false_positives"]) == FALSE_POSITIVE_LIMIT


def test_save_memory_warns_when_large(caplog) -> None:
    """save_memory logs warning when serialized memory exceeds size threshold."""
    # Build a memory that will exceed MEMORY_SIZE_WARN_BYTES
    big_conv = ["x" * 200] * 600  # ~120KB worth
    mem = Memory(
        version=1, repo="owner/repo",
        false_positives=[], conventions=big_conv,
        resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0,
            avg_rounds_to_resolve=0.0,
        ),
    )

    with patch(f"{_MEMORY_MOD}.run_gh") as mock_gh:
        mock_gh.side_effect = [
            RuntimeError("HTTP 404"),   # _get_file_sha
            _make_proc("main"),         # get default branch
            _make_proc("abc123sha"),    # get default branch SHA
            _make_proc(""),             # create ref
            _make_proc(""),             # put file
        ]
        with caplog.at_level(logging.WARNING, logger="guardrails_review.memory"):
            save_memory(mem)

    assert any("memory size" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# update_from_review
# ---------------------------------------------------------------------------


def test_update_from_review_increments_stats_on_fix() -> None:
    """update_from_review increments fixed count when thread marked fixed."""
    mem = _make_memory()
    result = _make_result()
    thread = _make_thread(is_resolved=True)

    updated = update_from_review(mem, result, [thread])

    assert updated.resolution_stats.total_threads == 1
    assert updated.resolution_stats.fixed == 1


def test_update_from_review_ignores_unresolved_threads() -> None:
    """update_from_review does not count unresolved threads."""
    mem = _make_memory()
    result = _make_result()
    thread = _make_thread(is_resolved=False)

    updated = update_from_review(mem, result, [thread])

    assert updated.resolution_stats.total_threads == 0
    assert updated.resolution_stats.fixed == 0


def test_update_from_review_accumulates_stats() -> None:
    """update_from_review accumulates across multiple calls."""
    mem = _make_memory()
    result = _make_result()

    t1 = _make_thread("t1", is_resolved=True)
    t2 = _make_thread("t2", is_resolved=True)
    t3 = _make_thread("t3", is_resolved=False)

    updated = update_from_review(mem, result, [t1, t2, t3])

    assert updated.resolution_stats.total_threads == 2
    assert updated.resolution_stats.fixed == 2


def test_update_from_review_returns_new_instance() -> None:
    """update_from_review returns a new Memory object."""
    mem = _make_memory()
    updated = update_from_review(mem, _make_result(), [])
    assert updated is not mem


def test_update_from_review_no_double_counting() -> None:
    """update_from_review does not count the same thread twice across calls."""
    mem = _make_memory()
    result = _make_result()
    thread = _make_thread("t1", is_resolved=True)

    first = update_from_review(mem, result, [thread])
    assert first.resolution_stats.total_threads == 1

    # Second call with the same already-resolved thread — must not count again
    second = update_from_review(first, result, [thread])
    assert second.resolution_stats.total_threads == 1
    assert second.resolution_stats.fixed == 1
    assert "t1" in second.resolution_stats.resolved_thread_ids


# ---------------------------------------------------------------------------
# build_memory_context
# ---------------------------------------------------------------------------


def test_build_context_includes_false_positives() -> None:
    """build_memory_context includes false positive patterns."""
    mem = Memory(
        version=1, repo="o/r",
        false_positives=[_make_fp(pattern="urllib for API", rule="S605")],
        conventions=["Project uses gh CLI — S603/S607 expected"],
        resolution_stats=ResolutionStats(
            total_threads=0, fixed=0, false_positive=0, wont_fix=0,
            avg_rounds_to_resolve=0.0,
        ),
    )
    ctx = build_memory_context(mem)

    assert "urllib for API" in ctx
    assert "S605" in ctx
    assert "gh CLI" in ctx


def test_build_context_empty_when_no_data() -> None:
    """build_memory_context returns empty string when memory has no data."""
    mem = _make_memory()
    assert build_memory_context(mem) == ""

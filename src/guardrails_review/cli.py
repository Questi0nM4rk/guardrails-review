"""CLI entry point: review, comments, approve subcommands."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import sys

from guardrails_review.cache import load_all_reviews, load_latest_review
from guardrails_review.context import build_agent_context
from guardrails_review.github import approve_pr, request_changes
from guardrails_review.reviewer import run_resolve, run_review


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="guardrails-review",
        description="LLM-powered PR reviewer with auto-approve and inline comments",
    )
    sub = parser.add_subparsers(dest="command")

    # review
    review_p = sub.add_parser("review", help="Run LLM review on a PR")
    review_p.add_argument("--pr", type=int, required=True, help="PR number")
    review_p.add_argument(
        "--dry-run", action="store_true", help="Print review without posting"
    )

    # comments
    comments_p = sub.add_parser("comments", help="Query review findings")
    comments_p.add_argument("--pr", type=int, required=True, help="PR number")
    comments_p.add_argument(
        "--json", dest="as_json", action="store_true", help="Output as JSON"
    )

    # approve
    approve_p = sub.add_parser("approve", help="Approve or request changes on a PR")
    approve_p.add_argument("--pr", type=int, required=True, help="PR number")
    approve_p.add_argument(
        "--request-changes",
        dest="request_changes_msg",
        metavar="MSG",
        help="Request changes instead of approving",
    )
    approve_p.add_argument(
        "--dry-run", action="store_true", help="Print action without calling API"
    )

    # resolve
    resolve_p = sub.add_parser("resolve", help="Auto-resolve stale review threads")
    resolve_p.add_argument("--pr", type=int, required=True, help="PR number")
    resolve_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print resolvable threads without resolving",
    )

    # context
    context_p = sub.add_parser(
        "context", help="Agent context: structured JSON of review state"
    )
    context_p.add_argument("--pr", type=int, required=True, help="PR number")
    context_p.add_argument(
        "--max-comments",
        type=int,
        default=20,
        help="Max unresolved comments to show (default 20)",
    )

    return parser


def _cmd_review(args: argparse.Namespace) -> int:
    return run_review(args.pr, dry_run=args.dry_run)


def _cmd_comments(args: argparse.Namespace) -> int:
    if args.as_json:
        reviews = load_all_reviews(args.pr)
    else:
        latest = load_latest_review(args.pr)
        reviews = [latest] if latest else []

    if not reviews:
        print(f"No cached reviews for PR #{args.pr}")
        return 1

    if args.as_json:
        output = [asdict(r) for r in reviews]
        print(json.dumps(output, indent=2))
        return 0

    review = reviews[0]
    print(f"PR #{review.pr} — {review.verdict} (model: {review.model})")
    first_line = review.summary.splitlines()[0] if review.summary else "(no summary)"
    print(f"  {first_line}")

    if not review.comments:
        print("  No comments")
    else:
        for c in review.comments:
            print(f"  {c.path}:{c.line} — {c.body}")

    return 0


def _cmd_approve(args: argparse.Namespace) -> int:
    if args.dry_run:
        if args.request_changes_msg:
            print(f"Would request changes on PR #{args.pr}: {args.request_changes_msg}")
        else:
            print(f"Would approve PR #{args.pr}")
        return 0

    if args.request_changes_msg:
        request_changes(args.pr, args.request_changes_msg)
        print(f"Requested changes on PR #{args.pr}")
    else:
        approve_pr(args.pr, "Approved via guardrails-review.")
        print(f"Approved PR #{args.pr}")
    return 0


def _cmd_resolve(args: argparse.Namespace) -> int:
    return run_resolve(args.pr, dry_run=args.dry_run)


def _cmd_context(args: argparse.Namespace) -> int:
    context = build_agent_context(args.pr, max_comments=args.max_comments)
    print(json.dumps(context, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 1

    handlers = {
        "review": _cmd_review,
        "comments": _cmd_comments,
        "approve": _cmd_approve,
        "resolve": _cmd_resolve,
        "context": _cmd_context,
    }
    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main())

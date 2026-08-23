#!/usr/bin/env python3
"""Create a local .env with generated secrets.

TRACE ships no default credentials. This script fills .env.example with
randomly generated local values so `docker compose up` works out of the box
without a well-known password ever existing (docs/SECURITY.md §2).
"""

from __future__ import annotations

import argparse
import json
import pathlib
import secrets
import sys

GENERATED = {
    "TRACE_MINIO_ACCESS_KEY": lambda: f"trace-{secrets.token_hex(6)}",
    "TRACE_MINIO_SECRET_KEY": lambda: secrets.token_urlsafe(32),
    "TRACE_CLICKHOUSE_PASSWORD": lambda: secrets.token_urlsafe(24),
    "TRACE_GRAFANA_PASSWORD": lambda: secrets.token_urlsafe(16),
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".", help="Repository root")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing .env")
    args = parser.parse_args()

    root = pathlib.Path(args.root).resolve()
    example = root / ".env.example"
    target = root / ".env"

    if target.exists() and not args.force:
        print(f"{target} already exists — leaving it alone (use --force to regenerate).")
        return 0
    if not example.is_file():
        print(f"Missing {example}", file=sys.stderr)
        return 1

    api_token = secrets.token_urlsafe(32)
    tokens = {
        api_token: {
            "subject": "analyst@example.com",
            "roles": ["ADMIN"],
            "tenant": "default",
        }
    }

    lines: list[str] = []
    for line in example.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0] if "=" in line else ""
        if key == "TRACE_API_TOKENS":
            line = "TRACE_API_TOKENS=" + json.dumps(tokens, separators=(",", ":"))
        elif key in GENERATED and line.endswith("="):
            line = f"{key}={GENERATED[key]()}"
        lines.append(line)

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    target.chmod(0o600)

    print(f"Wrote {target} (mode 600).\n")
    print("Your TRACE API token — paste it into the UI token field (top right):\n")
    print(f"    {api_token}\n")
    print("It is stored only in .env, which is git-ignored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

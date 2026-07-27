#!/usr/bin/env python3
"""Fail the build if pipeline internals leak into this public repository.

The pipeline lives in a private package. This repo is allowed to call it and show its
results, but must never carry its threshold names, per-frame metric names, or internal
reason and phase vocabulary.

The banned terms are stored as truncated SHA-256 digests rather than plaintext. Listing
them literally would defeat the purpose: the checker would become the leak.

    python3 scripts/check_public_surface.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

SKIP_DIRS = {".git", "node_modules", "dist", ".astro", ".venv", "venv", "__pycache__", ".vercel"}
SKIP_EXT = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".mp4", ".mov", ".woff", ".woff2"}
SELF = Path(__file__).name

BANNED_DIGESTS = {
    "918326a3737a7dbf", "d57c5608974a4508", "2defd58d50591d39", "f179c76fd050b898",
    "b78509f9e8a5b04a", "9c2ee2d1ec02b51d", "12e3f43571525344", "b3a823b5652f40d8",
    "8439539051f21c13", "e9fbc3124b9cf669", "1f1c760deab437db", "e246935015b9cd03",
    "82b31913165b5a76", "cb96b9b33c4b0579", "0ec085c2e79ac38e", "b5cf9c6723f88f50",
    "5cc262d53e1400c3", "3932f32b34185140", "d9715942e0df8510", "fca6da8b4b760366",
    "66b6a4a535964e60", "ddddf82bf39a72b2", "ea08ff6438b0267e", "b83c16645445e99a",
    "fe6c7dff442535e2", "2b885fb9ecfb086b", "031bdc3d5246c406", "d2869eaa72dc5307",
    "64dc788b6ab1b5b3", "03cfb810ff502039", "7f4b17bfb525f6a5", "7b15314facc46711",
    "69bda487806f7391", "301887bca811f85a", "18830caa4d4ea7a5", "22fbaf234edffb11",
    "7bc064cf6c259e5a", "4ec8b80ee5dc164e", "053f93c86045fc08", "bd84a7a28151c750",
    "d5ee5b805124f051", "58997ebc3b0d905d", "4bd2caff52cb38fe", "dc7cb8b2079610cb",
    "2ff21ef904e27a95", "fa11c8bb16ce5c43",
}

TOKEN_RE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)*")

SECRET_RES = [
    (re.compile(r"gh[pousr]_[A-Za-z0-9]{16,}"), "GitHub token"),
    (re.compile(r"github_pat_[A-Za-z0-9_]{20,}"), "GitHub fine-grained token"),
    (re.compile(r"x-access-token:(?!\$)[A-Za-z0-9_\-]{8,}"), "inlined access token"),
    (re.compile(r"(?i)\bBEGIN (?:RSA |OPENSSH )?PRIVATE KEY\b"), "private key"),
]


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def candidates(token: str) -> set[str]:
    """The token itself plus every contiguous run of its underscore-separated parts.

    Catches a banned term embedded in a longer identifier, e.g. a wrapper variable that
    still names an internal threshold.
    """
    out = {token}
    parts = token.split("_")
    if len(parts) > 1:
        for start in range(len(parts)):
            for end in range(start + 1, len(parts) + 1):
                out.add("_".join(parts[start:end]))
    return out


def files_to_scan() -> list[Path]:
    found = []
    for path in REPO.rglob("*"):
        if not path.is_file() or path.suffix.lower() in SKIP_EXT:
            continue
        if path.name == SELF:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(REPO).parts):
            continue
        found.append(path)
    return found


def main() -> int:
    failures: list[str] = []
    scanned = 0

    for path in files_to_scan():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        scanned += 1
        rel = path.relative_to(REPO)

        seen: set[str] = set()
        for token in TOKEN_RE.findall(text.lower()):
            if len(token) < 4 or token in seen:
                continue
            seen.add(token)
            for candidate in candidates(token):
                if digest(candidate) in BANNED_DIGESTS:
                    failures.append(f"{rel}: internal term (sha256 {digest(candidate)})")

        for pattern, label in SECRET_RES:
            if pattern.search(text):
                failures.append(f"{rel}: possible {label} committed")

    if (REPO / "src" / "yotta_mcap").exists():
        failures.append("src/yotta_mcap: pipeline source must not be vendored here")

    gitignore = (REPO / ".gitignore").read_text(encoding="utf-8")
    for required in ("uploads/", "build/", "node_modules/"):
        if required not in gitignore:
            failures.append(f".gitignore: missing {required}")

    print(f"Scanned {scanned} files.")
    if failures:
        print(f"\n{len(failures)} problem(s) found:\n")
        for failure in sorted(set(failures)):
            print(f"  - {failure}")
        print("\nThese belong in the private pipeline package, not in the public repo.")
        return 1

    print("Public surface is clean: no internal vocabulary, no secrets, no vendored source.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

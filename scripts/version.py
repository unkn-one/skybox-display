#!/usr/bin/env python3
"""
scripts/version.py

Usage:
  version.py show [--debian]
  version.py debian
  version.py bump {major|minor|patch} [--dry-run]

Behavior:
- "show" prints the PEP 440 version derived from git tags (setuptools-scm).
- "debian" prints Debian-friendly version ('.dev' -> '~dev').
- "bump" computes next release from current version and tags 'vX.Y.Z'
  (or shows it with --dry-run).

Conventions:
- Git tags are "vX.Y.Z"
- pyproject.toml may define [project].dynamic = ["version"] with setuptools-scm.

Exit codes: 0 ok, 2 usage/config errors, 3 git errors
"""
import argparse
import os
import re
import subprocess
import sys
from typing import Tuple

PYPROJECT = os.environ.get("PYPROJECT_TOML", "pyproject.toml")

SEMVER_RE = re.compile(r"^(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)(?:\.dev(?P<dev>\d+))?$")

def run(cmd: list[str], **kw) -> str:
    try:
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, **kw).strip()
        return out
    except subprocess.CalledProcessError as e:
        print(f"[git] {' '.join(cmd)} failed:\n{e.output}", file=sys.stderr)
        sys.exit(3)

def have_git() -> bool:
    try:
        subprocess.check_output(["git", "--version"])
        return True
    except Exception:
        return False

def pep440_to_debian(v: str) -> str:
    # Map PEP 440 ".devN" to Debian "~devN"
    return v.replace(".dev", "~dev")

def get_version_from_pyproject_static() -> str | None:
    # Minimal reader: only to detect static [project].version
    try:
        import tomllib  # py311+
        with open(PYPROJECT, "rb") as f:
            data = tomllib.load(f)
        proj = data.get("project", {})
        v = proj.get("version")
        return str(v).strip() if v else None
    except Exception:
        return None

def get_current_version() -> str:
    """
    Prefer setuptools-scm (dynamic), else fall back to static pyproject version,
    else try best-effort from git tags.
    """
    # 1) setuptools-scm path (recommended)
    try:
        from setuptools_scm import get_version  # type: ignore
        return get_version(root=".", version_scheme="guess-next-dev", local_scheme="no-local-version")
    except Exception:
        pass

    # 2) static pyproject?
    v = get_version_from_pyproject_static()
    if v:
        return v

    # 3) try git tags best-effort (if available)
    if not have_git():
        print("setuptools-scm missing and git unavailable; cannot derive version", file=sys.stderr)
        sys.exit(2)

    # last matching tag vX.Y.Z
    tags = run(["git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname"]).splitlines()
    if not tags:
        print("No version tags found (expected tags like v1.2.3).", file=sys.stderr)
        sys.exit(2)
    last = tags[0]
    base = last.lstrip("v")
    m = SEMVER_RE.match(base)
    if not m:
        print(f"Latest tag {last} isn't a semantic version (vX.Y.Z).", file=sys.stderr)
        sys.exit(2)

    # commits since last tag -> .devN on next patch
    count = run(["git", "rev-list", "--count", f"{last}..HEAD"])
    try:
        n = int(count)
    except ValueError:
        n = 0
    if n <= 0:
        return base

    maj, minr, pat = int(m["maj"]), int(m["min"]), int(m["pat"])
    next_patch = f"{maj}.{minr}.{pat+1}.dev{n}"
    return next_patch

def bump_version(kind: str) -> Tuple[str, str]:
    """
    Returns (new_release_version, message). Does not tag.
    Logic:
      - if current == A.B.C           -> patch: A.B.(C+1), minor: A.(B+1).0, major: (A+1).0.0
      - if current == A.B.(C+1).devN  -> patch/minor/major computed from "A.B.(C+1)" baseline
    """
    cur = get_current_version()
    m = SEMVER_RE.match(cur)
    if not m:
        print(f"Current version '{cur}' not in expected form.", file=sys.stderr)
        sys.exit(2)
    maj, minr, pat = int(m["maj"]), int(m["min"]), int(m["pat"])
    # If we're on a .dev pre, that's already the "next patch" baseline; fine for bumps.
    if kind == "patch":
        newv = f"{maj}.{minr}.{pat}"
    elif kind == "minor":
        newv = f"{maj}.{minr+1}.0"
    elif kind == "major":
        newv = f"{maj+1}.0.0"
    else:
        print("kind must be major|minor|patch", file=sys.stderr)
        sys.exit(2)

    # Edge case: when not on .dev, patch must increment
    if m["dev"] is None and kind == "patch":
        newv = f"{maj}.{minr}.{pat+1}"

    msg = f"Release v{newv}"
    return newv, msg

def create_git_tag(newv: str, msg: str) -> None:
    if not have_git():
        print("git not available; cannot create tag.", file=sys.stderr)
        sys.exit(3)
    # Ensure clean-ish state: refuse if tag exists
    tags = run(["git", "tag", "--list", f"v{newv}"]).splitlines()
    if tags:
        print(f"Tag v{newv} already exists.", file=sys.stderr)
        sys.exit(3)
    run(["git", "tag", "-a", f"v{newv}", "-m", msg])
    print(f"Created tag v{newv}")

def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    ap_show = sub.add_parser("show", help="Print PEP 440 version")
    ap_show.add_argument("--debian", action="store_true", help="Print Debian-friendly version")

    sub.add_parser("debian", help="Print Debian-friendly version")

    ap_bump = sub.add_parser("bump", help="Bump version and create git tag vX.Y.Z")
    ap_bump.add_argument("kind", choices=["major", "minor", "patch"])
    ap_bump.add_argument("--dry-run", action="store_true", help="Compute and print, don't create tag")

    args = ap.parse_args()

    if args.cmd == "show":
        v = get_current_version()
        print(pep440_to_debian(v) if args.debian else v)
        return

    if args.cmd == "debian":
        v = get_current_version()
        print(pep440_to_debian(v))
        return

    if args.cmd == "bump":
        newv, msg = bump_version(args.kind)
        if args.dry_run:
            print(newv)
            return
        create_git_tag(newv, msg)
        print(newv)
        return

if __name__ == "__main__":
    main()

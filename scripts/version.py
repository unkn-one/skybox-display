#!/usr/bin/env python3
"""
scripts/version.py

Usage:
  version.py show [--debian]
  version.py debian
  version.py bump {major|minor|patch} [--dry-run]
  version.py desc    # short one-line description from pyproject.toml
"""
import argparse, os, re, subprocess, sys
import tomllib
from typing import Tuple

PYPROJECT = os.environ.get("PYPROJECT_TOML", "pyproject.toml")
SEMVER_RE = re.compile(r"^(?P<maj>\d+)\.(?P<min>\d+)\.(?P<pat>\d+)(?:\.dev(?P<dev>\d+))?$")

def run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as e:
        print(f"[cmd fail] {' '.join(cmd)}:\n{e.output}", file=sys.stderr)
        sys.exit(3)

def have_git() -> bool:
    try:
        subprocess.check_output(["git", "--version"])
        return True
    except Exception:
        return False

def pep440_to_debian(v: str) -> str:
    return v.replace(".dev", "~dev")

def pyproject() -> dict:
    try:
        with open(PYPROJECT, "rb") as f:
            return tomllib.load(f)
    except FileNotFoundError:
        print(f"{PYPROJECT} not found", file=sys.stderr)
        sys.exit(2)

def get_version_from_pyproject_static() -> str | None:
    try:
        proj = pyproject().get("project", {})
        v = proj.get("version")
        return str(v).strip() if v else None
    except Exception:
        return None

def get_description_from_pyproject() -> str:
    proj = pyproject().get("project", {})
    desc = proj.get("description", "").strip()
    if not desc:
        print("No description in [project] of pyproject.toml", file=sys.stderr)
        sys.exit(2)
    # deb control's short Description must be one line; take first line and trim
    return desc.splitlines()[0][:80]

def get_current_version() -> str:
    # 1) setuptools-scm (dynamic)
    try:
        from setuptools_scm import get_version  # type: ignore
        return get_version(root=".", version_scheme="guess-next-dev",
                           local_scheme="no-local-version")
    except Exception:
        pass
    # 2) static pyproject?
    v = get_version_from_pyproject_static()
    if v:
        return v
    # 3) derive from git tags as last resort
    if not have_git():
        print("setuptools-scm missing and git unavailable; cannot derive version", file=sys.stderr)
        sys.exit(2)
    tags = run(["git", "tag", "--list", "v[0-9]*.[0-9]*.[0-9]*", "--sort=-v:refname"]).splitlines()
    if not tags:
        print("No version tags like v1.2.3 found.", file=sys.stderr)
        sys.exit(2)
    last = tags[0]
    base = last.lstrip("v")
    m = SEMVER_RE.match(base)
    if not m:
        print(f"Latest tag {last} not in vX.Y.Z format.", file=sys.stderr)
        sys.exit(2)
    count = run(["git", "rev-list", "--count", f"{last}..HEAD"])
    n = int(count) if count.isdigit() else 0
    if n <= 0:
        return base
    maj, minr, pat = int(m["maj"]), int(m["min"]), int(m["pat"])
    return f"{maj}.{minr}.{pat+1}.dev{n}"

def bump_version(kind: str) -> Tuple[str, str]:
    cur = get_current_version()
    m = SEMVER_RE.match(cur)
    if not m:
        print(f"Current version '{cur}' not semver-ish.", file=sys.stderr)
        sys.exit(2)
    maj, minr, pat = int(m["maj"]), int(m["min"]), int(m["pat"])
    if kind == "patch":
        newv = f"{maj}.{minr}.{pat+1}" if m["dev"] is None else f"{maj}.{minr}.{pat}"
    elif kind == "minor":
        newv = f"{maj}.{minr+1}.0"
    elif kind == "major":
        newv = f"{maj+1}.0.0"
    else:
        print("kind must be major|minor|patch", file=sys.stderr)
        sys.exit(2)
    return newv, f"Release v{newv}"

def create_git_tag(newv: str, msg: str) -> None:
    if not have_git():
        print("git not available; cannot create tag.", file=sys.stderr)
        sys.exit(3)
    if run(["git", "tag", "--list", f"v{newv}"]):
        print(f"Tag v{newv} already exists.", file=sys.stderr)
        sys.exit(3)
    run(["git", "tag", "-a", f"v{newv}", "-m", msg])
    print(f"Created tag v{newv}")

def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_show = sub.add_parser("show")
    p_show.add_argument("--debian", action="store_true")
    sub.add_parser("debian")
    p_bump = sub.add_parser("bump")
    p_bump.add_argument("kind", choices=["major","minor","patch"])
    p_bump.add_argument("--dry-run", action="store_true")
    sub.add_parser("desc")

    args = ap.parse_args()
    if args.cmd == "show":
        v = get_current_version()
        print(pep440_to_debian(v) if args.debian else v)
        return
    elif args.cmd == "debian":
        print(pep440_to_debian(get_current_version()))
        return
    elif args.cmd == "desc":
        print(get_description_from_pyproject())
        return
    elif args.cmd == "bump":
        newv, msg = bump_version(args.kind)
        if not args.dry_run:
            create_git_tag(newv, msg)
        print(newv)
        return

if __name__ == "__main__":
    main()

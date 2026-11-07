"""Generate a unified diff of the migration against the upstream `dev` snapshot.

Usage:
    make_migration_patch.py [upstream-dir] [output.patch]

The diff covers the files that matter for the build integration:
`.github/**`, `config/**`, `README.md` and `README-EN.md`.
Files that do not exist upstream (e.g. the new `build-ak3.yml`) are emitted as
proper new-file hunks so the patch can be applied with `git apply -p1`.
"""

import difflib
import os
import sys

UPSTREAM_DEFAULT = os.path.join(os.environ.get("TEMP", "."), "resukisu-upstream", "Resukisu-dev")
CUR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UP = sys.argv[1] if len(sys.argv) > 1 else UPSTREAM_DEFAULT
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(CUR, "docs", "official-kernelsu-migration.patch")

INCLUDE_PREFIXES = (".github/", "config/")
INCLUDE_FILES = ("README.md", "README-EN.md")


def included(rel):
    return rel.startswith(INCLUDE_PREFIXES) or rel in INCLUDE_FILES


def collect(root):
    found = []
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules")]
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), root).replace(os.sep, "/")
            if included(rel):
                found.append(rel)
    return sorted(found)


def read(path):
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as fh:
        return fh.read().replace("\r\n", "\n")


def main():
    current = collect(CUR)
    chunks = []
    changed = []
    added = []

    for rel in current:
        cur_path = os.path.join(CUR, rel.replace("/", os.sep))
        up_path = os.path.join(UP, rel.replace("/", os.sep))
        body = read(cur_path)

        if not os.path.exists(up_path):
            added.append(rel)
            lines = body.splitlines(keepends=True)
            header = "--- /dev/null\n+++ b/%s\n@@ -0,0 +1,%d @@\n" % (rel, len(lines))
            chunks.append(header + "".join("+" + line for line in lines))
            if not body.endswith("\n"):
                chunks.append("\n\\ No newline at end of file\n")
            continue

        old = read(up_path)
        if old == body:
            continue
        changed.append(rel)
        chunks.append(
            "".join(
                difflib.unified_diff(
                    old.splitlines(keepends=True),
                    body.splitlines(keepends=True),
                    fromfile="a/" + rel,
                    tofile="b/" + rel,
                    n=3,
                )
            )
        )

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("".join(chunks))

    print("modified (%d):" % len(changed))
    for rel in changed:
        print("  M " + rel)
    print("added (%d):" % len(added))
    for rel in added:
        print("  A " + rel)
    print("patch:", OUT, os.path.getsize(OUT), "bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())

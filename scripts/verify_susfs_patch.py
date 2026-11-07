"""Dry-run the SUSFS KernelSU-side patch against the latest official KernelSU main.

For every file touched by `kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch`
this downloads the current `tiann/KernelSU@main` blob and checks, hunk by hunk,
that all context / removed lines still exist contiguously (i.e. `patch` would
find them, possibly with a line offset).
"""

import sys
import urllib.request

PATCH_BRANCH = sys.argv[1] if len(sys.argv) > 1 else "gki-android16-6.12"
PATCH_URL = (
    "https://gitlab.com/simonpunk/susfs4ksu/-/raw/%s/kernel_patches/KernelSU/"
    "10_enable_susfs_for_ksu.patch" % PATCH_BRANCH
)
RAW = "https://raw.githubusercontent.com/tiann/KernelSU/main/%s"


def fetch(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def parse_patch(text):
    """Return [(path, [(header, [body lines])])] for each file in the patch."""
    files = []
    cur = None
    hunk = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            cur = {"path": None, "hunks": []}
            files.append(cur)
            hunk = None
            continue
        if cur is None:
            continue
        if cur["path"] is None and line.startswith("+++ b/"):
            cur["path"] = line[len("+++ b/"):].strip()
            continue
        if line.startswith("@@"):
            hunk = {"header": line, "lines": []}
            cur["hunks"].append(hunk)
            continue
        if hunk is not None:
            if line.startswith("\\"):
                continue
            hunk["lines"].append(line)
    return [f for f in files if f["path"]]


def hunk_expectation(lines):
    """Lines that must exist in the target before the hunk is applied."""
    out = []
    for line in lines:
        if line.startswith("+"):
            continue
        if line.startswith(" "):
            out.append(line[1:])
        elif line.startswith("-"):
            out.append(line[1:])
    return out


def find_block(haystack, needle, hint):
    """Locate `needle` in `haystack`; prefer a match near `hint`."""
    if not needle:
        return hint, True
    n = len(needle)
    best = None
    for start in range(0, len(haystack) - n + 1):
        if haystack[start:start + n] == needle:
            distance = abs(start - hint)
            if best is None or distance < best[0]:
                best = (distance, start)
                if distance == 0:
                    break
    if best is None:
        return hint, False
    return best[1], True


def main():
    print("patch branch : %s" % PATCH_BRANCH)
    print("patch url    : %s" % PATCH_URL)
    patch = fetch(PATCH_URL)
    files = parse_patch(patch)

    total_hunks = 0
    failed_hunks = 0
    missing_files = 0
    max_offset = 0

    for entry in files:
        path = entry["path"]
        total_hunks += len(entry["hunks"])
        try:
            target = fetch(RAW % path).splitlines()
        except Exception as exc:  # noqa: BLE001
            print("  MISSING FILE %-55s (%s)" % (path, exc))
            missing_files += 1
            failed_hunks += len(entry["hunks"])
            continue

        line_cursor = 0
        bad = 0
        for hunk in entry["hunks"]:
            start = hunk["header"].split("-")[1].split(",")[0]
            hint = max(0, int(start) - 1 + line_cursor)
            block = hunk_expectation(hunk["lines"])
            pos, ok = find_block(target, block, hint)
            if not ok:
                bad += 1
                print("  HUNK FAIL   %-55s %s" % (path, hunk["header"]))
            else:
                delta = pos - hint
                max_offset = max(max_offset, abs(delta))
                line_cursor += delta
        failed_hunks += bad
        status = "OK" if bad == 0 else "PARTIAL(%d/%d)" % (bad, len(entry["hunks"]))
        print("  %-14s %-55s hunks=%d" % (status, path, len(entry["hunks"])))

    print()
    print("files=%d hunks=%d failed_hunks=%d missing_files=%d max_offset=%d"
          % (len(files), total_hunks, failed_hunks, missing_files, max_offset))
    if failed_hunks or missing_files:
        print("RESULT: patch would need fuzz/adaptation")
        return 1
    print("RESULT: SUSFS KernelSU-side patch applies cleanly to tiann/KernelSU@main")
    return 0


if __name__ == "__main__":
    sys.exit(main())

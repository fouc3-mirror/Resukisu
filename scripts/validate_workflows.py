"""Static validation for the Resukisu build workflows.

Checks:
  1. every workflow file is valid YAML with at least one trigger
  2. no line-ending corruption (CRLF) was introduced
  3. no SukiSU / ReSukiSU / KernelSU-Next / MKSU integration remains
  4. KPM is absent from the integration and explicitly disabled in defconfig
  5. official KernelSU setup + official AnyKernel3 are wired in
  6. SUSFS is forced on by every build entry workflow
"""

import glob
import os
import re
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF_DIR = os.path.join(ROOT, ".github", "workflows")

failures = []


def fail(msg):
    failures.append(msg)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


print("== 1/6 YAML structure ==")
workflows = sorted(glob.glob(os.path.join(WF_DIR, "*.yml")))
docs = {}
for path in workflows:
    name = os.path.basename(path)
    raw = read(path)
    crlf = raw.count("\r\n")
    if crlf:
        fail("%s: contains %d CRLF line endings" % (name, crlf))
    try:
        doc = yaml.safe_load(raw)
    except Exception as exc:  # noqa: BLE001
        fail("%s: YAML error: %s" % (name, exc))
        continue
    if not isinstance(doc, dict):
        fail("%s: root is not a mapping" % name)
        continue
    trigger = doc.get("on", doc.get(True))
    if not trigger:
        fail("%s: no event trigger" % name)
        continue
    jobs = doc.get("jobs") or {}
    if not jobs:
        fail("%s: no jobs" % name)
    docs[name] = doc
    names = ",".join(sorted(trigger)) if isinstance(trigger, dict) else str(trigger)
    print("  OK %-26s triggers=%-30s jobs=%d" % (name, names, len(jobs)))

print()
print("== 2/6 legacy KernelSU variants removed ==")
legacy = re.compile(r"SukiSU|ReSukiSU|KernelSU-Next|MKSU", re.IGNORECASE)
# The only tolerated mention is the third-party ZRAM/LZ4KD patch collection,
# which is a compression-algorithm patch source and has nothing to do with the
# KernelSU integration itself.
ZRAM_PATCH_SOURCE = 'git clone --depth=1 https://github.com/ShirkNeko/SukiSU_patch.git "$ZRAM_PATCHES"'
for path in workflows:
    name = os.path.basename(path)
    for lineno, line in enumerate(read(path).splitlines(), 1):
        if not legacy.search(line):
            continue
        if line.strip() == ZRAM_PATCH_SOURCE:
            print("  ALLOWED %s:%d (ZRAM/LZ4 patch source only)" % (name, lineno))
            continue
        fail("%s:%d: legacy variant reference: %s" % (name, lineno, line.strip()))
print("  scanned %d workflow files" % len(workflows))

print()
print("== 3/6 KPM not integrated ==")
build = read(os.path.join(WF_DIR, "build.yml"))
if "use_kpm" in build:
    fail("build.yml still exposes a use_kpm input")
if "CONFIG_KPM is not set" not in build:
    fail("build.yml does not force '# CONFIG_KPM is not set'")
if not re.search(r"sed -i '/\^CONFIG_KPM=/d", build):
    fail("build.yml does not strip existing CONFIG_KPM entries")
if re.search(r"^.*\bkpm.*patch\b", build, re.IGNORECASE | re.MULTILINE):
    fail("build.yml appears to still carry a KPM patch step")
print("  CONFIG_KPM forced off: yes")
print("  use_kpm input: absent")

print()
print("== 4/6 official KernelSU setup ==")
expected_setup = (
    'curl -fLSs "https://raw.githubusercontent.com/tiann/KernelSU/main/kernel/setup.sh"'
    ' | bash -s -- "$KSU_REF"'
)
if expected_setup not in build:
    fail("build.yml does not use the official KernelSU setup.sh invocation")
if 'KSU_REF="main"' not in build:
    fail("build.yml does not pin KSU_REF to main")
if "tiann/KernelSU" not in build:
    fail("build.yml does not reference tiann/KernelSU")
print("  setup.sh via curl && bash -s -- \"$KSU_REF\": yes")
print("  KSU_REF=main (latest source): yes")

print()
print("== 5/6 official AnyKernel3 packaging ==")
if "https://github.com/osm0sis/AnyKernel3.git" not in build:
    fail("build.yml does not clone official osm0sis/AnyKernel3")
if 'ANYKERNEL_BRANCH="master"' not in build:
    fail("build.yml does not use AnyKernel3 master branch")
if 'zip -r -9 "../$ZIP_NAME" ./* -x "README.md" "*placeholder*" ".git/*"' not in build:
    fail("AnyKernel3 zip does not follow the official exclusion rules")
print("  repo osm0sis/AnyKernel3, branch master: yes")
print("  zip excludes README.md / *placeholder* / .git: yes")

print()
print("== 6/6 SUSFS forced on ==")
if "https://gitlab.com/simonpunk/susfs4ksu" not in build:
    fail("build.yml does not clone simonpunk/susfs4ksu")
for entry in [
    "kernel-a12-5-10.yml",
    "kernel-a13-5-15.yml",
    "kernel-a14-6-1.yml",
    "kernel-a15-6-6.yml",
    "kernel-a16-6-12.yml",
    "kernel-custom.yml",
    "build-ak3.yml",
]:
    text = read(os.path.join(WF_DIR, entry))
    if "enable_susfs: true" not in text:
        fail("%s does not pass enable_susfs: true" % entry)
    else:
        print("  OK %-22s enable_susfs: true" % entry)

print()
if failures:
    print("FAILED (%d)" % len(failures))
    for item in failures:
        print("  - " + item)
    sys.exit(1)

print("ALL CHECKS PASSED")

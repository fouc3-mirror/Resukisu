"""Extract every `run:` script from the workflows and check its bash syntax.

Usage:  check_bash_syntax.py [repo-root] [report.json]

GitHub expressions (`${{ ... }}`) are replaced by a placeholder first, because
they are substituted before the shell ever sees the script.  bash-parser 0.5.0
is an old parser, so a few bash-only constructs (`<<<`, `<(...)`, `declare -A`,
escaped quotes inside double quotes) are reported as false positives; running
the same check against the pristine upstream snapshot shows which ones are
pre-existing and therefore not introduced by this migration.
"""

import glob
import json
import os
import re
import subprocess
import sys

import yaml

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
REPORT = sys.argv[2] if len(sys.argv) > 2 else ""
WF_DIR = os.path.join(ROOT, ".github", "workflows")
TMP = os.environ.get("TEMP", ".")
NODE = r"C:\Users\Admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\node\bin\node.exe"
MODULE = os.path.join(TMP, "bashparse", "node_modules", "bash-parser")

EXPR = re.compile(r"\$\{\{[^}]*\}\}")


def walk(node, path, acc):
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "run" and isinstance(value, str):
                acc.append((path, value))
            else:
                walk(value, path + "/" + str(key), acc)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            walk(value, path + "/" + str(i), acc)


def main():
    tag = re.sub(r"[^A-Za-z0-9]+", "_", ROOT)[-24:]
    out_dir = os.path.join(TMP, "wf-scripts-" + tag)
    os.makedirs(out_dir, exist_ok=True)

    manifest = []
    for wf in sorted(glob.glob(os.path.join(WF_DIR, "*.yml"))):
        doc = yaml.safe_load(open(wf, encoding="utf-8"))
        acc = []
        walk(doc.get("jobs") or {}, os.path.basename(wf), acc)
        for index, (label, script) in enumerate(acc):
            script = EXPR.sub("__EXPR__", script)
            name = "%s__%02d.sh" % (re.sub(r"[^A-Za-z0-9_.-]", "_", label), index)
            path = os.path.join(out_dir, name)
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(script)
            manifest.append({"label": label, "path": path})

    manifest_path = os.path.join(out_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh)

    checker = os.path.join(out_dir, "check.js")
    with open(checker, "w", encoding="utf-8") as fh:
        fh.write(
            """
const fs = require('fs');
const parse = require(%s);
const manifest = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const report = [];
for (const entry of manifest) {
  const src = fs.readFileSync(entry.path, 'utf8');
  try { parse(src); } catch (e) { report.push(entry.label + ' :: ' + e.message.split('\\n')[0]); }
}
fs.writeFileSync(process.argv[3], JSON.stringify(report, null, 2));
console.log('scripts=' + manifest.length + ' failures=' + report.length);
for (const r of report) console.log('  FAIL ' + r);
"""
            % json.dumps(MODULE)
        )

    json_out = os.path.join(out_dir, "failures.json")
    result = subprocess.run(
        [NODE, checker, manifest_path, json_out], capture_output=True, text=True
    )
    print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    if REPORT:
        with open(REPORT, "w", encoding="utf-8") as fh:
            if os.path.exists(json_out):
                fh.write(open(json_out, encoding="utf-8").read())
    return 0


if __name__ == "__main__":
    sys.exit(main())

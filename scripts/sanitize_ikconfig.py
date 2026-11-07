#!/usr/bin/env python3
"""Sanitize the kernel's embedded .config that userspace sees as /proc/config.gz.

Why: a stock GKI kernel keeps CONFIG_IKCONFIG/_PROC on, so any app can read
/proc/config.gz.  A KernelSU+SUSFS build therefore leaks CONFIG_KSU=y, every
CONFIG_KSU_SUSFS_* option, CONFIG_BBG and the build's CONFIG_LOCALVERSION.
Turning CONFIG_IKCONFIG off removes the leak but changes the kernel binary;
this script instead rewrites the embedded gzip payload in place so that the
reported config matches stock, while the kernel binary is otherwise untouched.

Constraints:
  * the payload lives in a fixed-size .rodata array (kernel_config_data), so the
    replacement gzip must be exactly as long as the original one -> pad with a
    gzip FEXTRA field;
  * the kernel only hands the raw bytes to userspace (it never decompresses
    them), so a valid gzip stream with padding is fine.

Usage: sanitize_ikconfig.py <Image> [<Image> ...]
"""

import gzip
import re
import struct
import sys
import zlib

ST = b"IKCFG_ST"
ED = b"IKCFG_ED"

# Kconfig emits "manu" blocks:
#     (blank)
#     #
#     # <title>
#     #
#     ...options...
#     # end of <title>
#     (blank)
# Dropping the whole block keeps the result byte-identical to stock.
BLOCK_TITLES = (
    "KernelSU",
    "Baseband Security Guard Configuration",
)

STOCK_LSM = (
    'CONFIG_LSM="landlock,lockdown,yama,loadpin,safesetid,selinux,'
    'smack,tomoyo,apparmor,bpf"'
)
STOCK_LOCALVERSION = 'CONFIG_LOCALVERSION="-4k"'

REWRITE = {
    "CONFIG_LTO=y": None,                  # our build is thin, stock is none
    "CONFIG_LTO_CLANG=y": None,
    "CONFIG_LTO_CLANG_THIN=y": "# CONFIG_LTO_CLANG_THIN is not set",
    "# CONFIG_LTO_NONE is not set": "CONFIG_LTO_NONE=y",
    "CONFIG_TMPFS_XATTR=y": "# CONFIG_TMPFS_XATTR is not set",
    "CONFIG_TMPFS_POSIX_ACL=y": "# CONFIG_TMPFS_POSIX_ACL is not set",
    "CONFIG_LOCALVERSION=\"-g0908354dac1b-ab16143355-4k\"": STOCK_LOCALVERSION,
}

# safety net for anything left outside a block
DROP_PREFIX = ("CONFIG_KSU=", "CONFIG_KSU_", "# CONFIG_KSU", "CONFIG_BBG=",
               "# CONFIG_BBG", "CONFIG_BBG_")


def drop_blocks(lines):
    for title in BLOCK_TITLES:
        start = None
        for i, line in enumerate(lines):
            if line.strip() == "# " + title:
                start = i
                break
        if start is None:
            continue
        end = None
        for j in range(start, len(lines)):
            if lines[j].strip() == "# end of " + title:
                end = j
                break
        if end is None:
            continue
        lo = start - 1 if start > 0 and lines[start - 1].strip() == "#" else start
        hi = end
        # swallow one trailing/leading blank so spacing stays stock-like
        if hi + 1 < len(lines) and lines[hi + 1].strip() == "":
            hi += 1
        elif lo > 0 and lines[lo - 1].strip() == "":
            lo -= 1
        del lines[lo:hi + 1]
    return lines


def sanitize(text):
    lines = drop_blocks(text.split("\n"))
    out = []
    for line in lines:
        s = line.strip()
        if s.startswith(DROP_PREFIX):
            continue
        if s.startswith("CONFIG_LOCALVERSION="):
            out.append(STOCK_LOCALVERSION)
            continue
        if s.startswith("CONFIG_LSM="):
            out.append(STOCK_LSM)
            continue
        if s in REWRITE:
            repl = REWRITE[s]
            if repl is not None:
                out.append(repl)
            continue
        out.append(line)
    return "\n".join(out)


def pack_same_length(text, target_len):
    """Return a gzip stream of exactly target_len bytes (FEXTRA padded)."""
    raw = text.encode()
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    body = deflater.compress(raw) + deflater.flush()
    overhead = 10 + 2 + 8          # base header + XLEN + crc/isize
    xlen = target_len - overhead - len(body)
    if xlen < 4:
        raise SystemExit(
            "sanitized payload does not fit: need %d bytes, room %d"
            % (target_len, overhead + len(body))
        )
    extra = b"IK" + struct.pack("<H", xlen - 4) + b"\x00" * (xlen - 4)
    head = (
        b"\x1f\x8b\x08\x04"        # magic, deflate, FEXTRA
        b"\x00\x00\x00\x00"        # mtime 0
        b"\x00\xff"                # xfl, os = unknown
        + struct.pack("<H", xlen)
        + extra
    )
    blob = head + body + struct.pack(
        "<II", zlib.crc32(raw) & 0xFFFFFFFF, len(raw) & 0xFFFFFFFF
    )
    assert len(blob) == target_len, (len(blob), target_len)
    gzip.decompress(blob)          # must parse
    return blob


def patch(path):
    data = bytearray(open(path, "rb").read())
    st = data.find(ST)
    if st < 0:
        print("%s: no IKCFG_ST (CONFIG_IKCONFIG off) - nothing to do" % path)
        return 0
    ed = data.find(ED, st)
    if ed < 0:
        raise SystemExit("%s: IKCFG_ED not found" % path)
    blob = bytes(data[st + len(ST):ed])
    text = gzip.decompress(blob).decode("utf-8", "replace")
    if "CONFIG_KSU" not in text and "CONFIG_BBG" not in text:
        print("%s: config.gz already clean" % path)
        return 0
    clean = sanitize(text)
    for bad in ("CONFIG_KSU", "CONFIG_BBG", "baseband_guard"):
        if bad in clean:
            raise SystemExit("%s: %s survived sanitizing" % (path, bad))
    new = pack_same_length(clean, len(blob))
    data[st + len(ST):ed] = new
    open(path, "wb").write(bytes(data))
    print(
        "%s: /proc/config.gz sanitized, payload %d bytes unchanged, %d lines"
        % (path, len(new), clean.count("\n") + 1)
    )
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    rc = 0
    for p in sys.argv[1:]:
        rc |= patch(p)
    sys.exit(rc)

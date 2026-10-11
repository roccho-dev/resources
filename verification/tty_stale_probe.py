"""Finite fault isolation of the unchanged pinned TTY; never Host acceptance.

The real tty.c runs on a PTY. Only its CDP port and terminal ACK peer are
synthetic. No Chrome, network, product patch, retry or replacement Viewer.
A known failure reproduced here is evidence, not a successful product test.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import struct
import subprocess
import tempfile
import termios
import time

# Assert the exact upstream bytes before compiling; never carry a source copy.
BLOBS = {
    "tty.c": "5c9f27cb9ef2a0c5ebbe38ec58cf22f0ecb507f2",
    "tty.h": "958ff31a7047c166346bb8cf1394f4542e60569d",
    "cdp.h": "a0ed6f877d43c8bcb6dd0220430d4f607c6c4f05",
}
PORT = r'''
#define _POSIX_C_SOURCE 200809L
#include "tty.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
static int mode, frames, actions, injected;
static long long ms(void) {
    struct timespec t; clock_gettime(CLOCK_MONOTONIC, &t);
    return t.tv_sec*1000LL+t.tv_nsec/1000000;
}
void frame_free(Frame *f) { free(f->png); free(f->geometry); memset(f,0,sizeof(*f)); }
int frame_equal(const Frame *a, const Frame *b) {
    return a->geometry && b->geometry && !strcmp(a->geometry,b->geometry);
}
int valid_utf8(const unsigned char *s, size_t n) {
    /* Only ASCII is sent by this state test; not a UTF-8 implementation proof. */
    for (size_t i=0; i<n; i++) if (s[i]>=128) return 0;
    return 1;
}
int cdp_frame(Cdp *c, Frame *f) {
    (void)c; memset(f,0,sizeof(*f)); ++frames;
    int status=CDP_OK;
    if (!injected && ((mode==1 && actions==1) || (mode==2 && frames==1))) {
        injected=1; status=CDP_STALE;
    } else if (!injected && mode==3 && actions==1) {
        injected=1; status=CDP_ERROR;
    }
    fprintf(stderr,"{\"event\":\"frame\",\"ms\":%lld,\"status\":%d,\"actions\":%d}\n",ms(),status,actions);
    if (status) return status;
    /* Valid 1x1 PNG; the synthetic peer does not claim to render it. */
    f->png=strdup("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVR4nGP4DwQACfsD/fteaysAAAAASUVORK5CYII=");
    f->geometry=strdup(actions ? "after-wheel":"before-wheel");
    if (!f->png || !f->geometry) { frame_free(f); return CDP_ERROR; }
    f->len=strlen(f->png); f->width=f->height=1;
    f->css_width=f->css_height=1; return CDP_OK;
}
int cdp_apply(Cdp *c, const Frame *f, const Action *a) {
    (void)c; (void)f;
    if (a->kind!=WHEEL) return CDP_UNSUPPORTED;
    ++actions;
    fprintf(stderr,"{\"event\":\"apply\",\"ms\":%lld,\"actions\":%d}\n",ms(),actions);
    return CDP_OK;
}
int main(int argc, char **argv) {
    if (argc!=2) return 64;
    mode=atoi(argv[1]); setvbuf(stderr,NULL,_IOLBF,0);
    const volatile sig_atomic_t cancel=0;
    int status=tty_run(NULL,0,&cancel);
    fprintf(stderr,"{\"event\":\"exit\",\"ms\":%lld,\"status\":%d,\"frames\":%d,\"actions\":%d}\n",ms(),status,frames,actions);
    return status;
}
'''


def trial(binary, directory, name, mode):
    """One process, one wheel, finite observation; no result-driven retries."""
    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 640, 384))
    saved = termios.tcgetattr(slave)
    trace = directory / (name + ".jsonl")
    images, acknowledgements, pending = [], [], b""
    wheel_at = None
    started = time.monotonic()
    packet = re.compile(rb"\x1b_G([^;]*);[^\x1b]*\x1b\\")
    with trace.open("wb") as output:
        process = subprocess.Popen([str(binary), str(mode)], stdin=slave,
                                   stdout=slave, stderr=output, close_fds=True)
        try:
            while process.poll() is None:
                assert time.monotonic() - started < 8, "probe exceeded finite bound"
                ready, _, _ = select.select([master], [], [], 0.025)
                if ready:
                    pending += os.read(master, 8192)
                    assert len(pending) < 32768, "unbounded synthetic peer input"
                    if b"\x1b[16t" in pending:
                        os.write(master, b"\x1b[6;16;8t")
                        pending = pending.replace(b"\x1b[16t", b"")
                    while match := packet.search(pending):
                        header = dict(field.split(b"=", 1) for field in match[1].split(b",") if b"=" in field)
                        pending = pending[match.end():]
                        if header.get(b"a") == b"T":
                            assert header.get(b"m") == b"0", "fixture must fit one packet"
                            image = int(header[b"i"])
                            images.append(image)
                            # Withhold only the newly emitted post-wheel image ACK.
                            if not (mode == 4 and len(images) > 1):
                                os.write(master, b"\x1b_Gi=%d;OK\x1b\\" % image)
                                acknowledgements.append(image)
                rows = [json.loads(line) for line in trace.read_text().splitlines()]
                # Two successful reads before input prove the initial ACK was consumed:
                # the second is gated by ready in the unchanged TTY loop.
                if wheel_at is None and sum(r["event"] == "frame" and r["status"] == 0 for r in rows) >= 2:
                    os.write(master, b"\x1b[<65;40;12M")
                    wheel_at = time.monotonic()
                if wheel_at is not None and time.monotonic() - wheel_at >= 4:
                    assert mode in (0, 2), "expected diagnostic failure did not occur"
                    os.write(master, b"\x11")
                    process.wait(timeout=1)
            process.wait(timeout=1)
            restored = termios.tcgetattr(slave) == saved
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=1)
            os.close(master)
            os.close(slave)
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    assert rows[-1]["event"] == "exit" and restored
    assert sum(r["event"] == "apply" for r in rows) == 1, "wheel absent or replayed"
    post = [r for r in rows if r["event"] == "frame" and r["actions"] == 1]
    assert post
    if mode in (0, 2):
        assert process.returncode == 0 and len(images) == len(acknowledgements) == 2
        assert len(post) >= 2 and all(r["status"] == 0 for r in post)
    else:
        assert process.returncode == 1 and len(post) == 1
        assert post[0]["status"] == {1: 2, 3: 1, 4: 0}[mode]
        assert len(images) == (2 if mode == 4 else 1)
        assert len(acknowledgements) == 1
        delay = rows[-1]["ms"] - post[0]["ms"]
        assert (delay < 1000) if mode == 3 else (3000 <= delay < 7000)
    initial_stale = [r for r in rows if r["event"] == "frame" and r["status"] == 2 and r["actions"] == 0]
    assert len(initial_stale) == (1 if mode == 2 else 0)
    result = {"test": "pinned-tty-stale-isolation", "case": name,
              "scope": "native-tty-synthetic-ports-only", "acceptance": "NOT_PROVEN",
              "outcome": "EXPECTED_DIAGNOSTIC_OBSERVATION", "exit": process.returncode,
              "wheel_calls": 1, "post_wheel_frame_calls": len(post),
              "post_wheel_first_status": post[0]["status"],
              "post_frame_to_exit_ms": rows[-1]["ms"] - post[0]["ms"],
              "images": len(images), "acks": len(acknowledgements), "tty_restored": restored}
    print(json.dumps(result, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    args = parser.parse_args()
    for name, expected in BLOBS.items():
        data = (args.source / name).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        assert actual == expected, "unexpected pinned source: " + name
    with tempfile.TemporaryDirectory(prefix="tty-stale-probe-") as temp:
        directory = Path(temp)
        port, binary = directory / "port.c", directory / "probe"
        port.write_text(PORT)
        subprocess.run(shlex.split(os.environ.get("CC", "cc")) +
                       ["-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I", str(args.source),
                        str(args.source / "tty.c"), str(port), "-lm", "-o", str(binary)],
                       check=True, timeout=30)
        for name, mode in (("baseline", 0), ("post-wheel-stale-once", 1),
                           ("initial-stale-once", 2), ("post-wheel-error", 3),
                           ("post-wheel-ack-withheld", 4)):
            trial(binary, directory, name, mode)


if __name__ == "__main__":
    main()

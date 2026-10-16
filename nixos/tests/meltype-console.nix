# The physical console path in a VM, as on VersaPro: QEMU's keyboard → kernel input → evdev → libinput → bcon,
# then meltype-tty and an interactive bash. Three logins on the getty VT, one at a time:
#   probe   bcon → bash                (no meltype-tty: which layer loses a key)
#   tracer  bcon → meltype-tty → bash  (os.read/os.write and the Direct Input state traced into a VM file)
#   meltype the real meltype-console login (nixos/meltype-console.nix)
# Users, passwords and keystrokes exist only in this VM; nothing from a host is recorded.
{ pkgs, meltypeConsole }:
let
  bash = "${pkgs.bashInteractive}/bin/bash";
  # A login shell like meltype-login, with another child for bcon.
  bconLogin = name: child: (pkgs.writeShellScriptBin name ''
    if [ "$#" -eq 0 ]; then
      . /etc/set-environment
      export SHELL=${child} BCON_BACKEND=seatd
      exec /run/current-system/sw/bin/bcon
    fi
    exec ${bash} "$@"
  '').overrideAttrs (_: { passthru.shellPath = "/bin/${name}"; });
  probeLogin = bconLogin "probe-login" bash;
  # Imported by meltype-tty's Python at startup (PYTHONPATH): records its byte boundaries and, at each read
  # from bcon, the Direct Input state before that input is processed.
  traceSite = pkgs.writeTextDir "usercustomize.py" ''
    import gc, json, os, sys, time
    path = os.environ.pop("MELTYPE_TRACE", None)
    os.environ.pop("PYTHONPATH", None)
    if path:
        log = open(path, "a", buffering=1)
        real_read, real_write = os.read, os.write
        def state():
            cls = getattr(sys.modules.get("__main__"), "InputBridge", None)
            for o in gc.get_objects() if cls else ():
                if isinstance(o, cls):
                    return {"direct": o.direct, "composing": o.view is not None, "capturing": o.capturing,
                            "paused": o.paused, "escape": bytes(o.escape).hex(), "shadow": bytes(o.shadow).decode("latin-1"),
                            "unechoed": bytes(o.unechoed).decode("latin-1"), "erasing": o.erasing}
            return None
        def record(op, fd, data):
            entry = {"t": round(time.monotonic(), 4), "op": op, "fd": fd}
            if op == "write" and fd == 1: entry["len"] = len(data)
            else: entry["hex"] = bytes(data).hex()
            if op == "read" and fd == 0: entry["state"] = state()
            log.write(json.dumps(entry) + "\n")
        def read(fd, n):
            data = real_read(fd, n); record("read", fd, data); return data
        def write(fd, data):
            n = real_write(fd, data); record("write", fd, bytes(data)[:n]); return n
        os.read, os.write = read, write
  '';
  traceShell = pkgs.writeShellScript "trace-shell" ''
    export SHELL=${bash} PYTHONPATH=${traceSite} MELTYPE_TRACE=/tmp/di2-trace.jsonl
    exec /run/current-system/sw/bin/meltype-tty --raw-text
  '';
  traceLogin = bconLogin "trace-login" traceShell;
in
{
  name = "versapro-meltype-console";

  nodes.machine = { ... }: {
    imports = [ meltypeConsole ];
    virtualisation.memorySize = 3072;
    virtualisation.cores = 2;
    environment.variables.LIBGL_ALWAYS_SOFTWARE = "1";
    users.users.meltype.password = "vm";
    users.users.probe = { isNormalUser = true; password = "vm"; extraGroups = [ "seat" "video" "input" ]; shell = probeLogin; };
    users.users.tracer = { isNormalUser = true; password = "vm"; extraGroups = [ "seat" "video" "input" ]; shell = traceLogin; };
    environment.shells = [ probeLogin traceLogin ];
  };

  testScript = ''
    import json
    import time

    start_all()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("seatd.service")

    def login(user):
        machine.wait_until_tty_matches("1", "login: ")
        machine.send_chars(user + "\n")
        machine.wait_until_tty_matches("1", "Password: ")
        machine.send_chars("vm\n")
        machine.wait_until_succeeds(f"pgrep -u {user} -x .bcon-wrapped", timeout=90)
        machine.wait_until_succeeds(f"pgrep -u {user} -x bash", timeout=90)
        time.sleep(5)  # the prompt is drawn

    def logout(user):
        machine.send_key("ctrl-d")
        machine.wait_until_fails(f"pgrep -u {user} -x .bcon-wrapped", timeout=90)
        machine.wait_until_fails(f"pgrep -u {user}", timeout=90)
        machine.wait_until_succeeds("systemctl is-active getty@tty1.service", timeout=90)
        time.sleep(3)

    def read(path):
        return machine.succeed(f"cat {path} 2>/dev/null || true")

    def raw_keys(name):
        # The bytes the session's program receives for a, Tab, Ctrl+Space and Ctrl+R.
        out = f"/tmp/di2-{name}-raw"
        machine.send_chars(f"stty raw -echo; timeout 8 cat > {out}; stty sane\n")
        time.sleep(2)
        machine.send_chars("a")
        machine.send_key("tab")
        machine.send_key("ctrl-spc")
        machine.send_key("ctrl-r")
        time.sleep(9)
        return " ".join(machine.succeed(f"od -An -tx1 {out} 2>/dev/null || true").split())

    def tab(name):
        out = f"/tmp/di2-{name}-tab"
        machine.send_chars("printf %s /nix/sto")
        machine.send_key("tab")
        time.sleep(2)
        machine.send_chars(f" > {out}\n")
        time.sleep(2)
        machine.screenshot(f"di2-{name}-tab")
        return read(out)

    def ctrl_r(name):
        out = f"/tmp/di2-{name}-r"
        machine.send_chars(f"echo r-marker >> {out}\n")
        time.sleep(2)
        machine.send_key("ctrl-r")
        machine.send_chars("r-marker")
        time.sleep(1)
        machine.send_key("ret")
        time.sleep(2)
        return read(out).count("r-marker")

    def conversion(name):
        out = f"/tmp/di2-{name}-conv"
        machine.send_chars("echo nihongo")
        time.sleep(2)
        machine.send_key("ctrl-spc")
        time.sleep(2)
        machine.screenshot(f"di2-{name}-conv")
        machine.send_chars(" ")
        time.sleep(2)
        machine.send_key("ret")
        time.sleep(2)
        machine.send_chars(f" > {out}\n")
        time.sleep(2)
        return read(out).strip()

    summary = {}
    login("probe")
    summary["probe"] = {"raw": raw_keys("probe"), "tab": tab("probe"), "ctrl_r": ctrl_r("probe")}
    logout("probe")

    login("tracer")
    summary["tracer"] = {"raw": raw_keys("tracer"), "tab": tab("tracer"),
        "conversion": conversion("tracer"), "ctrl_r": ctrl_r("tracer")}
    logout("tracer")
    for line in read("/tmp/di2-trace.jsonl").splitlines():
        entry = json.loads(line)
        if entry.get("fd") != 1: print("DI2-TRACE " + json.dumps(entry))

    login("meltype")
    summary["meltype"] = {"raw": raw_keys("meltype"), "tab": tab("meltype"),
        "conversion": conversion("meltype"), "ctrl_r": ctrl_r("meltype")}
    logout("meltype")

    print("DI2-SUMMARY " + json.dumps(summary, ensure_ascii=False))
    for user in ["probe", "tracer", "meltype"]:
        got = summary[user]
        assert got["raw"] == "61 09 00 12", (user, "raw bytes", got)
        assert got["tab"] == "/nix/store/", (user, "Tab completion", got)
        assert got["ctrl_r"] == 2, (user, "Ctrl+R", got)
        if user != "probe": assert got["conversion"] == "日本語", (user, "Ctrl+Space conversion", got)
  '';
}

# The physical console path in a VM, as on VersaPro: QEMU's keyboard → kernel input → evdev → libinput → bcon,
# then meltype-tty and an interactive bash. Two logins on the getty VT, one at a time:
#   probe   bcon → bash                (no meltype-tty: which layer loses a key)
#   meltype the real meltype-console login (nixos/meltype-console.nix): bcon → meltype-tty → bash
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
    environment.shells = [ probeLogin ];
    # VM-only completion evidence, not input logging or a production shell change.
    environment.interactiveShellInit = ''
      case "$USER" in
        probe|meltype) PROMPT_COMMAND='printf "\n" >> "/tmp/di2-$USER-prompts"' ;;
      esac
    '';
  };

  testScript = ''
    import json
    import time

    start_all()
    machine.wait_for_unit("multi-user.target")
    machine.wait_for_unit("seatd.service")

    def prompt_count(user):
        return int(machine.succeed(f"wc -l < /tmp/di2-{user}-prompts").strip())

    def completed(user, before):
        # Poll evidence only. Never send another Enter or replay a tested command to obtain a PASS.
        machine.wait_until_succeeds(
            f"test $(wc -l < /tmp/di2-{user}-prompts) -eq {before + 1}", timeout=30)
        assert prompt_count(user) == before + 1, (user, "unexpected extra prompt")

    def login(user):
        machine.wait_until_tty_matches("1", "login: ")
        machine.send_chars(user + "\n")
        machine.wait_until_tty_matches("1", "Password: ")
        machine.send_chars("vm\n")
        machine.wait_until_succeeds(f"pgrep -u {user} -x .bcon-wrapped", timeout=90)
        machine.wait_until_succeeds(f"pgrep -u {user} -x bash", timeout=90)
        machine.wait_until_succeeds(f"test -s /tmp/di2-{user}-prompts", timeout=30)
        time.sleep(5)  # the prompt is drawn

    def logout(user):
        machine.send_key("ctrl-d")
        machine.wait_until_fails(f"pgrep -u {user} -x .bcon-wrapped", timeout=90)
        machine.wait_until_fails(f"pgrep -u {user}", timeout=90)
        machine.wait_until_succeeds("systemctl is-active getty@tty1.service", timeout=90)
        time.sleep(3)

    def read(path):
        return machine.succeed(f"cat {path}")

    def raw_keys(name):
        # The bytes the session's program receives for a, Tab, Ctrl+Space and Ctrl+R.
        out = f"/tmp/di2-{name}-raw"
        before = prompt_count(name)
        machine.send_chars(f"stty raw -echo; touch {out}.ready; timeout 8 cat > {out}; stty sane\n")
        machine.wait_until_succeeds(f"test -e {out}.ready", timeout=30)
        machine.send_chars("a")
        machine.send_key("tab")
        machine.send_key("ctrl-spc")
        machine.send_key("ctrl-r")
        completed(name, before)
        return " ".join(machine.succeed(f"od -An -tx1 {out}").split())

    def tab(name):
        out = f"/tmp/di2-{name}-tab"
        before = prompt_count(name)
        machine.send_chars("printf %s /nix/sto")
        machine.send_key("tab")
        time.sleep(2)
        machine.send_chars(f" > {out}\n")
        completed(name, before)
        machine.screenshot(f"di2-{name}-tab")
        result = read(out)
        assert result == "/nix/store/", (name, "Tab completion", result)
        return result

    def ctrl_r(name):
        out = f"/tmp/di2-{name}-r"
        before = prompt_count(name)
        machine.send_chars(f"echo r-marker >> {out}\n")
        completed(name, before)
        before = prompt_count(name)
        machine.send_key("ctrl-r")
        machine.send_chars("r-marker")
        time.sleep(1)
        machine.send_key("ret")
        completed(name, before)
        return read(out).count("r-marker")

    def conversion(name):
        out = f"/tmp/di2-{name}-conv"
        before = prompt_count(name)
        machine.send_chars("echo nihongo")
        time.sleep(2)
        machine.send_key("ctrl-spc")
        time.sleep(2)
        machine.screenshot(f"di2-{name}-conv")
        # Since Meltype v1.2.1.8 Ctrl+Space already converts; Enter commits the first candidate (Meltype#24).
        machine.send_key("ret")
        time.sleep(2)
        machine.send_chars(f" > {out}\n")
        completed(name, before)
        return read(out).strip()

    summary = {}
    login("probe")
    summary["probe"] = {"raw": raw_keys("probe"), "tab": tab("probe"), "ctrl_r": ctrl_r("probe")}
    logout("probe")

    login("meltype")
    summary["meltype"] = {"raw": raw_keys("meltype"), "tab": tab("meltype"),
        "conversion": conversion("meltype"), "ctrl_r": ctrl_r("meltype")}
    logout("meltype")

    print("DI2-SUMMARY " + json.dumps(summary, ensure_ascii=False))
    for user in ["probe", "meltype"]:
        got = summary[user]
        assert got["raw"] == "61 09 00 12", (user, "raw bytes", got)
        assert got["tab"] == "/nix/store/", (user, "Tab completion", got)
        assert got["ctrl_r"] == 2, (user, "Ctrl+R", got)
        if user != "probe": assert got["conversion"] == "日本語", (user, "Ctrl+Space conversion", got)
  '';
}

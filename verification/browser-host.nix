# Normal acceptance and an explicitly separate, observer-affected diagnostic.
{ diagnostic ? false }:
let
  pkgs = import ./pkgs.nix;
  # Reuse the existing pinned diagnostic producer: no dependency source is copied
  # into resources, and the real Host dependency still has doCheck=true.
  native = (import ./cdp-geometry.nix).CDP_TTY_PACKAGE;
  observer = pkgs.runCommand "cdp-tty-call-observer" {
    nativeBuildInputs = [ pkgs.stdenv.cc pkgs.pkg-config pkgs.python3 ];
    buildInputs = [ (pkgs.curl.override { websocketSupport = true; }) pkgs.json_c ];
  } ''
    mkdir -p "$out/bin" "$out/share/observer"
    flags="-std=c11 -O2 -Wall -Wextra -Werror"
    cc $flags -I${native} $(pkg-config --cflags libcurl json-c) \
      ${native}/main.c ${native}/tty.c ${./viewer-observer.c} ${native}/libcdp-tty.a \
      -Wl,--wrap=cdp_frame,--wrap=cdp_apply,--wrap=json_object_equal,--wrap=read,--wrap=write \
      $(pkg-config --libs libcurl json-c) -lm -o "$out/bin/cdp-tty"
    cc $flags -DOBSERVER_SELFTEST -I${native} $(pkg-config --cflags json-c) \
      ${./viewer-observer.c} -Wl,--wrap=json_object_equal,--wrap=read,--wrap=write \
      $(pkg-config --libs json-c) -o observer-selftest
    CDP_TTY_TRACE="$PWD/selftest.jsonl" ./observer-selftest > selftest.stdout
    python3 - <<'PY'
    import json, pathlib
    rows = [json.loads(line) for line in pathlib.Path('selftest.jsonl').read_text().splitlines()]
    for event in ('frame.end', 'apply.end'):
        assert [r['status'] for r in rows if r['event'] == event] == [0, 1, 2, 3]
    changes = [r for r in rows if r['event'] == 'geometry.mismatch' and r['area'] == 'visual']
    assert len(changes) == 1 and changes[0]['before'] == {'pageY': 0} and changes[0]['after'] == {'pageY': 80}
    assert len([r for r in rows if r['event'] == 'kitty.ack' and r['image_id'] == 91 and r['ok']]) == 1
    assert pathlib.Path('selftest.stdout').read_bytes() == b'fixture'
    print('OBSERVER_SELFTEST_PASS: status/arguments/call-count/bytes preserved; diagnostic only')
    PY
    cp selftest.jsonl "$out/share/observer/"
    # Fault isolation of unchanged tty.c; synthetic ports, never Host acceptance.
    python3 -u ${./tty_stale_probe.py} --source ${native} \
      > "$out/share/observer/tty-stale-isolation.jsonl"
    cat "$out/share/observer/tty-stale-isolation.jsonl"
    sha256sum ${native}/libcdp-tty.a ${native}/main.c ${native}/tty.c ${./viewer-observer.c} ${./tty_stale_probe.py} \
      > "$out/share/observer/source.sha256"
  '';
  fixture = pkgs.writeText "browser-host-page.html" (builtins.readFile ./page.html);
  remote = { ... }: {
    environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.procps pkgs.python3 ];
    virtualisation.memorySize = 512;
  };
in pkgs.testers.runNixOSTest {
  name = if diagnostic then "browser-host-call-observer" else "browser-host-session";
  globalTimeout = 300;
  extraPythonPackages = p: [ p.pillow ];
  nodes = {
    browser = { ... }: {
      imports = [ ../nixos/browser-host.nix ];
      services.browserHost = { enable = true; initialUrl = "file://${fixture}"; };
      virtualisation.memorySize = 2048;
      # Only the separate diagnostic uses the same sources linked with observers.
      # The normal test and installed Host continue to use the original package.
      environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.kbd pkgs.procps
        (pkgs.python3.withPackages (p: [ p.websocket-client ])) ]
        ++ pkgs.lib.optionals diagnostic [ (pkgs.lib.hiPrio observer) ];
      environment.variables = pkgs.lib.optionalAttrs diagnostic {
        CDP_TTY_TRACE = "/run/viewer-trace.jsonl";
      };
      hardware.graphics.enable = true;
      services.dbus.enable = true;
      fonts.packages = [ pkgs.noto-fonts pkgs.noto-fonts-cjk-sans ];
      systemd.services.browser-host-terminal.environment.LIBGL_ALWAYS_SOFTWARE = "1";
      services.openssh.enable = true;
      services.openssh.settings.PermitRootLogin = "prohibit-password";
    };
    remoteA = remote;
    remoteB = remote;
  };
  testScript = builtins.readFile ./browser-host.py;
}

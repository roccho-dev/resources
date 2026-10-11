# First executable closure step; NOT full pre-apply acceptance.
# Exact package set selected by ops #426, without unrelated private flake inputs.
let
  pkgs = import ./pkgs.nix;
  bcon = pkgs.callPackage ../nixos/bcon.nix { };
  fixture = pkgs.writeText "browser-host-page.html" (builtins.readFile ./page.html);
  remote = { ... }: {
    environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.procps pkgs.python3 ];
    virtualisation.memorySize = 512;
  };
in pkgs.testers.runNixOSTest {
  name = "browser-host-session";
  globalTimeout = 300;
  extraPythonPackages = p: [ p.pillow ];
  nodes = {
    browser = { ... }: {
      imports = [ ../nixos/browser-host.nix ];
      services.browserHost = { enable = true; initialUrl = "file://${fixture}"; };
      virtualisation.memorySize = 2048;
      environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.kbd pkgs.procps
        (pkgs.python3.withPackages (p: [ p.websocket-client ])) ];
      hardware.graphics.enable = true;
      services.dbus.enable = true;
      fonts.packages = [ pkgs.noto-fonts pkgs.noto-fonts-cjk-sans ];
      # Only GPU emulation differs from the Host module's terminal service.
      systemd.services.browser-host-terminal.environment.LIBGL_ALWAYS_SOFTWARE = "1";
      services.openssh.enable = true;
      # Disposable VM network only; no production credentials.
      services.openssh.settings.PermitRootLogin = "prohibit-password";
    };
    remoteA = remote;
    remoteB = remote;
  };
  testScript = builtins.readFile ./browser-host.py;
}

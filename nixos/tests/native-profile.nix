{ pkgs }:
{
  name = "own-native-profile-boundary";
  nodes.machine = { ... }: {
    environment.systemPackages = [ pkgs.bash ];
    system.stateVersion = "26.05";
  };
  testScript = ''
    machine.start()
    machine.wait_for_unit("multi-user.target")
    machine.succeed("install -d /run/profile-test; cp ${../own-native-profile.sh} /run/profile-test/select")
    # Stop at build: crossing the guard is tested without changing any profile or fetching a source.
    machine.succeed("printf '#!/bin/sh\\ntouch /run/profile-test/build-called\\nexit 73\\n' > /run/profile-test/nix; chmod +x /run/profile-test/nix")
    machine.succeed("printf '#!/bin/sh\\ntouch /run/profile-test/set-called\\nexit 74\\n' > /run/profile-test/nix-env; chmod +x /run/profile-test/nix-env")
    selector = "PATH=/run/profile-test:/run/current-system/sw/bin bash /run/profile-test/select " + "0" * 40
    status, _ = machine.execute(selector)
    assert status == 73, "native NixOS VM must reach standard Nix build"
    machine.succeed("test -f /run/profile-test/build-called; unlink /run/profile-test/build-called")
    machine.fail("test -e /run/profile-test/set-called")
    # Simulate a detected container and a failed detector; both must stop before the build sentinel.
    for detector_status in (0, 2):
        machine.succeed(f"printf '#!/bin/sh\\nexit {detector_status}\\n' > /run/profile-test/systemd-detect-virt; chmod +x /run/profile-test/systemd-detect-virt")
        status, _ = machine.execute(selector)
        assert status == 2, "container or unknown detection must be refused"
        machine.fail("test -e /run/profile-test/build-called")
        machine.fail("test -e /run/profile-test/set-called")
    machine.fail("test -e /nix/var/nix/profiles/own-dev")
  '';
}

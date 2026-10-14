{ pkgs
, ownModule
, extendedImage
, extendedImageName
, codexVersion
, nativeProfile
, nativeProfileNext
}:
{
  name = "versapro-own-oci";

  nodes.machine =
    { config, lib, pkgs, ... }:
    let
      evaluatedExecStartPre =
        config.systemd.services.docker-versapro-own-oci.serviceConfig.ExecStartPre;
    in
    {
      imports = [ ownModule ];

      assertions = [
        {
          assertion =
            builtins.length evaluatedExecStartPre == 2
            && lib.hasSuffix "/bin/pre-start" (toString (builtins.elemAt evaluatedExecStartPre 0))
            && lib.hasInfix "versapro-own-oci-seed" (toString (builtins.elemAt evaluatedExecStartPre 1));
          message = "the evaluated standard OCI unit must load imageFile before the own seed";
        }
      ];

      services.versaproOwnOci = {
        enable = true;
        authorizedKeyFile = "/run/versapro-own-oci-test/authorized-key.env";
      };

      environment.systemPackages = [ pkgs.openssh pkgs.jq ];
      virtualisation.memorySize = 4096;
      virtualisation.diskSize = 32768;
      virtualisation.cores = 2;

      systemd.services.versapro-own-oci-test-key = {
        description = "Generate the VM-only own OCI SSH key";
        before = [ "docker-versapro-own-oci.service" ];
        path = [ pkgs.coreutils pkgs.openssh ];
        serviceConfig.Type = "oneshot";
        script = ''
          set -eu
          dir=/run/versapro-own-oci-test
          install -d -m 700 "$dir"
          if [ ! -s "$dir/id_ed25519" ]; then
            ssh-keygen -q -t ed25519 -N "" -f "$dir/id_ed25519"
          fi
          pub=$(cut -d' ' -f1,2 "$dir/id_ed25519.pub")
          printf 'OWN_AUTHORIZED_KEY=%s\n' "$pub" > "$dir/authorized-key.env"
          chmod 600 "$dir/authorized-key.env"
        '';
      };

      systemd.services.docker-versapro-own-oci = {
        requires = [ "versapro-own-oci-test-key.service" ];
        after = [ "versapro-own-oci-test-key.service" ];
      };

      specialisation.extended.configuration.services.versaproOwnOci = {
        imageFile = lib.mkForce extendedImage;
        imageName = lib.mkForce extendedImageName;
      };
    };

  # The same host platform without any OCI module: Native T is a separate root-owned
  # Nix profile, not part of system.build.toplevel or an obligatory OCI wrapper.
  nodes.native = { pkgs, ... }: {
    virtualisation.memorySize = 1024;
    virtualisation.diskSize = 8192;
    virtualisation.cores = 1;
    virtualisation.writableStore = true;
    virtualisation.additionalPaths = [ nativeProfile nativeProfileNext ];
    environment.systemPackages = [ pkgs.nix ];
  };

  testScript = ''
    import shlex
    import time

    machine.start()
    machine.wait_for_unit("docker-versapro-own-oci.service")
    machine.wait_for_open_port(2223)

    key_dir = "/run/versapro-own-oci-test"
    known_hosts = f"{key_dir}/known_hosts"
    ssh_base = (
        f"ssh -F /dev/null -p 2223 -i {key_dir}/id_ed25519 "
        "-o IdentitiesOnly=yes -o BatchMode=yes -o StrictHostKeyChecking=yes "
        f"-o GlobalKnownHostsFile=/dev/null -o UserKnownHostsFile={known_hosts} "
        "dev@127.0.0.1"
    )

    def strict(command):
        return f"set -eu; {command}"

    def machine_succeed(command):
        return machine.succeed(strict(command))

    def machine_fails(command):
        return machine.fail(strict(command))

    def pin_host_key():
        machine_succeed(
            "pub=$(docker exec versapro-own-oci cat /home/dev/.ssh/ssh_host_ed25519_key.pub); "
            f"printf '[127.0.0.1]:2223 %s\\n' \"$(printf '%s\\n' \"$pub\" | cut -d' ' -f1,2)\" > {known_hosts}"
        )

    def ssh(command):
        return machine.succeed(f"{ssh_base} {shlex.quote(strict(command))}")

    def ssh_fails(command):
        return machine.fail(f"{ssh_base} {shlex.quote(strict(command))}")

    def ssh_ready():
        # The TCP port and systemd unit may precede sshd in a newly loaded OCI.
        # Retry only a strict read-only probe, never repeat a switch or effect.
        for _ in range(45):
            status, _out = machine.execute(f"{ssh_base} true", check_return=False)
            if status == 0:
                return
            time.sleep(1)
        raise AssertionError("own OCI SSH was not actually ready")

    pin_host_key()
    ssh_ready()

    # Prove an earlier failed SSH assertion cannot be hidden by a later success.
    ssh_fails('test "$(id -u)" = 9999; test "$HOME" = /home/dev')

    ssh('test "$(id -u)" = 1000; test "$HOME" = /home/dev; test "$NIX_REMOTE" = daemon')
    ssh('test "$(codex --version)" = "codex-cli ${codexVersion}"; ! command -v hello')
    ssh("nix store ping --store daemon >/dev/null; ! touch /nix/store/dev-write")

    mount_probe = (
        "mounts=$(docker inspect --format '{{range .Mounts}}{{println .Name .Destination .RW}}{{end}}' versapro-own-oci); "
        "test \"$(printf '%s\\n' \"$mounts\" | sed '/^$/d' | wc -l)\" = 3; "
        "grep -qx 'versapro-own-oci-home /home/dev true' <<<\"$mounts\"; "
        "grep -qx 'versapro-own-oci-work /work/repos true' <<<\"$mounts\"; "
        "grep -qx 'versapro-own-oci-nix /nix true' <<<\"$mounts\""
    )
    machine_succeed(mount_probe)

    # Prove a wrong earlier mount assertion cannot be hidden by a correct last one.
    machine_fails(
        "mounts=$(docker inspect --format '{{range .Mounts}}{{println .Name .Destination .RW}}{{end}}' versapro-own-oci); "
        "grep -qx 'wrong-home /home/dev true' <<<\"$mounts\"; "
        "grep -qx 'versapro-own-oci-nix /nix true' <<<\"$mounts\""
    )

    ssh("echo home > ~/.own-oci-home; mkdir -p /work/repos/own-oci-test; echo work > /work/repos/own-oci-test/marker")
    before_id = machine.succeed("docker inspect -f '{{.Id}}' versapro-own-oci").strip()
    before_key = machine.succeed("docker exec versapro-own-oci cat /home/dev/.ssh/ssh_host_ed25519_key.pub").strip()
    before_profile = ssh("readlink /nix/var/nix/profiles/own-dev").strip()

    machine.succeed("systemctl restart docker-versapro-own-oci.service")
    machine.wait_for_unit("docker-versapro-own-oci.service")
    machine.wait_for_open_port(2223)
    after_restart_id = machine.succeed("docker inspect -f '{{.Id}}' versapro-own-oci").strip()
    assert after_restart_id != before_id
    pin_host_key()
    ssh_ready()
    ssh('test "$(cat ~/.own-oci-home)" = home; test "$(cat /work/repos/own-oci-test/marker)" = work')
    assert machine.succeed("docker exec versapro-own-oci cat /home/dev/.ssh/ssh_host_ed25519_key.pub").strip() == before_key

    machine.succeed("systemctl stop docker-versapro-own-oci.service")
    machine.succeed("/run/current-system/specialisation/extended/bin/switch-to-configuration test")
    machine.succeed("systemctl start docker-versapro-own-oci.service")
    machine.wait_for_unit("docker-versapro-own-oci.service")
    machine.wait_for_open_port(2223)
    extended_id = machine.succeed("docker inspect -f '{{.Id}}' versapro-own-oci").strip()
    assert extended_id != after_restart_id
    pin_host_key()
    ssh_ready()
    ssh('test "$(cat ~/.own-oci-home)" = home; test "$(cat /work/repos/own-oci-test/marker)" = work')
    ssh('test "$(codex --version)" = "codex-cli ${codexVersion}"; hello >/dev/null')
    assert machine.succeed("docker exec versapro-own-oci cat /home/dev/.ssh/ssh_host_ed25519_key.pub").strip() == before_key
    after_profile = ssh("readlink /nix/var/nix/profiles/own-dev").strip()
    assert after_profile != before_profile

    # Synthetic Native-only VM: independent T generations without a NixOS switch or OCI.
    # The profile closures are injected solely into this disposable VM store; no auth is read.
    existing_oci_image = machine.succeed("docker inspect -f '{{.Image}}' versapro-own-oci").strip()
    native.start()
    native.wait_for_unit("multi-user.target")
    before_system = native.succeed("readlink -f /run/current-system").strip()
    native.succeed("! systemctl list-unit-files | grep -q docker-versapro-own-oci")
    native.succeed("! command -v docker; ! test -e /run/current-system/sw/bin/codex")
    native.succeed("test -x ${nativeProfile}/bin/codex; test -x ${nativeProfileNext}/bin/codex")
    native.succeed("test ! -e ${nativeProfile}/bin/hello; test -x ${nativeProfileNext}/bin/hello")

    p = "/nix/var/nix/profiles/host-native-tool"
    native.succeed(f"nix-env --profile {p} --set ${nativeProfile}")
    native.succeed(f'test "$(readlink -f {p})" = "${nativeProfile}"')
    native.succeed(f'test "$({p}/bin/codex --version)" = "codex-cli ${codexVersion}"')
    generation0 = native.succeed(f"readlink {p}").strip()
    native.succeed(f"nix-env --profile {p} --set ${nativeProfileNext}")
    native.succeed(f'test "$(readlink -f {p})" = "${nativeProfileNext}"; {p}/bin/hello >/dev/null')
    generation1 = native.succeed(f"readlink {p}").strip()
    assert generation1 != generation0

    native.succeed(f"nix-env --profile {p} --rollback")
    native.succeed(f'test "$(readlink {p})" = "{generation0}"; ! test -e {p}/bin/hello')
    native.succeed(f"nix-env --profile {p} --set ${nativeProfileNext}")
    native.succeed(f"nix-store --check-validity ${nativeProfileNext}; test -x {p}/bin/hello")
    native.succeed(f'test "$(readlink -f /run/current-system)" = "{before_system}"')
    # Native profile selection must not replace this other VM node's fixed OCI.
    assert machine.succeed("docker inspect -f '{{.Image}}' versapro-own-oci").strip() == existing_oci_image
    native.shutdown()
  '';
}

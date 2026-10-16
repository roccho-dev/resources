{ nixpkgs ? builtins.fetchTarball {
    url = "https://codeload.github.com/NixOS/nixpkgs/tar.gz/2efa67fd26b6df417c33e4603185c701f260dd83";
  }, legacyBiosOnly ? false
}:
let
  system = import (nixpkgs + "/nixos") {
    system = "x86_64-linux";
    configuration = { lib, ... }: {
      imports = [
        (nixpkgs + "/nixos/modules/installer/cd-dvd/installation-cd-minimal.nix")
      ];

      # Isolate legacy BIOS compatibility without changing the SSH/network requirements.
      isoImage.makeEfiBootable = lib.mkForce (!legacyBiosOnly);

      networking.hostName = "versapro-installer";
      networking.networkmanager.enable = true;
      networking.networkmanager.ensureProfiles = {
        environmentFiles = [ "/run/bootstrap/wifi.env" ];
        profiles.bootstrap-wifi = {
          connection = {
            id = "bootstrap-wifi";
            type = "wifi";
            autoconnect = true;
          };
          wifi = {
            mode = "infrastructure";
            ssid = "$BOOT_WIFI_SSID";
          };
          wifi-security = {
            key-mgmt = "wpa-psk";
            psk = "$BOOT_WIFI_PSK";
          };
          ipv4.method = "auto";
          ipv6.method = "auto";
        };
      };

      # This partition is prepared separately; credentials never enter the Nix store.
      fileSystems = lib.mkImageMediaOverride {
        "/run/bootstrap" = {
          device = "/dev/disk/by-label/NIXOSCONF";
          fsType = "vfat";
          # The read-only bootstrap must not fsck the raw partition claimed by the live ISO.
          noCheck = true;
          # The live ISO claims the whole USB disk; a read-only loop avoids that claim.
          options = [ "ro" "loop" "nosuid" "nodev" "noexec" "umask=0077" "nofail" "x-systemd.device-timeout=15s" ];
        };
      };
      systemd.services.NetworkManager-ensure-profiles = {
        after = [ "run-bootstrap.mount" ];
        wants = [ "run-bootstrap.mount" ];
        unitConfig.ConditionPathExists = "/run/bootstrap/wifi.env";
      };

      hardware.enableRedistributableFirmware = true;
      boot.kernelModules = [ "rtl8xxxu" ];
      services.openssh = {
        enable = true;
        generateHostKeys = false;
        settings = {
          PasswordAuthentication = false;
          KbdInteractiveAuthentication = false;
          PermitRootLogin = "prohibit-password";
        };
        # A dedicated bootstrap host identity enables strict host-key checking.
        hostKeys = [ { path = "/run/bootstrap/ssh_host_ed25519_key"; type = "ed25519"; } ];
      };
      systemd.services.sshd = {
        after = [ "run-bootstrap.mount" ];
        requires = [ "run-bootstrap.mount" ];
        unitConfig.ConditionPathExists = "/run/bootstrap/ssh_host_ed25519_key";
      };
      users.users.root.openssh.authorizedKeys.keys = [
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIf3e6NN1SmMo0PxHFRLADSY4fG3wSv6kEhA5Yq57I1l windows-own"
      ];

      boot.loader.timeout = lib.mkForce 3;
      image.baseName = lib.mkForce "versapro-ssh-installer";
      image.fileName = lib.mkForce "versapro-ssh-installer.iso";
      isoImage.squashfsCompression = "zstd -Xcompression-level 6";
      system.stateVersion = "26.05";
    };
  };
in
system.config.system.build.isoImage

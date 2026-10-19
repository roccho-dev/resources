# ownCore: the own Core (git, the gh wrapper and its credential helper, nix), from nixos/default.nix.
{ ownCore, ... }:
let
  # The one declared management key (root here, the own OCI's SSH entry, and the native dev user).
  managementKey = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIf3e6NN1SmMo0PxHFRLADSY4fG3wSv6kEhA5Yq57I1l windows-own";
in
{
  networking.hostName = "versapro";
  networking.useDHCP = false;
  networking.networkmanager.enable = true;

  # Observed storage/USB modules; the root remains on the internal SATA SSD.
  boot.initrd.availableKernelModules = [
    "ehci_pci" "ahci" "usb_storage" "sd_mod" "sr_mod"
  ];
  hardware.enableRedistributableFirmware = true;
  hardware.cpu.intel.updateMicrocode = true;

  boot.loader.grub = {
    enable = true;
    efiSupport = false;
    device = "/dev/disk/by-id/ata-SSD_240G_1804BQ0831CWM370";
  };
  fileSystems."/" = {
    device = "/dev/disk/by-label/NIXOS_ROOT";
    fsType = "ext4";
  };
  swapDevices = [ ];

  services.openssh = {
    enable = true;
    generateHostKeys = true;
    hostKeys = [
      { path = "/etc/ssh/ssh_host_ed25519_key"; type = "ed25519"; }
    ];
    settings = {
      PasswordAuthentication = false;
      KbdInteractiveAuthentication = false;
      PermitRootLogin = "prohibit-password";
    };
  };
  users.users.root.openssh.authorizedKeys.keys = [ managementKey ];

  # Native own (#72, oci-own = native). B declares the development user, its repository root, the own Core (the
  # same Core the own OCI's B carries) and where the selected T is found. B never contains or selects a Tool: T is
  # the own tool profile, set by root as the native generation /nix/var/nix/profiles/own-dev
  # (nixos/own-native-profile.sh), where the Core's gh wrapper finds its credential helper.
  users.users.dev = {
    isNormalUser = true;
    description = "own development user";
    openssh.authorizedKeys.keys = [ managementKey ];
    packages = [ ownCore ];
  };
  # Repositories and each principal's gh slot (/work/repos/.auth/<principal>/gh), as in the own OCI.
  systemd.tmpfiles.rules = [
    "d /work 0755 root root -"
    "d /work/repos 0755 dev users -"
  ];
  environment.profiles = [ "/nix/var/nix/profiles/own-dev" ];
  # The host's nix-daemon serves dev's builds; flakes for the pinned resources outputs.
  nix.settings.experimental-features = [ "nix-command" "flakes" ];

  # Wi-Fi profile and generated host private key stay in standard target-private files.
  # No installer module, USB host key, secret provisioning framework or future workload.
  system.stateVersion = "26.05";
}

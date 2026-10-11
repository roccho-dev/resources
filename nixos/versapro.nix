{ ... }:
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
  users.users.root.openssh.authorizedKeys.keys = [
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIf3e6NN1SmMo0PxHFRLADSY4fG3wSv6kEhA5Yq57I1l windows-own"
  ];

  # Wi-Fi profile and generated host private key stay in standard target-private files.
  # No installer module, USB host key, secret provisioning framework or future workload.
  system.stateVersion = "26.05";
}

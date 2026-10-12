{ defaultImage
, defaultImageName
, containerName ? "versapro-own-oci"
}:
{ config, lib, pkgs, ... }:
let
  cfg = config.services.versaproOwnOci;
  serviceName = "docker-${containerName}";
  homeVolume = "${containerName}-home";
  workVolume = "${containerName}-work";
  nixVolume = "${containerName}-nix";
  rootKeys = config.users.users.root.openssh.authorizedKeys.keys;
  fallbackAuthorizedKey =
    if cfg.authorizedKey != null then cfg.authorizedKey
    else if cfg.authorizedKeyFile == null && builtins.length rootKeys == 1 then builtins.head rootKeys
    else null;
  docker = config.virtualisation.docker.package;
  seed = pkgs.writeShellScript "${containerName}-seed" ''
    set -eu
    for volume in ${homeVolume} ${workVolume} ${nixVolume}; do
      if ! ${docker}/bin/docker volume inspect "$volume" >/dev/null 2>&1; then
        ${docker}/bin/docker volume create "$volume" >/dev/null
      fi
    done
    ${docker}/bin/docker run --rm \
      --mount=type=volume,source=${nixVolume},target=/seed,volume-nocopy \
      --env OWN_NIX_VOLUME=${nixVolume} \
      ${lib.escapeShellArg cfg.imageName} \
      /bin/own-nix-seed
  '';
in
{
  options.services.versaproOwnOci = {
    enable = lib.mkEnableOption "the fixed own OCI on VersaPro";

    imageFile = lib.mkOption {
      type = lib.types.pathInStore;
      default = defaultImage;
      description = "Fixed production own OCI archive.";
    };

    imageName = lib.mkOption {
      type = lib.types.str;
      default = defaultImageName;
      description = "Name and tag contained in imageFile.";
    };

    authorizedKey = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Public management key; defaults to the one declared root management key.";
    };

    authorizedKeyFile = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "Optional runtime systemd EnvironmentFile containing OWN_AUTHORIZED_KEY.";
    };
  };

  config = lib.mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.authorizedKeyFile != null || fallbackAuthorizedKey != null;
        message = "versapro own OCI needs one public management key or an authorizedKeyFile";
      }
      {
        assertion = !(cfg.authorizedKey != null && cfg.authorizedKeyFile != null);
        message = "set only one of authorizedKey and authorizedKeyFile";
      }
    ];

    virtualisation.docker.enable = true;
    virtualisation.oci-containers.backend = "docker";
    virtualisation.oci-containers.containers.${containerName} = {
      image = cfg.imageName;
      imageFile = cfg.imageFile;
      pull = "never";
      ports = [ "127.0.0.1:2223:2223" ];
      volumes = [
        "${homeVolume}:/home/dev"
        "${workVolume}:/work/repos"
      ];
      environment = {
        OWN_HOME_VOLUME = homeVolume;
        OWN_WORK_VOLUME = workVolume;
        OWN_NIX_VOLUME = nixVolume;
      };
      extraOptions = [
        "--mount=type=volume,source=${nixVolume},target=/nix,volume-nocopy"
        "--shm-size=1G"
        "--env=OWN_AUTHORIZED_KEY"
      ];
      autoRemoveOnStop = true;
    };

    # Keep the standard oci-containers imageFile loader as the first
    # ExecStartPre, then seed the production /nix volume before container run.
    systemd.services.${serviceName} = {
      environment = lib.optionalAttrs (fallbackAuthorizedKey != null) {
        OWN_AUTHORIZED_KEY = fallbackAuthorizedKey;
      };
      serviceConfig = {
        EnvironmentFile = lib.optional (cfg.authorizedKeyFile != null) cfg.authorizedKeyFile;
        ExecStartPre = lib.mkAfter [ seed ];
      };
    };
  };
}

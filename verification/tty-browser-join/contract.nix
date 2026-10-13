# This validates C's input shape, not upstream agreement, test success or trust.
let
  names = [ "A" "B" "terminal" ];
  valid = value:
    builtins.isAttrs value
    && builtins.isString (value.rev or null)
    && builtins.match "[0-9a-f]{40}" value.rev != null
    && builtins.isString (value.narHash or null)
    && builtins.match "sha256-[A-Za-z0-9+/]{43}=" value.narHash != null
    && builtins.isAttrs (value.package or null)
    && (value.package.type or null) == "derivation"
    && (value.package.system or null) == "x86_64-linux";
  inspect = supplied:
    if !builtins.isAttrs supplied then {
      state = "INVALID_UPSTREAM_INPUT"; missing = []; invalid = [ "suppliers" ];
    } else let
      missing = builtins.filter (name: (supplied.${name} or null) == null) names;
      invalid = builtins.filter (name:
        (supplied.${name} or null) != null && !valid supplied.${name}
      ) names;
      extra = builtins.filter (name: !builtins.elem name names) (builtins.attrNames supplied);
    in {
      inherit missing;
      invalid = invalid ++ extra;
      state = if invalid != [] || extra != [] then "INVALID_UPSTREAM_INPUT"
        else if missing != [] then "WAITING_UPSTREAM_EXPORTS"
        else "INPUT_SHAPE_VALID_NOT_E2E";
    };
in {
  inherit inspect;
  require = supplied:
    let result = inspect supplied;
    in if result.state == "INPUT_SHAPE_VALID_NOT_E2E" then supplied
      else throw ("C intake: " + builtins.toJSON result);
}

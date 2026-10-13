# Synthetic values test intake rejection only. They are never built or E2E evidence.
let
  contract = import ./contract.nix;
  item = {
    rev = "1111111111111111111111111111111111111111";
    narHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
    package = { type = "derivation"; system = "x86_64-linux"; };
  };
  all = { A = item; B = item; terminal = item; };
  state = supplied: (contract.inspect supplied).state;
  invalid = supplied: state supplied == "INVALID_UPSTREAM_INPUT";
  tests = {
    missing_all = (contract.inspect {}).missing == [ "A" "B" "terminal" ];
    missing_A = (contract.inspect (all // { A = null; })).missing == [ "A" ];
    missing_B = (contract.inspect (all // { B = null; })).missing == [ "B" ];
    missing_terminal = (contract.inspect (all // { terminal = null; })).missing == [ "terminal" ];
    mutable_ref = invalid (all // { A = item // { rev = "main"; }; });
    absent_hash = invalid (all // { B = builtins.removeAttrs item [ "narHash" ]; });
    bad_hash = invalid (all // { B = item // { narHash = "unknown"; }; });
    local_path = invalid (all // { B = item // { package = "/tmp/build"; }; });
    wrong_system = invalid (all // { B = item // { package = item.package // { system = "aarch64-linux"; }; }; });
    wrong_kind = invalid (all // { A = item // { package = item.package // { type = "fixture"; }; }; });
    unknown_input = invalid (all // { X = item; });
    non_object = invalid [];
    valid_shape_is_not_e2e = state all == "INPUT_SHAPE_VALID_NOT_E2E";
    pending_is_not_ready = state { A = item; } == "WAITING_UPSTREAM_EXPORTS";
    missing_is_rejected = !(builtins.tryEval (contract.require {})).success;
    invalid_is_rejected = !(builtins.tryEval (contract.require (all // { A = "stub"; }))).success;
  };
  failed = builtins.filter (name: !tests.${name}) (builtins.attrNames tests);
in assert failed == []; {
  gate = "C_INTAKE_UNIT_ONLY";
  cases = builtins.length (builtins.attrNames tests);
  inherit failed;
  upstream = (contract.inspect (import ./suppliers.nix)).state;
  e2e = "NOT_RUN";
  upstreamAgreement = "NOT_CLAIMED";
}

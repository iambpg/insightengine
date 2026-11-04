"""MAC identity and capwap words, including the labels on a controller that predates PR #37."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ie_config.ap_status import (  # noqa: E402
    AP_FRESH_SECONDS,
    ap_identity,
    canon_mac,
    capwap_state,
    finish_ap_status,
    interpret_oper_text,
    looks_like_mac,
    sample_fresh,
)


def test_hostname_is_not_a_mac_and_the_key_mac_canonicalises():
    assert not looks_like_mac("AP0035.1a09.5274")
    assert canon_mac("00:c8:8b:c1:7e:90") == "00:c8:8b:c1:7e:90"
    assert canon_mac("00c8.8bc1.7e90") == "00:c8:8b:c1:7e:90"
    assert canon_mac("0.200.139.193.126.144") == "00:c8:8b:c1:7e:90"
    name, mac, wlc, _site = ap_identity({
        "ap": "00:c8:8b:c1:7e:90",
        "ap_name": "00:c8:8b:c1:7e:90",
        "mac": "00:c8:8b:c1:7e:90",
        "ip": "10.1.1.1",
        "wlc": "OiOB-Bree-WLC01",
        "source": "OiOB-Bree-WLC01",
    })
    assert name == ""
    assert mac == "00:c8:8b:c1:7e:90"
    assert wlc == "OiOB-Bree-WLC01"


def test_capwap_enum_and_freshness_window():
    assert interpret_oper_text("ewlc-ap-state-registered") == "up"
    assert interpret_oper_text("ewlc_ap_state_registered") == "up"
    assert interpret_oper_text("ap-up") == "up"
    assert interpret_oper_text("run") == "up"
    assert interpret_oper_text("associated") == "up"
    assert interpret_oper_text("ewlc-ap-state-deregistered") == "down"
    assert capwap_state({"ap_state/ap_operation_state": "ewlc-ap-state-registered"}) == "up"
    assert finish_ap_status(None, True) == "up"
    assert finish_ap_status("down", True) == "down"
    assert finish_ap_status(None, False) == "down"
    now = 1_000_000.0
    assert sample_fresh({"value": [now - 60, "1"]}, now)
    assert not sample_fresh({"value": [now - AP_FRESH_SECONDS - 1, "1"]}, now)
    assert sample_fresh({"value": [now, "1"]}, now)

"""DNS suffix stripping and Netdisco/NetBox name matching."""

from ie_config.fleet import _match_record
from ie_config.hostnames import domain_suffix_yaml, names_match, parse_suffixes, strip_device_label, strip_hostname


def test_strip_keeps_internal_dots_and_is_case_insensitive():
    suffixes = parse_suffixes(".pnp.co.za, example.net")
    assert suffixes == [".pnp.co.za", ".example.net"]
    assert strip_hostname("wc18.cc30-claremont-1rsw01.pnp.co.za", suffixes) == "wc18.cc30-claremont-1rsw01"
    both = parse_suffixes(".pnp.co.za, .verginactive.co.za, .virginactive.co.za")
    assert strip_hostname("wc00-kenilworth-asw01.pnp.co.za", both) == "wc00-kenilworth-asw01"
    assert strip_hostname("wc00-kenilworth-asw01.verginactive.co.za", both) == "wc00-kenilworth-asw01"
    assert strip_hostname("wc00-kenilworth-asw01.virginactive.co.za", both) == "wc00-kenilworth-asw01"
    assert strip_hostname("wc18.cc30-claremont-1rsw01.pnp.co.za", both) == "wc18.cc30-claremont-1rsw01"
    assert strip_hostname("WC18.cc30-claremont-1rsw01.PNP.CO.ZA", suffixes) == "WC18.cc30-claremont-1rsw01"
    assert strip_hostname("wc18.cc30-claremont-1rsw01", suffixes) == "wc18.cc30-claremont-1rsw01"
    assert strip_hostname("other.example.net", suffixes) == "other"
    # a suffix in the middle is left alone
    assert strip_hostname("not.pnp.co.za.extra", suffixes) == "not.pnp.co.za.extra"
    assert strip_hostname("", suffixes) == ""


def test_cdp_device_id_drops_suffix_and_trailing_serial():
    suffixes = [".pnp.co.za"]
    assert strip_device_label("wc18.cc30-claremont-1rsw01.pnp.co.za (FOC1234ABCD)", suffixes) == "wc18.cc30-claremont-1rsw01"
    assert strip_device_label("wc18.cc30-claremont-1rsw01 (FOC1234ABCD).pnp.co.za", suffixes) == "wc18.cc30-claremont-1rsw01"
    assert strip_device_label("switch01(FOC999)", suffixes) == "switch01"


def test_name_match_uses_stripped_forms():
    suffixes = [".pnp.co.za"]
    assert names_match("wc18.cc30-claremont-1rsw01", "wc18.cc30-claremont-1rsw01.pnp.co.za", suffixes)
    assert not names_match("wc18.cc30-claremont-1rsw01", "other.pnp.co.za", suffixes)
    rows = [{"id": "4", "hostname": "wc18.cc30-claremont-1rsw01", "mgmtIp": "10.129.32.16"}]
    found = _match_record(rows, "wc18.cc30-claremont-1rsw01.pnp.co.za", name_key="hostname", ip_key="mgmtIp", suffixes=suffixes)
    assert found["id"] == "4"
    missed = _match_record(rows, "wc18.cc30-claremont-1rsw01.pnp.co.za", name_key="hostname", ip_key="mgmtIp", suffixes=[])
    assert missed is None


def test_domain_suffix_yaml_is_a_netdisco_list():
    text = domain_suffix_yaml([".pnp.co.za", ".example.net"])
    assert "domain_suffix:" in text
    assert "- '.pnp.co.za'" in text
    assert "- '.example.net'" in text
    assert domain_suffix_yaml([]) == ""

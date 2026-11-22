# Wireless normalizer.
# Per-client series are emitted only when the input tag wlc_role is missing
# or "clients" (telegraf-wlc-clients). telegraf-wlc sets wlc_role=ap and drops
# the client subscriptions so a client flood cannot fill its registry.
# Every numeric client leaf is kept. Labels on ie_wlc_client are only wlc,
# ap, ssid, band and the client MAC. Protocol, VLAN, mobility and free text
# are not labels. store_clients=0 (IE_WLC_STORE_CLIENTS=0) still drops the
# per-client series and keeps the per-AP/per-radio rollup.
# AireOS SNMP does not include a client list.
#
# `state` is the one global Telegraf lets the script mutate.

KEEP_NS = 180 * 1000000000
RESET_NS = 90 * 1000000000

CLIENT_NAMES = (
    "ie_wlc_client_raw",
    "ie_wlc_client_common",
    "ie_wlc_client_dot11",
    "ie_wlc_client_mobility",
    "ie_wlc_client_policy",
)
RADIO_NAMES = ("ie_wlc_rrm", "ie_wlc_rrm_slot", "ie_wlc_radio_mdt", "ie_wlc_radio_stats", "ie_wlc_ssid", "ie_wlc_ethernet", "ie_wlc_capwap_pkts")
AP_NAMES_IN = ("ie_wlc_ap_mdt", "ie_wlc_ap_name_map", "ie_wlc_ap_join", "ie_wlc_ap_history", "ie_wlc_ap_image_prepare", "ie_wlc_ap_image_predownload")
SDWAN_NAMES = ("ie_sdwan_bfd", "ie_sdwan_approute")

# Source leaf -> canonical field. Skipped on passthrough only when that
# canonical field was actually written, so a second counter is not dropped.
ALIAS_OF = {
    "most_recent_rssi": "rssi",
    "most_recent_snr": "snr",
    "cca_util_percentage": "channel_util",
    "rx_util_percentage": "channel_util",
    "bss_chan_util": "channel_util",
    "curr_freq": "channel",
    "current_channel": "channel",
    "curr_tx_power_in_dbm": "tx_power_dbm",
    "current_tx_power_level": "tx_power_level",
    "chan_width": "width",
    "channel_width": "width",
    "rogue_20_count": "rogue_neighbors",
    "five_minutes": "busy_percent",
    "noise_floor": "noise",
    "non_wifi_inter": "interference",
    "num_assoc_clients": "clients",
    "stations": "clients",
    "joined_aps_count": "joined_aps",
    "total_count": "aps",
    "malicious_count": "malicious",
    "friendly_count": "friendly",
}


def _clients_here(metric):
    # Unset keeps the unit tests on one process. The AP collector sets ap
    # and must not keep client series.
    if "wlc_role" not in metric.tags:
        return True
    return metric.tags["wlc_role"] == "clients"


def apply(metric):
    name = metric.name
    path = ""
    if "path" in metric.tags:
        path = metric.tags["path"]
    blob = (name + " " + path).lower()
    if "wireless-client-oper" in blob or name in CLIENT_NAMES or "traffic-stats" in blob or "common-oper-data" in blob or "dot11-oper-data" in blob:
        if not _clients_here(metric):
            return None
        # Client rows have no history list. Skip that scan; it walked every
        # leaf on every client and made the forward listener miss its deadline.
        state["history_drop"] = {}
        return client_metric(metric, blob)
    if name in RADIO_NAMES or "rrm-oper" in blob or "radio-oper" in blob or "ssid-counter" in blob or "ethernet-if" in blob or "capwap-pkts" in blob:
        state["history_drop"] = {}
        return radio_metric(metric, blob)
    # One pass decides which history-list index is newest. Lookups and
    # passthrough both skip the older copies.
    state["history_keep"] = history_keep(metric)
    if "cdp-cache" in blob or "lldp-neigh" in blob or name in ("ie_wlc_cdp_mdt", "ie_wlc_lldp_mdt", "ie_wlc_cdp"):
        return neighbor_metric(metric)
    if name in AP_NAMES_IN or "capwap-data" in blob or name in ("ie_wlc_ap_join", "ie_wlc_ap_history"):
        return ap_metric(metric)
    if "rogue-oper" in blob or name == "ie_wlc_rogue_mdt":
        return rogue_mdt(metric)
    if "ha-oper" in blob or "ha-infra" in blob or name == "ie_wlc_ha":
        return ha_metric(metric)
    if name == "ie_wlc_cpu" or "cpu-usage" in blob:
        return cpu_metric(metric)
    if name == "ie_wlc_memory" or "memory-statistic" in blob:
        return memory_metric(metric)
    if "wlan-global" in blob or "wlan-client-stats" in blob or name in ("ie_wlc_wlan_info", "ie_wlc_wlan_clients", "ie_wlc_wlan"):
        return wlan_metric(metric)
    if name in SDWAN_NAMES or "sdwan-oper" in blob or "app-route" in blob:
        return sdwan_metric(metric, blob)
    if name == "ie_wlc_ap":
        return snmp_ap(metric)
    if name == "ie_wlc_radio":
        return snmp_radio(metric)
    if name == "ie_wlc_noise":
        return snmp_noise(metric)
    if name == "ie_wlc_interference":
        return snmp_interference(metric)
    if name == "ie_wlc_rogue_raw":
        return snmp_rogue(metric)
    if name == "ie_wlc_join":
        return snmp_join(metric)
    if name in ("ie_wlc_env", "ie_wlc_platform", "ie_wlc_interface", "ie_wlc_hardware", "ie_wlc_mobility", "ie_wlc_ap_global_stats", "ie_wlc_join_count"):
        return controller_passthrough(metric)
    # Unknown subscriptions still keep their numbers. Strings and list indexes
    # are not copied onto the series, or one raw dial-out row becomes a new
    # Prometheus series for every timestamp and MAC.
    return sanitize(metric)


def buckets():
    if "buckets" not in state:
        state["buckets"] = {}
    return state["buckets"]


def ssid_buckets():
    if "ssid_buckets" not in state:
        state["ssid_buckets"] = {}
    return state["ssid_buckets"]


def ap_names():
    if "ap_names" not in state:
        state["ap_names"] = {}
    return state["ap_names"]


def remembered_ap(wlc, ap):
    # Radio oper often carries only the radio MAC. The AP name map, filled
    # from capwap and the name subscription, turns that MAC into the hostname.
    if not ap:
        return ""
    key = str(wlc) + "|" + str(ap)
    if key in ap_names():
        return ap_names()[key]
    return str(ap)


def mac_place():
    if "mac_place" not in state:
        state["mac_place"] = {}
    return state["mac_place"]


def noise_worst():
    if "noise_worst" not in state:
        state["noise_worst"] = {}
    return state["noise_worst"]


def inter_worst():
    if "inter_worst" not in state:
        state["inter_worst"] = {}
    return state["inter_worst"]


def rogue_seen():
    if "rogue_seen" not in state:
        state["rogue_seen"] = {}
    return state["rogue_seen"]


def maybe_reset(metric):
    now = metric.time
    previous = state["gather_time"] if "gather_time" in state else now
    if now - previous > RESET_NS or previous - now > RESET_NS:
        state["noise_worst"] = {}
        state["inter_worst"] = {}
        state["rogue_seen"] = {}
    state["gather_time"] = now


def client_metric(metric, blob):
    mac = tag_or_field(metric, ("ms_mac_address", "client_mac", "ms-mac-address", "client-mac", "ms-mac-addr", "mac"))
    if not mac and "index" in metric.tags:
        mac = metric.tags["index"]
    ap = tag_or_field(metric, ("ap_name", "ap-name"))
    radio = tag_or_field(metric, ("ms_ap_slot_id", "radio_slot_id", "radio", "slot_id", "ms-ap-slot-id", "radio-slot-id"))
    ssid = tag_or_field(metric, ("vap_ssid", "vap-ssid", "ssid", "wlan_profile", "wlan-profile"))
    band = tag_or_field(metric, ("radio_type", "radio-type", "ms_radio_type", "ms-radio-type", "current_active_band", "radio_band", "radio-band", "band"))
    protocol = tag_or_field(metric, ("ewlc_ms_phy_type", "ewlc-ms-phy-type", "protocol"))
    vlan = tag_or_field(metric, ("res_vlan_id", "res-vlan-id", "res_vlan_name", "res-vlan-name", "vlan"))
    mobility = tag_or_field(metric, ("mm_client_role", "mm-client-role", "mobility_state", "mobility-state"))
    wlc = who(metric)
    if not ap:
        mac_key = tag_or_field(metric, ("ap_mac", "wtp_mac", "wtp-mac", "ap-mac"))
        if mac_key and (wlc + "|" + str(mac_key)) in ap_names():
            ap = ap_names()[wlc + "|" + str(mac_key)]
        elif mac_key:
            ap = mac_key
    saved = None
    if mac and (wlc + "|" + str(mac)) in mac_place():
        saved = mac_place()[wlc + "|" + str(mac)]
    if mac and (not ap) and saved != None:
        ap = saved["ap"]
        if not radio:
            radio = saved["radio"]
    if saved != None:
        if not ssid:
            ssid = saved["ssid"]
        if not band:
            band = saved["band"]
        if not protocol:
            protocol = saved["protocol"]
        if not vlan:
            vlan = saved["vlan"]
        if not mobility:
            mobility = saved["mobility"]
    if mac:
        mac_place()[wlc + "|" + str(mac)] = {
            "ap": str(ap) if ap else "",
            "radio": str(radio) if radio else "0",
            "ssid": str(ssid) if ssid else "",
            "band": str(band) if band else "",
            "protocol": str(protocol) if protocol else "",
            "vlan": str(vlan) if vlan != None else "",
            "mobility": str(mobility) if mobility else "",
        }
    if not ap:
        ap = "unknown"
    if not radio:
        radio = "0"
    rssi = num(tag_or_field(metric, ("most_recent_rssi", "rssi", "most-recent-rssi", "ewlc_ms_rssi")))
    snr = num(tag_or_field(metric, ("most_recent_snr", "snr", "most-recent-snr")))
    bytes_rx = num(tag_or_field(metric, ("bytes_rx", "bytes-rx")))
    bytes_tx = num(tag_or_field(metric, ("bytes_tx", "bytes-tx")))
    tx_retries = num(tag_or_field(metric, ("tx_retries", "tx-retries", "data_retries", "data-retries")))
    rts_retries = num(tag_or_field(metric, ("rts_retries", "rts-retries")))
    # current-rate is a string (Mbps, often "72.2"; sometimes an MCS token
    # such as "m9"). num() only accepts a pure number, then speed (uint32).
    current_rate = first_num(metric, ("current_rate", "current-rate", "speed"))
    site = metric.tags["site"] if "site" in metric.tags else ""
    key = wlc + "|" + site + "|" + str(ap) + "|" + str(radio)
    if key not in buckets():
        buckets()[key] = {}
    bucket = buckets()[key]
    ident = str(mac) if mac else str(len(bucket))
    prev = bucket[ident] if ident in bucket else (None, None, 0)
    now = metric.time
    if rssi == None:
        rssi = prev[0]
    if snr == None:
        snr = prev[1]
    detail_only = rssi == None and snr == None and bytes_rx == None and bytes_tx == None
    identity_only = detail_only and ("common-oper" in blob or "policy-data" in blob or ("mobility-oper-data" in blob and "wireless-client" in blob))
    if identity_only:
        bucket[ident] = (prev[0], prev[1], now)
        # IE_WLC_STORE_CLIENTS=0 still drops the per-client series.
        if not store_clients(metric) or not mac:
            return None
        return emit_client(metric, ap, radio, mac, ssid, band, protocol, vlan, mobility, rssi, snr, bytes_rx, bytes_tx, tx_retries, rts_retries, current_rate, now)
    bucket[ident] = (rssi, snr, now)
    drop_old(bucket, now)
    agg = Metric("ie_wlc_client_radio")
    copy_place(metric, agg)
    agg.tags["ap"] = str(ap)
    agg.tags["radio"] = str(radio)
    if band:
        agg.tags["band"] = str(band)
    stats = summarize(bucket)
    agg.fields["clients"] = stats[0]
    if stats[1] != None:
        agg.fields["rssi_avg"] = stats[1]
        agg.fields["rssi_min"] = stats[2]
    if stats[3] != None:
        agg.fields["snr_avg"] = stats[3]
        agg.fields["snr_min"] = stats[4]
    agg.time = now
    out = [agg]
    if ssid:
        skey = key + "|" + str(ssid)
        if skey not in ssid_buckets():
            ssid_buckets()[skey] = {}
        ssid_buckets()[skey][ident] = now
        drop_old_simple(ssid_buckets()[skey], now)
        ss = Metric("ie_wlc_ssid")
        copy_place(metric, ss)
        ss.tags["ap"] = str(ap)
        ss.tags["radio"] = str(radio)
        ss.tags["ssid"] = str(ssid)
        if band:
            ss.tags["band"] = str(band)
        ss.fields["clients"] = len(ssid_buckets()[skey])
        ss.time = now
        out.append(ss)
    if store_clients(metric) and mac and not detail_only:
        out.append(emit_client(metric, ap, radio, mac, ssid, band, protocol, vlan, mobility, rssi, snr, bytes_rx, bytes_tx, tx_retries, rts_retries, current_rate, now))
    if len(out) == 1:
        return out[0]
    return out


def radio_metric(metric, blob):
    # One walk. tag_or_field scans every leaf, and a radio row called it
    # about fifteen times. That scan is what pinned the radio listener.
    idx = leaf_index(metric)
    ap = _pick(idx, ("ap_name", "wtp_mac", "name", "ap-name", "wtp-mac"))
    radio = _pick(idx, ("radio_slot_id", "radio", "slot_id", "radio-slot-id", "slot-id"))
    wlc = who(metric)
    if ap:
        remembered = remembered_ap(wlc, ap)
        if remembered:
            ap = remembered
    if not ap:
        ap = "unknown"
    if not radio:
        radio = "0"
    ssid = _pick(idx, ("vap_ssid", "vap-ssid", "ssid"))
    band = _pick(idx, ("radio_band", "radio-band", "radio_type", "radio-type", "current_active_band", "band"))
    if ssid:
        out = Metric("ie_wlc_ssid")
        copy_place(metric, out)
        out.tags["ap"] = str(ap)
        out.tags["radio"] = str(radio)
        out.tags["ssid"] = str(ssid)
        if band:
            out.tags["band"] = str(band)
        clients = _first_idx(idx, ("num_assoc_clients", "num-assoc-clients", "clients"))
        if clients != None:
            out.fields["clients"] = clients
        out.time = metric.time
        return finish_fast(metric, out)
    if "ethernet" in blob:
        out = Metric("ie_wlc_ethernet")
        copy_place(metric, out)
        out.tags["ap"] = str(ap)
        iface = _pick(idx, ("if_name", "if-name"))
        if iface:
            out.tags["if"] = str(iface)
        rx = _first_idx(idx, ("rx_pkts", "rx-pkts"))
        tx = _first_idx(idx, ("tx_pkts", "tx-pkts"))
        if rx != None:
            out.fields["rx_pkts"] = rx
        if tx != None:
            out.fields["tx_pkts"] = tx
        return finish_ether(metric, out)
    out = Metric("ie_wlc_radio")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    out.tags["radio"] = str(radio)
    if not _mac_text(ap):
        out.tags["ap_name"] = str(ap)
    radio_mac = _pick(idx, ("wtp_mac", "wtp-mac", "ethernet_mac", "eth_mac"))
    if radio_mac and _mac_text(radio_mac):
        out.tags["mac"] = str(radio_mac)
    if band:
        out.tags["band"] = str(band)
    util = _first_idx(idx, ("cca_util_percentage", "channel_util", "rx_util_percentage", "cca-util-percentage", "bss_chan_util", "bss-chan-util"))
    # dBm only. load/rx-noise-channel-utilization is a percent and stays its own field.
    noise = noise_dbm(metric)
    inter = _first_idx(idx, ("interference", "non_wifi_inter", "non-wifi-inter", "cca_interference"))
    clients = _first_idx(idx, ("num_assoc_clients", "stations", "clients", "num-assoc-clients"))
    channel = _first_idx(idx, ("channel", "curr_freq", "curr-freq", "current_channel", "current-channel"))
    power = _first_idx(idx, ("curr_tx_power_in_dbm", "curr-tx-power-in-dbm", "tx_power_dbm"))
    level = _first_idx(idx, ("current_tx_power_level", "current-tx-power-level", "tx_power_level"))
    width = _first_idx(idx, ("chan_width", "chan-width", "channel_width"))
    rogues = _first_idx(idx, ("rogue_20_count", "rogue-20-count"))
    if util != None:
        out.fields["channel_util"] = util
    if noise != None:
        out.fields["noise"] = noise
    if inter != None:
        out.fields["interference"] = inter
    if clients != None:
        out.fields["clients"] = clients
    if channel != None:
        out.fields["channel"] = channel
    if power != None:
        out.fields["tx_power_dbm"] = power
        out.fields["tx_power"] = power
    if level != None:
        out.fields["tx_power_level"] = level
    if width != None:
        out.fields["width"] = width
    if rogues != None:
        out.fields["rogue_neighbors"] = rogues
    radio_oper = _pick(idx, ("oper_state", "oper-state", "radio_oper", "ap_operation_state"))
    radio_up = oper_up(radio_oper)
    if radio_up != None:
        out.fields["oper_up"] = radio_up
    return finish_radio(metric, out)


def ap_metric(metric):
    ap = tag_or_field(metric, ("name", "ap_name", "wtp_name", "ap-name", "wtp-name", "wtp_name"))
    if not ap:
        ap = tag_or_field(metric, ("wtp_mac", "wtp-mac"))
    if not ap:
        ap = "unknown"
    if not _keep_history_row(metric, str(ap)):
        return None
    oper = tag_or_field(metric, ("ap_operation_state", "oper_status", "ap_state", "ap-operation-state"))
    # A free-text disconnect reason is a new series on every numeric leaf.
    # Keep a short enum on this one AP series so WlcApDown can still show it.
    reason = tag_or_field(metric, ("reboot_reason", "join_reason", "disconnect_reason", "reboot-reason", "ap-disconnect-reason", "ap_disconnect_reason_str"))
    out = Metric("ie_wlc_ap")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    if reason and low_card("reboot_reason", str(reason)) and _tag_room("reboot_reason", str(reason).strip()):
        out.tags["reboot_reason"] = str(reason).strip()
    up = oper_up(oper)
    # No state leaf is not the same as down. The API treats a fresh info
    # sample as online. Forcing 0 here marked every joined AP offline.
    if up != None:
        out.fields["oper_up"] = up
    # MAC, serial and IP live on the info series only. Copying them onto
    # every counter makes the scrape carry one label set per leaf.
    disconnects = num(tag_or_field(metric, ("disconnects",)))
    if disconnects != None:
        out.fields["disconnects"] = disconnects
    out.time = metric.time
    rows = finish_ap(metric, out)
    remember_named(metric, str(ap))
    info = ap_info(metric, str(ap))
    if info == None:
        return rows
    if rows == None:
        return info
    if type(rows) == "list":
        rows.append(info)
        return rows
    return [rows, info]


def ap_info(metric, ap):
    model = tag_or_field(metric, ("model", "device_detail/static_info/ap_models/model", "ap_models/model"))
    serial = tag_or_field(metric, ("wtp_serial_num", "wtp-serial-num", "serial", "board_data/wtp_serial_num"))
    ip = tag_or_field(metric, ("wtp_ip", "wtp-ip", "ip_addr", "ip-addr", "ap_ip_addr", "ip"))
    mac = tag_or_field(metric, ("wtp_mac", "wtp-mac", "wtp_enet_mac", "eth_mac", "eth-mac", "ethernet_mac"))
    location = tag_or_field(metric, ("ap_location/location", "location"))
    country = tag_or_field(metric, ("country_code", "country-code"))
    ios = tag_or_field(metric, ("sw_version", "sw-version", "wtp_version/sw_version", "ios"))
    mode = tag_or_field(metric, ("wtp_mode", "wtp-mode", "ap_mode_data/wtp_mode", "ap_mode"))
    site_tag = tag_or_field(metric, ("site_tag_name", "site-tag-name", "site_tag/site_tag_name"))
    policy_tag = tag_or_field(metric, ("policy_tag_name", "policy-tag-name", "policy_tag_info/policy_tag_name"))
    rf_tag = tag_or_field(metric, ("rf_tag_name", "rf-tag-name", "rf_tag/rf_tag_name"))
    if not (model or serial or ip or location or country or ios or mode or site_tag):
        return None
    info = Metric("ie_wlc_ap")
    copy_place(metric, info)
    info.tags["ap"] = ap
    if not _mac_text(ap):
        info.tags["ap_name"] = ap
    mac = tag_or_field(metric, ("wtp_mac", "wtp-mac", "mac", "ethernet_mac", "wtp_enet_mac"))
    if mac:
        info.tags["mac"] = str(mac)
    if model:
        info.tags["model"] = str(model)
    if serial:
        info.tags["serial"] = str(serial)
    if ip:
        info.tags["ip"] = str(ip)
    if mac:
        info.tags["mac"] = str(mac)
    if location:
        info.tags["location"] = str(location)
    if country:
        info.tags["country"] = str(country)
    if ios:
        info.tags["ios"] = str(ios)
        info.tags["sw_version"] = str(ios)
    # One label on the info series. The same word on every counter leaf
    # made each AP state a second copy of the whole counter set.
    state = tag_or_field(metric, ("ap_operation_state", "oper_status", "ap_state", "ap-operation-state"))
    if state and low_card("ap_operation_state", str(state)):
        info.tags["ap_operation_state"] = str(state).strip()
    if mode:
        info.tags["mode"] = str(mode)
    if site_tag:
        info.tags["site_tag"] = str(site_tag)
    if policy_tag:
        info.tags["policy_tag"] = str(policy_tag)
    if rf_tag:
        info.tags["rf_tag"] = str(rf_tag)
    info.fields["info"] = 1
    info.time = metric.time
    return info


def neighbor_metric(metric):
    ap = tag_or_field(metric, ("ap_name", "ap-name", "name"))
    if not ap:
        ap = "unknown"
    switch = tag_or_field(metric, ("neighbor_switch", "cdp_cache_device_id", "system_name", "system-name"))
    port = tag_or_field(metric, ("neighbor_port", "cdp_cache_device_port", "cdp-cache-device-port", "port_id", "port-id"))
    out = Metric("ie_wlc_neighbor")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    if switch:
        out.tags["switch"] = str(switch)
    if port:
        out.tags["port"] = str(port)
    if not (switch or port):
        return None
    out.fields["info"] = 1
    out.time = metric.time
    return out


def rogue_mdt(metric):
    total = num(tag_or_field(metric, ("total_count", "total-count")))
    malicious = num(tag_or_field(metric, ("malicious_count", "malicious-count")))
    friendly = num(tag_or_field(metric, ("friendly_count", "friendly-count")))
    out = Metric("ie_wlc_rogue")
    copy_place(metric, out)
    if total != None:
        out.fields["aps"] = total
    if malicious != None:
        out.fields["malicious"] = malicious
    if friendly != None:
        out.fields["friendly"] = friendly
    out.time = metric.time
    return finish(metric, out)


def ha_metric(metric):
    text = tag_or_field(metric, ("ha_state", "ha-state"))
    peer = tag_or_field(metric, ("peer_state", "peer-state"))
    out = Metric("ie_wlc_ha")
    copy_place(metric, out)
    if text:
        out.tags["ha_state"] = str(text)
    if peer:
        out.tags["peer_state"] = str(peer)
    active = 0
    if text and str(text).lower() == "active":
        active = 1
    out.fields["active"] = active
    out.time = metric.time
    return finish(metric, out)


def cpu_metric(metric):
    value = first_num(metric, ("five_minutes", "five-minutes", "five_seconds", "five-seconds"))
    out = Metric("ie_wlc_cpu")
    copy_place(metric, out)
    if value != None:
        out.fields["busy_percent"] = value
    out.time = metric.time
    return finish(metric, out)


def memory_metric(metric):
    used = num(tag_or_field(metric, ("used_memory", "used-memory")))
    free = num(tag_or_field(metric, ("free_memory", "free-memory")))
    total = num(tag_or_field(metric, ("total_memory", "total-memory")))
    out = Metric("ie_wlc_memory")
    copy_place(metric, out)
    pool = tag_or_field(metric, ("name",))
    if pool:
        out.tags["pool"] = str(pool)
    if used != None:
        out.fields["used"] = used
    if free != None:
        out.fields["free"] = free
    if total != None:
        out.fields["total"] = total
    out.time = metric.time
    return finish(metric, out)


def wlan_metric(metric):
    ssid = tag_or_field(metric, ("ssid", "wlan_profile", "wlan-profile", "wlan_profile_name", "wlan-profile-name"))
    clients = num(tag_or_field(metric, ("clients", "curr_clients_count", "curr-clients-count", "client_curr_state_run", "client-curr-state-run")))
    out = Metric("ie_wlc_wlan")
    copy_place(metric, out)
    if ssid:
        out.tags["ssid"] = str(ssid)
    if clients != None:
        out.fields["clients"] = clients
    out.time = metric.time
    return finish(metric, out)


def controller_passthrough(metric):
    joined = num(tag_or_field(metric, ("joined_aps_count", "joined-aps-count")))
    name = "ie_wlc_ap_global" if joined != None else metric.name
    out = Metric(name)
    copy_place(metric, out)
    if joined != None:
        out.fields["joined_aps"] = joined
    out.time = metric.time
    return finish(metric, out)


def snmp_ap(metric):
    remember_ap(metric)
    if "oper_status" in metric.fields:
        oper = num(metric.fields["oper_status"])
        if oper != None:
            metric.fields["oper_up"] = 1 if oper == 1 else 0
    if "admin_status" in metric.fields:
        admin = num(metric.fields["admin_status"])
        if admin != None:
            metric.fields["admin_up"] = 1 if admin == 1 else 0
    ap = tag_or_field(metric, ("ap_name",))
    if ap and "ap" not in metric.tags:
        metric.tags["ap"] = str(ap)
    return metric


def snmp_radio(metric):
    ap, radio = snmp_place(metric)
    metric.tags["ap"] = ap
    metric.tags["radio"] = radio
    if "radio_oper" in metric.fields:
        val = num(metric.fields["radio_oper"])
        if val != None:
            metric.fields["oper_up"] = 1 if val == 2 else 0
    if "radio_admin" in metric.fields:
        val = num(metric.fields["radio_admin"])
        if val != None:
            metric.fields["admin_up"] = 1 if val == 1 else 0
    if "tx_power_level" in metric.fields and "tx_power" not in metric.fields:
        metric.fields["tx_power"] = metric.fields["tx_power_level"]
    return metric


def snmp_noise(metric):
    maybe_reset(metric)
    ap, radio = snmp_place(metric)
    power = num(tag_or_field(metric, ("noise",)))
    if power == None:
        return None
    key = who(metric) + "|" + ap + "|" + radio
    if key not in noise_worst() or power > noise_worst()[key]:
        noise_worst()[key] = power
    out = Metric("ie_wlc_radio")
    copy_place(metric, out)
    out.tags["ap"] = ap
    out.tags["radio"] = radio
    out.fields["noise"] = noise_worst()[key]
    out.time = metric.time
    return out


def snmp_interference(metric):
    maybe_reset(metric)
    ap, radio = snmp_place(metric)
    power = num(tag_or_field(metric, ("interference",)))
    if power == None:
        return None
    key = who(metric) + "|" + ap + "|" + radio
    if key not in inter_worst() or power > inter_worst()[key]:
        inter_worst()[key] = power
    out = Metric("ie_wlc_radio")
    copy_place(metric, out)
    out.tags["ap"] = ap
    out.tags["radio"] = radio
    out.fields["interference"] = inter_worst()[key]
    out.time = metric.time
    return out


def snmp_rogue(metric):
    maybe_reset(metric)
    wlc = who(metric)
    ident = ""
    if "index" in metric.tags:
        ident = metric.tags["index"]
    if ident:
        rogue_seen()[wlc + "|" + ident] = 1
    count = 0
    prefix = wlc + "|"
    for key in rogue_seen():
        if len(key) >= len(prefix) and key[:len(prefix)] == prefix:
            count += 1
    out = Metric("ie_wlc_rogue")
    copy_place(metric, out)
    out.fields["aps"] = count
    out.time = metric.time
    return out


def snmp_join(metric):
    ap = tag_or_field(metric, ("ap_name",))
    if not ap:
        ap = "unknown"
    out = Metric("ie_wlc_ap")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    for src, dst in (("uptime_centiseconds", "uptime_centiseconds"), ("reassoc_ok", "reassoc_ok"), ("reassoc_fail", "reassoc_fail"), ("assoc_fail", "assoc_fail")):
        if src in metric.fields:
            out.fields[dst] = metric.fields[src]
    out.time = metric.time
    return out


def snmp_place(metric):
    ap = tag_or_field(metric, ("ap_name", "ap"))
    index = metric.tags["index"] if "index" in metric.tags else ""
    mac, radio = split_index(index)
    wlc = who(metric)
    if not ap and mac and (wlc + "|" + mac) in ap_names():
        ap = ap_names()[wlc + "|" + mac]
    if not ap:
        ap = mac if mac else "unknown"
    return str(ap), str(radio)


def split_index(index):
    # MAC is the first six dotted index bytes. The next byte is the radio slot.
    # Telegraf 1.38.3 uses go.starlark.net with while loops disabled, so the
    # walk is a for-loop over range() bounded by that six-byte prefix.
    parts = []
    if index:
        parts = index.split(".")
    limit = len(parts)
    if limit > 6:
        limit = 6
    mac_parts = []
    for i in range(limit):
        mac_parts.append(parts[i])
    mac = join_dot(mac_parts)
    radio = "0"
    if len(parts) > 6:
        radio = parts[6]
    return mac, radio


def join_dot(parts):
    out = ""
    first = True
    for part in parts:
        if first:
            out = part
            first = False
        else:
            out = out + "." + part
    return out


def sdwan_metric(metric, blob):
    local_color = tag_or_field(metric, ("local_color", "color", "local-color"))
    remote_color = tag_or_field(metric, ("remote_color", "remote-color"))
    if not local_color:
        local_color = "unknown"
    if not remote_color:
        remote_color = "unknown"
    out = Metric("ie_sdwan_tunnel")
    copy_place(metric, out)
    out.tags["local_color"] = str(local_color)
    out.tags["remote_color"] = str(remote_color)
    peer = tag_or_field(metric, ("system_ip", "remote_system_ip", "dst_ip", "dst-ip"))
    if peer:
        out.tags["peer"] = str(peer)
    wrote = False
    loss = num(tag_or_field(metric, ("loss_percentage", "mean_loss", "loss", "loss-percentage", "mean-loss")))
    latency = num(tag_or_field(metric, ("mean_latency", "latency", "mean-latency")))
    jitter = num(tag_or_field(metric, ("mean_jitter", "average_jitter", "jitter", "mean-jitter")))
    tunnel_state = tag_or_field(metric, ("state", "session_state", "bfd_state"))
    if loss != None:
        if loss > 1:
            loss = loss / 100.0
        out.fields["loss_ratio"] = loss
        wrote = True
    if latency != None:
        out.fields["latency_ms"] = latency
        wrote = True
    if jitter != None:
        out.fields["jitter_ms"] = jitter
        wrote = True
    up = bfd_up(tunnel_state)
    if up != None:
        out.fields["up"] = up
        wrote = True
    out.time = metric.time
    return finish(metric, out)


def remember_ap(metric):
    ap = tag_or_field(metric, ("ap_name", "ap-name", "name"))
    index = ""
    if "index" in metric.tags:
        index = metric.tags["index"]
    wlc = who(metric)
    if ap and index:
        mac, _radio = split_index(index)
        ap_names()[wlc + "|" + index] = ap
        if mac:
            ap_names()[wlc + "|" + mac] = ap


def remember_named(metric, ap):
    mac = tag_or_field(metric, ("wtp_mac", "ap_mac", "wtp-mac"))
    if mac:
        ap_names()[who(metric) + "|" + str(mac)] = ap


def copy_place(src, dst):
    for key in ("wlc", "site", "platform", "source"):
        if key in src.tags and src.tags[key]:
            dst.tags[key] = src.tags[key]
    if "wlc" not in dst.tags:
        dst.tags["wlc"] = who(src)


def who(metric):
    if "wlc" in metric.tags and metric.tags["wlc"]:
        return metric.tags["wlc"]
    if "source" in metric.tags and metric.tags["source"]:
        return metric.tags["source"]
    return "unknown"


def store_clients(metric):
    # Default is store. Only an explicit off skips per-client series.
    if "store_clients" not in metric.tags:
        return True
    value = metric.tags["store_clients"].lower()
    if value == "0" or value == "false" or value == "no" or value == "off":
        return False
    if value == "":
        return True
    return True


def tag_or_field(metric, names):
    # Exact names first. IOS-XE kvgpb then nests containers, and Telegraf
    # joins them with "/" after turning hyphens into underscores
    # (device_detail/static_info/ap_models/model). A suffix match still finds
    # the leaf. The shortest key wins so a top-level leaf beats a deeper one.
    for name in names:
        found = _lookup(metric, name, False)
        if found != None:
            return found
    for name in names:
        found = _lookup(metric, name, True)
        if found != None:
            return found
    return None


def _lookup(metric, name, nested):
    leaf = name.replace("-", "_")
    best = None
    best_len = 0
    for key in metric.tags:
        if metric.tags[key] == "":
            continue
        if not _history_kept(key):
            continue
        if (not nested and key == name) or (nested and _suffix(key, leaf)):
            if best == None or len(key) < best_len:
                best = metric.tags[key]
                best_len = len(key)
    for key in metric.fields:
        value = metric.fields[key]
        if value == "":
            continue
        if not _history_kept(key):
            continue
        if (not nested and (key == name or key == leaf)) or (nested and _suffix(key, leaf)):
            if best == None or len(key) < best_len:
                best = value
                best_len = len(key)
    return best


def _suffix(key, leaf):
    if key == leaf:
        return True
    tail = "/" + leaf
    if len(key) < len(tail):
        return False
    return key[len(key) - len(tail):] == tail


def num(value):
    if value == None:
        return None
    kind = type(value)
    if kind == "int" or kind == "float":
        return value
    if kind != "string":
        return None
    text = value.strip()
    if len(text) >= 4 and text[len(text) - 4:].lower() == "mbps":
        text = text[:len(text) - 4].strip()
    if not _numeric_text(text):
        return None
    if "." in text:
        return float(text)
    if text[0] == "+":
        text = text[1:]
    return int(text)


def _numeric_text(text):
    n = len(text)
    if n == 0:
        return False
    start = 0
    if text[0] == "-" or text[0] == "+":
        start = 1
    if start >= n:
        return False
    dot = False
    digits = False
    for i in range(start, n):
        ch = text[i]
        if ch == ".":
            if dot:
                return False
            dot = True
        elif ch < "0" or ch > "9":
            return False
        else:
            digits = True
    return digits


def first_num(metric, names):
    for name in names:
        value = num(tag_or_field(metric, (name,)))
        if value != None:
            return value
    return None


def snake(key):
    leaf = key
    slash = key.rfind("/")
    if slash >= 0:
        leaf = key[slash + 1:]
    return leaf.replace("-", "_")


def chan_beside(metric, key):
    slash = key.rfind("/")
    if slash < 0:
        return None
    prefix = key[:slash]
    for suffix in ("/chan", "/channel"):
        sibling = prefix + suffix
        if sibling in metric.fields:
            return num(metric.fields[sibling])
        if sibling in metric.tags:
            return num(metric.tags[sibling])
    return None


def noise_dbm(metric):
    # radio-oper-stats publishes noise-floor. rrm-measurement publishes dBm
    # under noise/noise/noise-data/<n>/noise, one leaf per scanned channel.
    # The shortest key ending in /noise is often a non-numeric container, so
    # every numeric noise leaf is considered. The operating channel wins;
    # otherwise the worst (least negative) dBm is kept.
    floor = first_num(metric, ("noise_floor", "noise-floor"))
    operating = first_num(metric, ("channel", "curr_freq", "curr-freq", "current_channel", "current-channel"))
    chosen = None
    worst = None
    for key in metric.fields:
        if snake(key) != "noise":
            continue
        if "utilization" in key:
            continue
        value = num(metric.fields[key])
        if value == None:
            continue
        chan = chan_beside(metric, key)
        if operating != None and chan != None and chan == operating:
            chosen = value
        if worst == None or value > worst:
            worst = value
    if chosen != None:
        return chosen
    if worst != None:
        return worst
    return floor


def attach_channel_noise(metric, out):
    for key in metric.fields:
        if snake(key) != "noise" or "noise_data" not in key:
            continue
        value = num(metric.fields[key])
        if value == None:
            continue
        chan = chan_beside(metric, key)
        if chan == None:
            continue
        label = str(chan)
        if len(label) > 2 and label[len(label) - 2:] == ".0":
            label = label[:len(label) - 2]
        name = "noise_" + label
        if name not in out.fields:
            out.fields[name] = value


# Extra tags that are not the AP identity. Past this many distinct values
# the tag is dropped so a free-form reason cannot mint a series per AP event.
TAG_VALUE_CAP = 128


def _digits(text):
    if text == "":
        return False
    for i in range(len(text)):
        ch = text[i]
        if ch < "0" or ch > "9":
            return False
    return True


def _ends(text, suffix):
    if len(text) < len(suffix):
        return False
    return text[len(text) - len(suffix):] == suffix


def _history_parent(token):
    parent = token.lower()
    if "history" in parent:
        return True
    return _ends(parent, "ptr")


def history_group(key):
    # Repeated YANG lists arrive as .../ewlc-ap-state-ptr/12/uptime or as
    # ewlc_ap_state_ptr_12_uptime. The index is not part of the metric name.
    if "/" in key:
        parts = key.split("/")
        found = None
        for i in range(len(parts)):
            if not _digits(parts[i]):
                continue
            parent = ""
            if i > 0:
                parent = parts[i - 1]
            if _history_parent(parent):
                found = ("/".join(parts[:i]), int(parts[i]))
        return found
    parts = key.split("_")
    for i in range(len(parts) - 1):
        if _history_parent(parts[i]) and _digits(parts[i + 1]):
            return ("_".join(parts[:i + 1]), int(parts[i + 1]))
    return None


def _timestamp_text(text):
    if len(text) < 19:
        return False
    if text[4] != "-" or text[7] != "-":
        return False
    for i in range(4):
        ch = text[i]
        if ch < "0" or ch > "9":
            return False
    return True


def _time_rank(key, value):
    leaf = snake(key)
    if "time" not in leaf and "date" not in leaf and "timestamp" not in leaf:
        return None
    if type(value) == "string":
        text = value.strip()
        if _timestamp_text(text):
            return text
        return None
    if type(value) == "int" or type(value) == "float":
        if value >= 1000000000 and value < 100000000000000:
            return value
    return None


def _rank_newer(rank, previous):
    if type(rank) != type(previous):
        return type(rank) == "string"
    return rank > previous


def history_keep(metric):
    # group -> index -> timestamp rank. No rank means the highest index wins.
    classified = {}
    indexes = {}
    ranks = {}
    for key in metric.fields:
        info = history_group(key)
        if info == None:
            continue
        classified[key] = info
        group = info[0]
        index = info[1]
        if group not in indexes:
            indexes[group] = {}
        indexes[group][index] = True
        rank = _time_rank(key, metric.fields[key])
        if rank == None:
            continue
        if group not in ranks:
            ranks[group] = {}
        previous = ranks[group][index] if index in ranks[group] else None
        if previous == None or _rank_newer(rank, previous):
            ranks[group][index] = rank
    keep = {}
    for group in indexes:
        best_index = None
        best_rank = None
        for index in indexes[group]:
            rank = None
            if group in ranks and index in ranks[group]:
                rank = ranks[group][index]
            if best_index == None:
                best_index = index
                best_rank = rank
                continue
            if rank != None and (best_rank == None or _rank_newer(rank, best_rank)):
                best_index = index
                best_rank = rank
            elif rank == None and best_rank == None and index > best_index:
                best_index = index
        keep[group] = best_index
    # Lookups walk every field. Remember the dropped keys so that walk stays a dict check.
    dropped = {}
    for key in classified:
        info = classified[key]
        group = info[0]
        if group in keep and keep[group] != info[1]:
            dropped[key] = True
    state["history_drop"] = dropped
    return keep


def _history_kept(key):
    if "history_drop" not in state:
        return True
    return key not in state["history_drop"]


def field_name(key):
    info = history_group(key)
    if info == None or "/" in key:
        return snake(key)
    parts = key.split("_")
    for i in range(len(parts) - 1):
        if _history_parent(parts[i]) and _digits(parts[i + 1]):
            return "_".join(parts[i + 2:])
    return snake(key)


def low_card(key, value):
    if type(value) != "string":
        return False
    text = value.strip()
    if text == "" or len(text) > 64 or _mac_text(text) or _timestamp_text(text):
        return False
    # Enums are hyphenated tokens. A space is a sentence or a note.
    if " " in text:
        return False
    leaf = field_name(key)
    if "mac" in leaf or "addr" in leaf or "serial" in leaf or "uuid" in leaf or "user" in leaf or "time" in leaf or "description" in leaf:
        return False
    if leaf == "ip" or _ends(leaf, "_ip"):
        return False
    for hint in ("state", "mode", "status", "name", "type", "band", "role", "reason", "profile", "protocol", "country"):
        if leaf == hint or _ends(leaf, "_" + hint):
            return True
    return False


def _tag_room(leaf, text):
    if "tag_card" not in state:
        state["tag_card"] = {}
    card = state["tag_card"]
    if leaf not in card:
        card[leaf] = {}
    seen = card[leaf]
    if text in seen:
        return True
    count = 0
    for _seen in seen:
        count = count + 1
    if count >= TAG_VALUE_CAP:
        return False
    seen[text] = True
    return True


def _index_parent(key):
    # The container immediately before a numeric list index. None when the
    # leaf is a scalar.
    found = None
    if "/" in key:
        parts = key.split("/")
        for i in range(len(parts)):
            if not _digits(parts[i]):
                continue
            if i > 0:
                found = parts[i - 1]
            else:
                found = ""
        return found
    parts = key.split("_")
    for i in range(len(parts) - 1):
        if _digits(parts[i + 1]):
            found = parts[i]
    return found


def _unstable_index(key):
    # History keeps the newest row under the leaf name. A slash index is a
    # YANG list position: channel noise is rewritten to noise_<channel>, and
    # every other list (neighbors, clients, rogues) would be a new series
    # each time the position changed. A scalar leaf such as stat_1 is kept.
    if history_group(key) != None:
        return not _history_kept(key)
    if "/" not in key:
        return False
    parent = _index_parent(key)
    if parent == None:
        return False
    # Channel noise stays. snake() names the dBm leaf "noise", and
    # attach_channel_noise adds noise_<channel>.
    if "noise" in parent.lower():
        return False
    return True


def _is_history_metric(metric):
    path = ""
    if "path" in metric.tags:
        path = metric.tags["path"]
    blob = (metric.name + " " + path).lower()
    return "history" in blob


def _keep_history_row(metric, ap):
    # Each history record arrives as its own metric. Only the newest one
    # for this AP is stored, under the same labels as the AP series.
    if not _is_history_metric(metric):
        return True
    rank = None
    for key in metric.fields:
        found = _time_rank(key, metric.fields[key])
        if found == None:
            continue
        if rank == None or _rank_newer(found, rank):
            rank = found
    if "hist_rank" not in state:
        state["hist_rank"] = {}
    ranks = state["hist_rank"]
    ident = who(metric) + "|" + str(ap)
    prev = ranks[ident] if ident in ranks else None
    if rank != None and prev != None and _rank_newer(prev, rank):
        return False
    if rank != None:
        ranks[ident] = rank
    return True


def sanitize(metric):
    out = Metric(metric.name)
    copy_place(metric, out)
    for key in ("ap", "radio", "ssid", "band", "if", "name", "pool", "interface"):
        if key in metric.tags and metric.tags[key]:
            out.tags[key] = metric.tags[key]
    out.time = metric.time
    return finish(metric, out)


def attach_extra(metric, out):
    for key in metric.fields:
        if not _history_kept(key) or _unstable_index(key):
            continue
        leaf = field_name(key)
        if leaf == "":
            continue
        target = leaf
        if leaf in ALIAS_OF:
            target = ALIAS_OF[leaf]
        if target in out.fields or leaf in out.fields:
            continue
        value = metric.fields[key]
        kind = type(value)
        if kind == "int" or kind == "float":
            out.fields[leaf] = value
        elif kind == "bool":
            out.fields[leaf] = 1 if value else 0
        elif leaf in ("ap_operation_state", "oper_state", "operation_state", "ap_state"):
            continue
        elif low_card(key, value) and leaf not in out.tags and _tag_room(leaf, str(value).strip()):
            out.tags[leaf] = str(value).strip()


def has_field(fields):
    for key in fields:
        return True
    return False


def attach_numbers(metric, out):
    for key in metric.fields:
        if not _history_kept(key):
            continue
        leaf = field_name(key)
        if leaf == "":
            continue
        target = leaf
        if leaf in ALIAS_OF:
            target = ALIAS_OF[leaf]
        if target in out.fields or leaf in out.fields:
            continue
        value = metric.fields[key]
        kind = type(value)
        if kind == "int" or kind == "float":
            out.fields[leaf] = value
        elif kind == "bool":
            out.fields[leaf] = 1 if value else 0


def _starts(text, prefix):
    n = len(prefix)
    if len(text) < n:
        return False
    return text[:n] == prefix


def leaf_index(metric):
    # Shortest key wins, tags then fields. One pass replaces the repeated
    # tag_or_field scans on a wide radio row.
    found = {}
    lengths = {}
    _index_side(found, lengths, metric.tags)
    _index_side(found, lengths, metric.fields)
    return found


def _index_side(found, lengths, table):
    for key in table:
        if not _history_kept(key):
            continue
        value = table[key]
        if value == "":
            continue
        leaf = snake(key)
        if leaf == "":
            continue
        size = len(key)
        if leaf not in found or size < lengths[leaf]:
            found[leaf] = value
            lengths[leaf] = size


def _pick(idx, names):
    for name in names:
        leaf = name.replace("-", "_")
        if leaf in idx:
            return idx[leaf]
    return None


def _first_idx(idx, names):
    return num(_pick(idx, names))


def config_leaf(leaf):
    # Capwap settings. They are not counters. The UI reads inventory from
    # ie_wlc_ap_info and up/down from ie_wlc_ap_oper_up.
    if leaf == "enable" or leaf == "enabled":
        return True
    if _ends(leaf, "_enable") or _ends(leaf, "_enabled"):
        return True
    if _starts(leaf, "is_") or _starts(leaf, "action_"):
        return True
    if "threshold" in leaf:
        return True
    if _ends(leaf, "_hold_time") or _ends(leaf, "_intvl") or _ends(leaf, "_interval"):
        return True
    if leaf == "build" or leaf == "release" or leaf == "version" or leaf == "clear_mode":
        return True
    if leaf == "dart_is_connected" or leaf == "ap_keepalive_state" or leaf == "degree":
        return True
    if leaf == "floor" or leaf == "flash_sec" or leaf == "lease_time" or leaf == "join_priority":
        return True
    if leaf == "join_time_taken" or leaf == "max_clients_supported" or leaf == "max_power":
        return True
    if leaf == "mem_size" or leaf == "mdns_group_id" or leaf == "multi_window_support":
        return True
    if leaf == "num_ports" or leaf == "num_radio_slots" or leaf == "num_slots" or leaf == "numeric_id":
        return True
    if leaf == "port" or leaf == "radio_reset" or leaf == "radio_slots_in_use":
        return True
    if leaf == "reset_button_state" or leaf == "tot_sniffer_radio" or leaf == "usb_override":
        return True
    if leaf == "vlan_tag_id" or leaf == "weak_rssi" or leaf == "window_size" or leaf == "wtp_model_type":
        return True
    if leaf == "encryption_capabilities" or leaf == "local_dhcp" or leaf == "maint" or leaf == "support":
        return True
    if leaf == "trap_retx_time" or leaf == "detection_time":
        return True
    return False


def _skip_ap_number(leaf):
    if config_leaf(leaf):
        return True
    # Join-request accounting. Nothing in the UI, alerts or dashboards reads it.
    if _starts(leaf, "num_") and leaf != "num_clients":
        return True
    if _ends(leaf, "_setup_req") or _ends(leaf, "_dtls_success"):
        return True
    return False


def _dtls_error(leaf):
    if "dtls" not in leaf:
        return False
    if "err" in leaf or _ends(leaf, "_failure"):
        return True
    return False


def _radio_keep(leaf):
    if leaf == "channel_util" or leaf == "noise" or leaf == "interference":
        return True
    if leaf == "clients" or leaf == "channel" or leaf == "width":
        return True
    if leaf == "tx_power" or leaf == "tx_power_dbm" or leaf == "tx_power_level":
        return True
    if leaf == "oper_up" or leaf == "rogue_neighbors":
        return True
    if leaf == "retry_count" or leaf == "tx_frame_count" or leaf == "fcs_error_count":
        return True
    if leaf == "rx_fragment_count" or leaf == "poor_snr_clients":
        return True
    if leaf == "rx_noise_channel_utilization":
        return True
    if _starts(leaf, "noise_"):
        return True
    return False


def _radio_alias(leaf):
    if leaf in ALIAS_OF:
        return ALIAS_OF[leaf]
    if leaf == "failed_count":
        return "retry_count"
    if leaf == "poor_coverage_clients":
        return "poor_snr_clients"
    return leaf


def _ether_keep(leaf):
    if leaf == "rx_pkts" or leaf == "tx_pkts":
        return True
    if leaf == "input_errors" or leaf == "output_errors":
        return True
    return False


def _copy_kept(metric, out, keep):
    for key in metric.fields:
        if _drop_list_index(key):
            continue
        value = metric.fields[key]
        kind = type(value)
        if kind != "int" and kind != "float" and kind != "bool":
            continue
        leaf = snake(key)
        if leaf == "":
            continue
        leaf = keep(leaf)
        if leaf == "":
            continue
        if leaf in out.fields:
            continue
        if kind == "bool":
            out.fields[leaf] = 1 if value else 0
        else:
            out.fields[leaf] = value


def _keep_radio_leaf(leaf):
    leaf = _radio_alias(leaf)
    if _radio_keep(leaf):
        return leaf
    return ""


def _keep_ether_leaf(leaf):
    if _ether_keep(leaf):
        return leaf
    return ""


def finish_radio(metric, out):
    attach_channel_noise(metric, out)
    _copy_kept(metric, out, _keep_radio_leaf)
    if not has_field(out.fields):
        return None
    out.time = metric.time
    return out


def finish_ether(metric, out):
    _copy_kept(metric, out, _keep_ether_leaf)
    if not has_field(out.fields):
        return None
    out.time = metric.time
    return out


def finish_ap(metric, out):
    # Numbers that are not settings. String leaves are not labels on the
    # counter series. DTLS errors are a second series with only place tags,
    # so a failure-type string cannot multiply them.
    attach_channel_noise(metric, out)
    dtls = None
    for key in metric.fields:
        if not _history_kept(key) or _unstable_index(key):
            continue
        leaf = field_name(key)
        if leaf == "":
            continue
        if leaf == "num_clients" or leaf == "number_of_clients":
            leaf = "clients"
        if _skip_ap_number(leaf):
            continue
        value = metric.fields[key]
        kind = type(value)
        if kind == "bool":
            value = 1 if value else 0
        elif kind != "int" and kind != "float":
            continue
        if _dtls_error(leaf):
            if dtls == None:
                dtls = Metric("ie_wlc_ap")
                copy_place(metric, dtls)
                if "ap" in out.tags:
                    dtls.tags["ap"] = out.tags["ap"]
            if leaf not in dtls.fields:
                dtls.fields[leaf] = value
            continue
        if leaf not in out.fields:
            out.fields[leaf] = value
    if dtls != None:
        dtls.time = metric.time
    if not has_field(out.fields):
        return dtls
    out.time = metric.time
    if dtls == None:
        return out
    return [out, dtls]


def finish(metric, out):
    attach_channel_noise(metric, out)
    attach_extra(metric, out)
    if not has_field(out.fields):
        out.fields["present"] = 1
    out.time = metric.time
    return out


def _drop_list_index(key):
    # A numeric YANG list slot. Channel noise is kept and renamed later.
    if "/" not in key:
        return False
    parts = key.split("/")
    for i in range(len(parts)):
        if not _digits(parts[i]):
            continue
        parent = ""
        if i > 0:
            parent = parts[i - 1]
        if "noise" in parent:
            continue
        return True
    return False


def finish_fast(metric, out):
    # Radio and client rows. Numbers only, one walk, no string tags and no
    # history index. The AP path still uses finish().
    attach_channel_noise(metric, out)
    for key in metric.fields:
        if _drop_list_index(key):
            continue
        value = metric.fields[key]
        kind = type(value)
        if kind != "int" and kind != "float" and kind != "bool":
            continue
        leaf = snake(key)
        if leaf == "":
            continue
        if leaf in ALIAS_OF:
            leaf = ALIAS_OF[leaf]
        if leaf in out.fields:
            continue
        if kind == "bool":
            out.fields[leaf] = 1 if value else 0
        else:
            out.fields[leaf] = value
    if not has_field(out.fields):
        out.fields["present"] = 1
    out.time = metric.time
    return out


def finish_client(metric, out):
    # Numbers only. A string leaf (username, VLAN name, timestamp) is not a label.
    return finish_fast(metric, out)


def emit_client(metric, ap, radio, mac, ssid, band, protocol, vlan, mobility, rssi, snr, bytes_rx, bytes_tx, tx_retries, rts_retries, current_rate, now):
    # radio, protocol, vlan and mobility stay off the series. They change as
    # a client roams and each value would be a new series until expiration.
    raw = Metric("ie_wlc_client")
    if "wlc" in metric.tags and metric.tags["wlc"] != "":
        raw.tags["wlc"] = str(metric.tags["wlc"])
    raw.tags["ap"] = str(ap)
    raw.tags["client"] = str(mac)
    if ssid:
        raw.tags["ssid"] = str(ssid)
    if band:
        raw.tags["band"] = str(band)
    if rssi != None:
        raw.fields["rssi"] = rssi
    if snr != None:
        raw.fields["snr"] = snr
    if bytes_rx != None:
        raw.fields["bytes_rx"] = bytes_rx
    if bytes_tx != None:
        raw.fields["bytes_tx"] = bytes_tx
    if tx_retries != None:
        raw.fields["tx_retries"] = tx_retries
    if rts_retries != None:
        raw.fields["rts_retries"] = rts_retries
    if current_rate != None:
        raw.fields["current_rate"] = current_rate
    raw.time = now
    return finish_client(metric, raw)


def _mac_text(value):
    text = str(value).strip().lower()
    if len(text) == 17 and (text[2] == ":" or text[2] == "-"):
        return True
    if len(text) == 14 and text[4] == "." and text[9] == ".":
        return True
    return False


def oper_up(value):
    # 9800 kvgpb sends the YANG enum, often ewlc-ap-state-registered or ap-up.
    # AireOS SNMP sends associated(1). run is the radio oper word on 17.15.
    if value == None:
        return None
    if type(value) == "int" or type(value) == "float":
        if value == 1 or value == 2 or value == 4:
            return 1
        return 0
    text = str(value).lower().replace("_", "-")
    if text == "":
        return None
    if "not-registered" in text or "deregister" in text or "disassoc" in text or "ap-down" in text:
        return 0
    if text == "down" or text == "offline":
        return 0
    if "registered" in text or text == "ap-up" or text == "up" or text == "enabled" or text == "run" or text == "associated" or text.endswith("-up"):
        return 1
    return 0


def bfd_up(value):
    if value == None:
        return None
    if type(value) == "int" or type(value) == "float":
        if value == 1 or value == 4:
            return 1
        return 0
    text = str(value).lower()
    if text == "up" or text == "up-up":
        return 1
    if text == "":
        return None
    return 0


def drop_old(bucket, now):
    stale = []
    for ident in bucket:
        seen = bucket[ident][2]
        if now - seen > KEEP_NS:
            stale.append(ident)
    for ident in stale:
        bucket.pop(ident)


def drop_old_simple(bucket, now):
    stale = []
    for ident in bucket:
        if now - bucket[ident] > KEEP_NS:
            stale.append(ident)
    for ident in stale:
        bucket.pop(ident)


def summarize(bucket):
    clients = 0
    rssi_sum = 0.0
    rssi_n = 0
    rssi_min = None
    snr_sum = 0.0
    snr_n = 0
    snr_min = None
    for ident in bucket:
        rssi = bucket[ident][0]
        snr = bucket[ident][1]
        if rssi == None and snr == None:
            continue
        clients += 1
        if rssi != None:
            rssi_sum += rssi
            rssi_n += 1
            if rssi_min == None or rssi < rssi_min:
                rssi_min = rssi
        if snr != None:
            snr_sum += snr
            snr_n += 1
            if snr_min == None or snr < snr_min:
                snr_min = snr
    rssi_avg = None
    snr_avg = None
    if rssi_n > 0:
        rssi_avg = rssi_sum / rssi_n
    if snr_n > 0:
        snr_avg = snr_sum / snr_n
    return (clients, rssi_avg, rssi_min, snr_avg, snr_min)

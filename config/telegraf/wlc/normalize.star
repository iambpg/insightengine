# Wireless normalizer.
# 9800 client detail (RSSI, SNR, rates, retries, bytes, SSID, band, protocol,
# VLAN, AP, mobility) is stored per client unless the input tag store_clients
# is "0" (IE_WLC_STORE_CLIENTS=0). Rollups per AP/radio and per SSID are
# always exported. AireOS SNMP does not include a client list; those inputs
# are counts, inventory, radios and neighbours.
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


def apply(metric):
    name = metric.name
    path = ""
    if "path" in metric.tags:
        path = metric.tags["path"]
    blob = (name + " " + path).lower()
    if "wireless-client-oper" in blob or name in CLIENT_NAMES or "traffic-stats" in blob or "common-oper-data" in blob or "dot11-oper-data" in blob:
        return client_metric(metric, blob)
    if "cdp-cache" in blob or "lldp-neigh" in blob or name in ("ie_wlc_cdp_mdt", "ie_wlc_lldp_mdt", "ie_wlc_cdp"):
        return neighbor_metric(metric)
    if name in RADIO_NAMES or "rrm-oper" in blob or "radio-oper" in blob or "ssid-counter" in blob or "ethernet-if" in blob or "capwap-pkts" in blob:
        return radio_metric(metric, blob)
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
    return metric


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
    band = tag_or_field(metric, ("radio_type", "radio-type", "ms_radio_type", "ms-radio-type", "current_active_band", "radio_band", "radio-band"))
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
    current_rate = num(tag_or_field(metric, ("current_rate", "current-rate", "speed")))
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
    if "common-oper" in blob and detail_only:
        bucket[ident] = (prev[0], prev[1], now)
        return None
    if "policy-data" in blob and detail_only:
        return None
    if "mobility-oper-data" in blob and "wireless-client" in blob and detail_only and not store_clients(metric):
        return None
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
        raw = Metric("ie_wlc_client")
        copy_place(metric, raw)
        raw.tags["ap"] = str(ap)
        raw.tags["radio"] = str(radio)
        raw.tags["client"] = str(mac)
        if ssid:
            raw.tags["ssid"] = str(ssid)
        if band:
            raw.tags["band"] = str(band)
        if protocol:
            raw.tags["protocol"] = str(protocol)
        if vlan != None and str(vlan) != "":
            raw.tags["vlan"] = str(vlan)
        if mobility:
            raw.tags["mobility"] = str(mobility)
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
        out.append(raw)
    if len(out) == 1:
        return out[0]
    return out


def radio_metric(metric, blob):
    ap = tag_or_field(metric, ("ap_name", "wtp_mac", "name", "ap-name", "wtp-mac"))
    radio = tag_or_field(metric, ("radio_slot_id", "radio", "slot_id", "radio-slot-id", "slot-id"))
    if not ap:
        ap = "unknown"
    if not radio:
        radio = "0"
    ssid = tag_or_field(metric, ("vap_ssid", "vap-ssid", "ssid"))
    band = tag_or_field(metric, ("radio_band", "radio-band", "radio_type", "radio-type", "current_active_band"))
    if ssid:
        out = Metric("ie_wlc_ssid")
        copy_place(metric, out)
        out.tags["ap"] = str(ap)
        out.tags["radio"] = str(radio)
        out.tags["ssid"] = str(ssid)
        if band:
            out.tags["band"] = str(band)
        clients = num(tag_or_field(metric, ("num_assoc_clients", "num-assoc-clients", "clients")))
        if clients == None:
            return None
        out.fields["clients"] = clients
        out.time = metric.time
        return out
    if "ethernet" in blob:
        out = Metric("ie_wlc_ethernet")
        copy_place(metric, out)
        out.tags["ap"] = str(ap)
        iface = tag_or_field(metric, ("if_name", "if-name"))
        if iface:
            out.tags["if"] = str(iface)
        rx = num(tag_or_field(metric, ("rx_pkts", "rx-pkts")))
        tx = num(tag_or_field(metric, ("tx_pkts", "tx-pkts")))
        if rx != None:
            out.fields["rx_pkts"] = rx
        if tx != None:
            out.fields["tx_pkts"] = tx
        if rx == None and tx == None:
            return None
        out.time = metric.time
        return out
    out = Metric("ie_wlc_radio")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    out.tags["radio"] = str(radio)
    if band:
        out.tags["band"] = str(band)
    wrote = False
    util = num(tag_or_field(metric, ("cca_util_percentage", "channel_util", "rx_util_percentage", "cca-util-percentage", "bss_chan_util", "bss-chan-util")))
    noise = num(tag_or_field(metric, ("noise", "noise_floor", "noise-floor", "rx_noise_channel_utilization", "rx-noise-channel-utilization")))
    inter = num(tag_or_field(metric, ("interference", "non_wifi_inter", "non-wifi-inter", "cca_interference")))
    clients = num(tag_or_field(metric, ("num_assoc_clients", "stations", "clients", "num-assoc-clients")))
    channel = num(tag_or_field(metric, ("channel", "curr_freq", "curr-freq", "current_channel", "current-channel")))
    power = num(tag_or_field(metric, ("curr_tx_power_in_dbm", "curr-tx-power-in-dbm", "tx_power_dbm")))
    level = num(tag_or_field(metric, ("current_tx_power_level", "current-tx-power-level", "tx_power_level")))
    width = num(tag_or_field(metric, ("chan_width", "chan-width", "channel_width")))
    rogues = num(tag_or_field(metric, ("rogue_20_count", "rogue-20-count")))
    if util != None:
        out.fields["channel_util"] = util
        wrote = True
    if noise != None:
        out.fields["noise"] = noise
        wrote = True
    if inter != None:
        out.fields["interference"] = inter
        wrote = True
    if clients != None:
        out.fields["clients"] = clients
        wrote = True
    if channel != None:
        out.fields["channel"] = channel
        wrote = True
    if power != None:
        out.fields["tx_power_dbm"] = power
        out.fields["tx_power"] = power
        wrote = True
    if level != None:
        out.fields["tx_power_level"] = level
        wrote = True
    if width != None:
        out.fields["width"] = width
        wrote = True
    if rogues != None:
        out.fields["rogue_neighbors"] = rogues
        wrote = True
    if not wrote:
        return None
    out.time = metric.time
    return out


def ap_metric(metric):
    ap = tag_or_field(metric, ("name", "ap_name", "wtp_name", "ap-name", "wtp-name", "wtp_name"))
    if not ap:
        ap = tag_or_field(metric, ("wtp_mac", "wtp-mac"))
    if not ap:
        ap = "unknown"
    oper = tag_or_field(metric, ("ap_operation_state", "oper_status", "ap_state", "ap-operation-state"))
    reason = tag_or_field(metric, ("reboot_reason", "join_reason", "disconnect_reason", "reboot-reason", "ap-disconnect-reason", "disconnects"))
    out = Metric("ie_wlc_ap")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    if reason:
        out.tags["reboot_reason"] = str(reason)
    up = oper_up(oper)
    if up != None:
        out.fields["oper_up"] = up
    else:
        out.fields["oper_up"] = 0
    disconnects = num(tag_or_field(metric, ("disconnects",)))
    if disconnects != None:
        out.fields["disconnects"] = disconnects
    out.time = metric.time
    remember_named(metric, str(ap))
    info = ap_info(metric, str(ap))
    if info == None:
        return out
    return [out, info]


def ap_info(metric, ap):
    model = tag_or_field(metric, ("model",))
    serial = tag_or_field(metric, ("wtp_serial_num", "wtp-serial-num", "serial"))
    ip = tag_or_field(metric, ("ip_addr", "ip-addr", "wtp_ip", "wtp-ip", "ip"))
    mac = tag_or_field(metric, ("wtp_mac", "wtp-mac", "eth_mac", "eth-mac", "ethernet_mac"))
    location = tag_or_field(metric, ("location",))
    country = tag_or_field(metric, ("country_code", "country-code"))
    ios = tag_or_field(metric, ("sw_version", "sw-version", "ios"))
    mode = tag_or_field(metric, ("wtp_mode", "wtp-mode", "ap_mode"))
    site_tag = tag_or_field(metric, ("site_tag_name", "site-tag-name"))
    policy_tag = tag_or_field(metric, ("policy_tag_name", "policy-tag-name"))
    rf_tag = tag_or_field(metric, ("rf_tag_name", "rf-tag-name"))
    if not (model or serial or ip or location or country or ios or mode or site_tag):
        return None
    info = Metric("ie_wlc_ap_info")
    copy_place(metric, info)
    info.tags["ap"] = ap
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
    if not switch and not port:
        return None
    out = Metric("ie_wlc_neighbor")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    if switch:
        out.tags["switch"] = str(switch)
    if port:
        out.tags["port"] = str(port)
    out.fields["info"] = 1
    out.time = metric.time
    return out


def rogue_mdt(metric):
    total = num(tag_or_field(metric, ("total_count", "total-count")))
    malicious = num(tag_or_field(metric, ("malicious_count", "malicious-count")))
    friendly = num(tag_or_field(metric, ("friendly_count", "friendly-count")))
    if total == None and malicious == None:
        return None
    out = Metric("ie_wlc_rogue")
    copy_place(metric, out)
    if total != None:
        out.fields["aps"] = total
    if malicious != None:
        out.fields["malicious"] = malicious
    if friendly != None:
        out.fields["friendly"] = friendly
    out.time = metric.time
    return out


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
    return out


def cpu_metric(metric):
    value = num(tag_or_field(metric, ("five_minutes", "five-minutes", "five_seconds", "five-seconds")))
    if value == None:
        return None
    out = Metric("ie_wlc_cpu")
    copy_place(metric, out)
    out.fields["busy_percent"] = value
    out.time = metric.time
    return out


def memory_metric(metric):
    used = num(tag_or_field(metric, ("used_memory", "used-memory")))
    free = num(tag_or_field(metric, ("free_memory", "free-memory")))
    total = num(tag_or_field(metric, ("total_memory", "total-memory")))
    if used == None and free == None and total == None:
        return None
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
    return out


def wlan_metric(metric):
    ssid = tag_or_field(metric, ("ssid", "wlan_profile", "wlan-profile", "wlan_profile_name", "wlan-profile-name"))
    clients = num(tag_or_field(metric, ("clients", "curr_clients_count", "curr-clients-count", "client_curr_state_run", "client-curr-state-run")))
    out = Metric("ie_wlc_wlan")
    copy_place(metric, out)
    if ssid:
        out.tags["ssid"] = str(ssid)
    if clients == None:
        return None
    out.fields["clients"] = clients
    out.time = metric.time
    return out


def controller_passthrough(metric):
    joined = num(tag_or_field(metric, ("joined_aps_count", "joined-aps-count")))
    if joined == None:
        return metric
    out = Metric("ie_wlc_ap_global")
    copy_place(metric, out)
    out.fields["joined_aps"] = joined
    out.time = metric.time
    return out


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
    parts = []
    if index:
        parts = index.split(".")
    mac_parts = []
    i = 0
    while i < len(parts) and i < 6:
        mac_parts.append(parts[i])
        i = i + 1
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
    if not wrote:
        return None
    out.time = metric.time
    return out


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
    for name in names:
        if name in metric.tags and metric.tags[name] != "":
            return metric.tags[name]
        if name in metric.fields:
            return metric.fields[name]
    return None


def num(value):
    if value == None:
        return None
    kind = type(value)
    if kind == "int" or kind == "float":
        return value
    return None


def oper_up(value):
    if value == None:
        return None
    if type(value) == "int" or type(value) == "float":
        if value == 1 or value == 2 or value == 4:
            return 1
        return 0
    text = str(value).lower()
    if text == "ap-up" or text == "registered" or text == "up" or text == "enabled":
        return 1
    if text == "":
        return None
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

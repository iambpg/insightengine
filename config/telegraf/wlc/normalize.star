# Collapse wireless client rows to one series per AP radio.
# Client MACs stay in this process. They are exported only when the input
# tag store_clients is "1" (IE_WLC_STORE_CLIENTS). A 9800 with ~5000 APs
# must not write a Prometheus series per client by default.
#
# State is per Telegraf process. Entries older than 3 minutes are dropped
# the next time that radio is updated.

# `state` is the one global Telegraf lets the script mutate. Client MACs
# live there, not in Prometheus.
KEEP_NS = 180 * 1000000000


def buckets():
    if "buckets" not in state:
        state["buckets"] = {}
    return state["buckets"]


def ap_names():
    if "ap_names" not in state:
        state["ap_names"] = {}
    return state["ap_names"]


def mac_place():
    if "mac_place" not in state:
        state["mac_place"] = {}
    return state["mac_place"]

CLIENT_NAMES = (
    "ie_wlc_client_raw",
    "ie_wlc_client_common",
    "ie_wlc_station",
)
RADIO_NAMES = ("ie_wlc_rrm", "ie_wlc_radio_mdt", "ie_wlc_ssid")
AP_NAMES_IN = ("ie_wlc_ap_mdt",)
SDWAN_NAMES = ("ie_sdwan_bfd", "ie_sdwan_approute")


def apply(metric):
    name = metric.name
    path = ""
    if "path" in metric.tags:
        path = metric.tags["path"]
    blob = (name + " " + path).lower()
    if name in CLIENT_NAMES or "client-oper" in blob or "traffic-stats" in blob or "common-oper" in blob:
        return client_metric(metric, blob)
    if name in RADIO_NAMES or "rrm-oper" in blob or "radio-oper" in blob or "ssid-counter" in blob:
        return radio_metric(metric, blob)
    if name in AP_NAMES_IN or "capwap-data" in blob or "access-point-oper" in blob:
        return ap_metric(metric)
    if name in SDWAN_NAMES or "sdwan-oper" in blob or "app-route" in blob:
        return sdwan_metric(metric, blob)
    if name == "ie_wlc_ap" or name == "ie_wlc_radio":
        remember_ap(metric)
    return metric


def remember_ap(metric):
    ap = tag_or_field(metric, ("ap_name", "ap-name", "name"))
    index = ""
    if "index" in metric.tags:
        index = metric.tags["index"]
    wlc = who(metric)
    if ap and index:
        ap_names()[wlc + "|" + index] = ap


def client_metric(metric, blob):
    mac = tag_or_field(metric, ("ms_mac_address", "client_mac", "ms-mac-address", "client-mac", "ms-mac-addr"))
    if not mac and "index" in metric.tags:
        mac = metric.tags["index"]
    ap = tag_or_field(metric, ("ap_name", "ap-name"))
    radio = tag_or_field(metric, ("ms_ap_slot_id", "radio_slot_id", "radio", "slot_id", "ms-ap-slot-id", "radio-slot-id"))
    wlc = who(metric)
    if not ap:
        mac_key = tag_or_field(metric, ("ap_mac", "wtp_mac", "wtp-mac", "ap-mac"))
        if mac_key and (wlc + "|" + str(mac_key)) in ap_names():
            ap = ap_names()[wlc + "|" + str(mac_key)]
        elif mac_key:
            ap = mac_key
    if mac and (not ap) and (wlc + "|" + str(mac)) in mac_place():
        saved = mac_place()[wlc + "|" + str(mac)]
        ap = saved[0]
        if not radio:
            radio = saved[1]
    if mac and ap:
        mac_place()[wlc + "|" + str(mac)] = (str(ap), str(radio) if radio else "0")
    if not ap:
        ap = "unknown"
    if not radio:
        radio = "0"
    rssi = num(tag_or_field(metric, ("most_recent_rssi", "rssi", "most-recent-rssi", "ewlc_ms_rssi")))
    snr = num(tag_or_field(metric, ("most_recent_snr", "snr", "most-recent-snr")))
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
    if "common-oper" in blob and rssi == None and snr == None:
        bucket[ident] = (prev[0], prev[1], now)
        return None
    bucket[ident] = (rssi, snr, now)
    drop_old(bucket, now)
    agg = Metric("ie_wlc_client_radio")
    copy_place(metric, agg)
    agg.tags["ap"] = str(ap)
    agg.tags["radio"] = str(radio)
    stats = summarize(bucket)
    agg.fields["clients"] = stats[0]
    if stats[1] != None:
        agg.fields["rssi_avg"] = stats[1]
        agg.fields["rssi_min"] = stats[2]
    if stats[3] != None:
        agg.fields["snr_avg"] = stats[3]
        agg.fields["snr_min"] = stats[4]
    agg.time = now
    if store_clients(metric) and mac:
        raw = Metric("ie_wlc_client")
        copy_place(metric, raw)
        raw.tags["ap"] = str(ap)
        raw.tags["radio"] = str(radio)
        raw.tags["client"] = str(mac)
        if rssi != None:
            raw.fields["rssi"] = rssi
        if snr != None:
            raw.fields["snr"] = snr
        raw.time = now
        return [agg, raw]
    return agg


def radio_metric(metric, blob):
    ap = tag_or_field(metric, ("ap_name", "wtp_mac", "name", "ap-name", "wtp-mac"))
    radio = tag_or_field(metric, ("radio_slot_id", "radio", "slot_id", "radio-slot-id"))
    if not ap:
        ap = "unknown"
    if not radio:
        radio = "0"
    out = Metric("ie_wlc_radio")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    out.tags["radio"] = str(radio)
    wrote = False
    util = num(tag_or_field(metric, ("cca_util_percentage", "channel_util", "rx_util_percentage", "cca-util-percentage")))
    noise = num(tag_or_field(metric, ("rx_noise_channel_utilization", "noise", "noise_floor", "rx-noise-channel-utilization")))
    inter = num(tag_or_field(metric, ("interference", "cca_interference")))
    clients = num(tag_or_field(metric, ("num_assoc_clients", "stations", "clients", "num-assoc-clients")))
    channel = num(tag_or_field(metric, ("channel", "curr_freq", "current_channel")))
    power = num(tag_or_field(metric, ("curr_tx_power_in_dbm", "tx_power", "current_tx_power_level")))
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
        out.fields["tx_power"] = power
        wrote = True
    if not wrote:
        return None
    out.time = metric.time
    return out


def ap_metric(metric):
    ap = tag_or_field(metric, ("name", "ap_name", "wtp_name", "ap-name"))
    if not ap:
        ap = tag_or_field(metric, ("wtp_mac", "wtp-mac"))
    if not ap:
        ap = "unknown"
    state = tag_or_field(metric, ("ap_operation_state", "oper_status", "ap_state", "ap-operation-state"))
    reason = tag_or_field(metric, ("reboot_reason", "join_reason", "disconnect_reason", "reboot-reason"))
    out = Metric("ie_wlc_ap")
    copy_place(metric, out)
    out.tags["ap"] = str(ap)
    if reason:
        out.tags["reboot_reason"] = str(reason)
    up = oper_up(state)
    if up != None:
        out.fields["oper_up"] = up
    else:
        out.fields["oper_up"] = 0
    out.time = metric.time
    remember_named(metric, str(ap))
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
    state = tag_or_field(metric, ("state", "session_state", "bfd_state"))
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
    up = bfd_up(state)
    if up != None:
        out.fields["up"] = up
        wrote = True
    if not wrote:
        return None
    out.time = metric.time
    return out


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
    if "store_clients" not in metric.tags:
        return False
    value = metric.tags["store_clients"].lower()
    return value == "1" or value == "true" or value == "yes"


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


def oper_up(state):
    if state == None:
        return None
    if type(state) == "int" or type(state) == "float":
        if state == 2 or state == 4:
            return 1
        return 0
    text = str(state).lower()
    if text == "ap-up" or text == "registered" or text == "up":
        return 1
    if text == "":
        return None
    return 0


def bfd_up(state):
    if state == None:
        return None
    if type(state) == "int" or type(state) == "float":
        if state == 1 or state == 4:
            return 1
        return 0
    text = str(state).lower()
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

# Runs only on client-oper measurements, before normalize.star.
# telegraf-wlc received them on the shared dial-out port. The clients
# process is the one that stores them, so the role tag has to say so
# before the row is written to the internal socket.
def apply(metric):
    metric.tags["wlc_role"] = "clients"
    return metric

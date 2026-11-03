"""Django view. Kept thin: the target shape lives in sd.py."""

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from netbox_lists.sd import (
    default_auth_map_path,
    default_map_path,
    load_auth_map,
    load_map,
    service_targets,
    target_for,
    vbs_targets,
)


def _text(value):
    return "" if value is None else str(value)


def device_dict(device):
    role = getattr(device, "role", None)
    site = getattr(device, "site", None)
    dtype = getattr(device, "device_type", None)
    manufacturer = getattr(dtype, "manufacturer", None) if dtype is not None else None
    platform = getattr(device, "platform", None)
    tenant = getattr(device, "tenant", None)
    region = getattr(site, "region", None) if site is not None else None
    group = getattr(site, "group", None) if site is not None else None
    ip4 = getattr(device, "primary_ip4", None)
    address = ""
    if ip4 is not None and getattr(ip4, "address", None) is not None:
        address = str(ip4.address.ip)
    custom = getattr(device, "custom_field_data", None) or {}
    return {
        "name": _text(getattr(device, "name", "")),
        "primary_ip4": address,
        "role": _text(getattr(role, "slug", "")),
        "site": _text(getattr(site, "name", "")),
        "device_type": _text(getattr(dtype, "model", "")),
        "region": _text(getattr(region, "name", "")),
        "tenant": _text(getattr(tenant, "name", "")),
        "site_group": _text(getattr(group, "name", "")),
        "platform": _text(getattr(platform, "slug", "")),
        "manufacturer": _text(getattr(manufacturer, "slug", "")),
        "snmp_module": _text(custom.get("snmp_module")),
        "snmp_auth": _text(custom.get("snmp_auth")),
    }


class PrometheusDevicesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from dcim.models import Device

        mapping = load_map(default_map_path())
        auth_by_ip = load_auth_map(default_auth_map_path())
        qs = Device.objects.filter(status="active").select_related(
            "role", "device_type", "device_type__manufacturer", "platform", "site",
            "site__region", "site__group", "tenant", "primary_ip4",
        )
        role = request.query_params.get("role")
        if role:
            qs = qs.filter(role__slug=role)
        status = request.query_params.get("status")
        if status:
            qs = qs.filter(status=status)
        targets = []
        for device in qs:
            item = target_for(device_dict(device), mapping, auth_by_ip)
            if item:
                targets.append(item)
        return Response(targets)


def _service_dict(service):
    custom = getattr(service, "custom_field_data", None) or {}
    tags = []
    try:
        tags = [tag.slug for tag in service.tags.all()]
    except Exception:
        tags = []
    ports = list(getattr(service, "ports", None) or [])
    parent = getattr(service, "parent", None)
    address = _text(custom.get("target"))
    site = ""
    if parent is not None:
        if not address:
            ip4 = getattr(parent, "primary_ip4", None)
            if ip4 is not None and getattr(ip4, "address", None) is not None:
                address = str(ip4.address.ip)
        parent_site = getattr(parent, "site", None)
        if parent_site is not None:
            site = _text(getattr(parent_site, "name", ""))
    return {
        "name": _text(getattr(service, "name", "")),
        "tags": tags,
        "probe": _text(custom.get("probe")),
        "address": address,
        "port": ports[0] if ports else "",
        "site": site,
    }


class PrometheusServicesView(APIView):
    """Blackbox HTTP SD. tag=third-party|bank and probe=icmp|tcp."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ipam.models import Service

        tag = request.query_params.get("tag") or ""
        probe = request.query_params.get("probe") or ""
        qs = Service.objects.all()
        if tag:
            qs = qs.filter(tags__slug=tag)
        services = [_service_dict(row) for row in qs.distinct()]
        return Response(service_targets(services, tag, probe))


class PrometheusVbsView(APIView):
    """Blackbox ICMP HTTP SD for each site that has vbs_server_ip."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        from dcim.models import Site

        sites = []
        for site in Site.objects.all():
            custom = getattr(site, "custom_field_data", None) or {}
            sites.append({
                "name": _text(getattr(site, "name", "")),
                "vbs_server_ip": _text(custom.get("vbs_server_ip")),
                "vbs_server_port": custom.get("vbs_server_port") or 9999,
            })
        return Response(vbs_targets(sites))

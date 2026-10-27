"""Structured read models over the same files the raw editor uses. They do not save."""

from __future__ import annotations

import json

import yaml


def prometheus_view(content: str) -> dict:
    data = yaml.safe_load(content) or {}
    jobs = []
    for job in (data.get("scrape_configs") or []):
        if not isinstance(job, dict):
            continue
        targets = []
        sd_urls = []
        for sd in job.get("http_sd_configs") or []:
            if isinstance(sd, dict) and sd.get("url"):
                sd_urls.append(sd["url"])
        for static in job.get("static_configs") or []:
            if isinstance(static, dict):
                targets.extend(static.get("targets") or [])
        params = job.get("params") or {}
        jobs.append({
            "job_name": job.get("job_name"),
            "metrics_path": job.get("metrics_path") or "/metrics",
            "scrape_interval": job.get("scrape_interval"),
            "targets": targets,
            "http_sd": sd_urls,
            "module": (params.get("module") or [None])[0] if isinstance(params.get("module"), list) else params.get("module"),
            "auth": (params.get("auth") or [None])[0] if isinstance(params.get("auth"), list) else params.get("auth"),
        })
    rules = []
    for group in (data.get("groups") or []):
        if not isinstance(group, dict):
            continue
        for rule in group.get("rules") or []:
            if isinstance(rule, dict) and rule.get("alert"):
                rules.append({
                    "group": group.get("name"),
                    "alert": rule.get("alert"),
                    "expr": rule.get("expr"),
                    "for": rule.get("for"),
                    "labels": rule.get("labels") or {},
                    "annotations": rule.get("annotations") or {},
                })
    return {"kind": "prometheus", "jobs": jobs, "rules": rules,
            "warning": "Saving a structured edit reformats the file and drops comments. Review the diff first."}


def alertmanager_view(content: str) -> dict:
    data = yaml.safe_load(content) or {}
    receivers = []
    for recv in data.get("receivers") or []:
        if not isinstance(recv, dict):
            continue
        hooks = []
        for hook in recv.get("webhook_configs") or []:
            if not isinstance(hook, dict):
                continue
            http = hook.get("http_config") or {}
            authz = http.get("authorization") or {}
            hooks.append({
                "url": hook.get("url"),
                "send_resolved": hook.get("send_resolved"),
                "bearer_token_file": authz.get("credentials_file"),
            })
        receivers.append({"name": recv.get("name"), "webhooks": hooks})
    return {"kind": "alertmanager", "route": data.get("route") or {}, "receivers": receivers,
            "warning": "Saving a structured edit reformats the file and drops comments. Review the diff first."}


def snmp_summary(content: str) -> dict:
    data = yaml.safe_load(content) or {}
    auths = sorted((data.get("auths") or {}).keys()) if isinstance(data.get("auths"), dict) else []
    modules = sorted((data.get("modules") or {}).keys()) if isinstance(data.get("modules"), dict) else []
    return {"kind": "snmp-exporter", "auths": auths, "modules": modules, "moduleCount": len(modules),
            "warning": "This is a summary. Edit the raw file; it is large and is not reformatted here."}


def structured_view(app_id: str, file_id: str, content: str) -> dict | None:
    if app_id == "prometheus" and file_id == "prometheus.yml":
        return prometheus_view(content)
    if app_id == "prometheus" and file_id == "alert-rules.yml":
        view = prometheus_view(content)
        view["kind"] = "alert-rules"
        return view
    if app_id == "alertmanager" and file_id == "alertmanager.yml":
        return alertmanager_view(content)
    if app_id == "snmp-exporter" and file_id == "snmp.yml":
        return snmp_summary(content)
    return None


def prometheus_from_jobs(jobs: list[dict], original: str) -> str:
    """Rebuild scrape_configs from a job table. Other top-level keys are kept. Comments are dropped."""
    data = yaml.safe_load(original) or {}
    scrape = []
    for job in jobs:
        item = {"job_name": job["job_name"]}
        if job.get("scrape_interval"):
            item["scrape_interval"] = job["scrape_interval"]
        if job.get("metrics_path"):
            item["metrics_path"] = job["metrics_path"]
        if job.get("http_sd"):
            item["http_sd_configs"] = [{"url": u} for u in job["http_sd"]]
        elif job.get("targets"):
            item["static_configs"] = [{"targets": list(job["targets"])}]
        scrape.append(item)
    data["scrape_configs"] = scrape
    return yaml.safe_dump(data, sort_keys=False)


def json_roundtrip(content: str) -> str:
    return json.dumps(json.loads(content), indent=2) + "\n"

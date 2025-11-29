from __future__ import annotations

import datetime
from typing import Any, Dict, List

import requests

from config import get_settings


def query_prometheus(query: str, start: datetime.datetime, end: datetime.datetime, step: int = 60) -> List[Dict[str, Any]]:
    settings = get_settings()
    url = f"{settings.prometheus_url}/api/v1/query_range"
    params = {
        "query": query,
        "start": start.timestamp(),
        "end": end.timestamp(),
        "step": step
    }
    try:
        resp = requests.get(url, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data.get("data", {}).get("result", [])
    except Exception as e:
        print(f"Error querying Prometheus: {e}")
        return []


def get_container_metrics(container_name: str, pod_name: str, namespace: str, start: datetime.datetime, end: datetime.datetime):
    print(f"Getting container metrics for container {container_name} in pod {pod_name} in namespace {namespace} from {start} to {end}")
    
    cpu_query = f'rate(container_cpu_usage_seconds_total{{container="{container_name}", pod=~"{pod_name}.*", namespace="{namespace}"}}[5m])'
    cpu_data = query_prometheus(cpu_query, start, end)
    
    mem_query = f'container_memory_working_set_bytes{{container="{container_name}", pod=~"{pod_name}.*", namespace="{namespace}"}}'
    mem_data = query_prometheus(mem_query, start, end)
    
    return cpu_data, mem_data

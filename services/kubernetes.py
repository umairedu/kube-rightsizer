from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from kubernetes import client, config
from kubernetes.config.config_exception import ConfigException

from config import get_settings

_KUBECONFIG_LOADED = False
v1 = None
apps_v1 = None


def _ensure_kube_config():
    global _KUBECONFIG_LOADED, v1, apps_v1
    if _KUBECONFIG_LOADED:
        return
    
    settings = get_settings()
    
    if settings.kubernetes_use_in_cluster_config:
        try:
            config.load_incluster_config()
            print("Loaded Kubernetes in-cluster configuration (RBAC mode)")
            _KUBECONFIG_LOADED = True
            v1 = client.CoreV1Api()
            apps_v1 = client.AppsV1Api()
            return
        except ConfigException as exc:
            print(f"Failed to load in-cluster Kubernetes configuration: {exc}")
            raise
    
    configured_path = Path(__file__).parent.parent / "kube_config"
    bundled_path = Path(__file__).parent.parent / "kube_config"
    kube_config_path = configured_path if configured_path.exists() else bundled_path
    
    try:
        if kube_config_path.exists():
            config.load_kube_config(config_file=str(kube_config_path))
            print(f"Loaded Kubernetes config from file: {kube_config_path}")
        else:
            config.load_kube_config()
            print("Loaded Kubernetes config from default location")
    except ConfigException as exc:
        print(f"Failed to load Kubernetes configuration: {exc}")
        raise
    
    v1 = client.CoreV1Api()
    apps_v1 = client.AppsV1Api()
    _KUBECONFIG_LOADED = True


def get_all_pods(excluded_namespaces: List[str], target_namespaces: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    _ensure_kube_config()
    pods = []
    
    if target_namespaces:
        for target_namespace in target_namespaces:
            if target_namespace in excluded_namespaces:
                print(f"Warning: Target namespace '{target_namespace}' is in excluded namespaces list, skipping")
                continue
            
            try:
                ns_pods = v1.list_namespaced_pod(target_namespace)
                for pod in ns_pods.items:
                    if pod.status.phase == "Running":
                        pods.append({
                            'name': pod.metadata.name,
                            'namespace': target_namespace,
                            'pod': pod
                        })
            except Exception as e:
                print(f"Error fetching pods from namespace {target_namespace}: {e}")
        return pods
    
    namespaces = v1.list_namespace()
    
    for ns in namespaces.items:
        ns_name = ns.metadata.name
        if ns_name in excluded_namespaces:
            continue
        
        try:
            ns_pods = v1.list_namespaced_pod(ns_name)
            for pod in ns_pods.items:
                if pod.status.phase == "Running":
                    pods.append({
                        'name': pod.metadata.name,
                        'namespace': ns_name,
                        'pod': pod
                    })
        except Exception as e:
            print(f"Error fetching pods from namespace {ns_name}: {e}")
    
    return pods


def get_pod(pod_name: str, namespace: str):
    _ensure_kube_config()
    return v1.read_namespaced_pod(pod_name, namespace)

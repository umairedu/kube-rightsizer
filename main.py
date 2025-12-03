#!/usr/bin/env python3
import datetime
import sys
import colorama
import yaml
from tabulate import tabulate

from config import get_settings
from services.kubernetes import get_all_pods, get_pod
from services.prometheus import get_container_metrics
from services.slack import send_to_slack

colorama.init(autoreset=True)
USE_COLORS = sys.stdout.isatty()


def _colorize(value: str, color: str) -> str:
    if not USE_COLORS:
        return value
    return f"{color}{value}{colorama.Fore.RESET}"

def _colorize_recommendation(current_val: str, recommended_val: str, resource_type: str) -> str:
    
    if not USE_COLORS:
        return recommended_val
    
    current = parse_resource_value(current_val)
    recommended = parse_resource_value(recommended_val)
    
    if current == 0 or current_val == "N/A":
        return _colorize(recommended_val, colorama.Fore.GREEN + colorama.Style.BRIGHT)
    
    if current == 0:
        return _colorize(recommended_val, colorama.Fore.GREEN + colorama.Style.BRIGHT)
    
    diff_percent = ((recommended - current) / current) * 100
    
    if diff_percent > 50:
        return _colorize(recommended_val, colorama.Fore.GREEN + colorama.Style.BRIGHT)
    elif diff_percent > 20:
        return _colorize(recommended_val, colorama.Fore.GREEN)
    elif diff_percent < -50:
        return _colorize(recommended_val, colorama.Fore.BLUE + colorama.Style.BRIGHT)
    elif diff_percent < -20:
        return _colorize(recommended_val, colorama.Fore.BLUE)
    else:
        return _colorize(recommended_val, colorama.Fore.CYAN)


def calculate_recommendations(cpu_data, mem_data, buffer_percent=20):
    cpu_values = []
    mem_values = []
    
    if cpu_data and len(cpu_data) > 0:
        for result in cpu_data:
            cpu_values.extend([float(v[1]) for v in result.get('values', [])])
    
    if mem_data and len(mem_data) > 0:
        for result in mem_data:
            mem_values.extend([float(v[1]) for v in result.get('values', [])])
    
    if cpu_values:
        cpu_mean = sum(cpu_values) / len(cpu_values)
        cpu_p95 = sorted(cpu_values)[int(len(cpu_values) * 0.95)] if len(cpu_values) > 1 else cpu_values[0]
    else:
        cpu_mean = 0.01
        cpu_p95 = 0.01
    
    if mem_values:
        mem_mean = sum(mem_values) / len(mem_values)
        mem_p95 = sorted(mem_values)[int(len(mem_values) * 0.95)] if len(mem_values) > 1 else mem_values[0]
    else:
        mem_mean = 16 * 1024 * 1024
        mem_p95 = 16 * 1024 * 1024
    
    cpu_request = max(cpu_mean * (1 + buffer_percent/100), 0.01)
    cpu_limit = max(cpu_p95 * (1 + buffer_percent/100), cpu_request * 1.5)
    
    mem_request = max(mem_mean * (1 + buffer_percent/100), 16*1024*1024)
    mem_limit = max(mem_p95 * (1 + buffer_percent/100), mem_request * 1.5)
    
    return {
        "requests": {
            "cpu": f"{int(cpu_request * 1000)}m",
            "memory": f"{int(mem_request / 1024 / 1024)}Mi"
        },
        "limits": {
            "cpu": f"{int(cpu_limit * 1000)}m",
            "memory": f"{int(mem_limit / 1024 / 1024)}Mi"
        },
        "stats": {
            "cpu_mean": f"{cpu_mean:.3f}",
            "cpu_p95": f"{cpu_p95:.3f}",
            "mem_mean_mb": f"{mem_mean / 1024 / 1024:.2f}",
            "mem_p95_mb": f"{mem_p95 / 1024 / 1024:.2f}"
        }
    }


def analyze_pod(pod_name, namespace, start, end, buffer_percent):
    try:
        pod = get_pod(pod_name, namespace)
    except Exception as e:
        print(f"Error reading pod {pod_name} in {namespace}: {e}")
        return None
    
    containers = pod.spec.containers
    recommendations = []
    
    for container in containers:
        cpu_data, mem_data = get_container_metrics(
            container.name, 
            pod_name, 
            namespace, 
            start, 
            end
        )
        
        rec = calculate_recommendations(cpu_data, mem_data, buffer_percent)
        
        current_resources = {
            "requests": {},
            "limits": {}
        }
        
        if container.resources:
            if container.resources.requests:
                current_resources["requests"] = {
                    "cpu": container.resources.requests.get("cpu", "N/A"),
                    "memory": container.resources.requests.get("memory", "N/A")
                }
            if container.resources.limits:
                current_resources["limits"] = {
                    "cpu": container.resources.limits.get("cpu", "N/A"),
                    "memory": container.resources.limits.get("memory", "N/A")
                }
        
        recommendations.append({
            "container": container.name,
            "current": current_resources,
            "recommended": rec
        })
    
    return {
        "pod": pod_name,
        "namespace": namespace,
        "containers": recommendations
    }


def format_as_yaml(recommendations):
    from collections import defaultdict
    
    container_groups = defaultdict(list)
    
    for rec in recommendations:
        for container in rec["containers"]:
            if resources_are_same(container["current"], container["recommended"]):
                continue
            
            container_name = container["container"]
            container_groups[container_name].append({
                "namespace": rec["namespace"],
                "container": container["container"],
                "current": container["current"],
                "recommended": container["recommended"]
            })
    
    if not container_groups:
        return "# No recommendations - all resources are already optimized."
    
    yaml_lines = []
    yaml_lines.append("# Patch the deployment for each container")
    yaml_lines.append("")
    
    sorted_containers = sorted(container_groups.items(), key=lambda x: (x[1][0]["namespace"] if x[1] else "", x[0]))
    
    for container_name, containers in sorted_containers:
        namespace = containers[0]["namespace"]
        
        max_cpu_req = 0.0
        max_mem_req = 0.0
        max_cpu_lim = 0.0
        max_mem_lim = 0.0
        
        for container in containers:
            recommended = container["recommended"]
            cpu_req = parse_resource_value(recommended["requests"]["cpu"])
            mem_req = parse_resource_value(recommended["requests"]["memory"])
            cpu_lim = parse_resource_value(recommended["limits"]["cpu"])
            mem_lim = parse_resource_value(recommended["limits"]["memory"])
            
            max_cpu_req = max(max_cpu_req, cpu_req)
            max_mem_req = max(max_mem_req, mem_req)
            max_cpu_lim = max(max_cpu_lim, cpu_lim)
            max_mem_lim = max(max_mem_lim, mem_lim)
        
        yaml_lines.append(f"# Patch deployment: {container_name}")
        yaml_lines.append(f"#------------")
        yaml_lines.append(f"# {container_name}")
        yaml_lines.append(f"#-------------")
        
        resources = {
            "resources": {
                "requests": {
                    "cpu": format_resource_value(max_cpu_req, "cpu"),
                    "memory": format_resource_value(max_mem_req, "memory")
                },
                "limits": {
                    "cpu": format_resource_value(max_cpu_lim, "cpu"),
                    "memory": format_resource_value(max_mem_lim, "memory")
                }
            }
        }
        
        resources_yaml = yaml.dump(resources, default_flow_style=False, sort_keys=False)
        yaml_lines.append(resources_yaml)
        yaml_lines.append("")
    
    return "\n".join(yaml_lines)


def parse_resource_value(value: str) -> float:
    if value == "N/A" or not value:
        return 0.0
    
    value = value.strip()
    
    # CPU units
    if value.endswith("m"):
        return float(value[:-1]) / 1000.0
    if value.endswith("n"):
        return float(value[:-1]) / 1000000000.0
    
    # Memory binary units (base 1024)
    if value.endswith("Mi"):
        return float(value[:-2]) * 1024 * 1024
    if value.endswith("Gi"):
        return float(value[:-2]) * 1024 * 1024 * 1024
    
    # Memory decimal units (base 1000)
    if value.endswith("M"):
        return float(value[:-1]) * 1000 * 1000
    if value.endswith("G"):
        return float(value[:-1]) * 1000 * 1000 * 1000
    try:
        return float(value)
    except ValueError:
        return 0.0


def resources_are_same(current: dict, recommended: dict) -> bool:
    current_cpu_req = parse_resource_value(current.get("requests", {}).get("cpu", "N/A"))
    current_mem_req = parse_resource_value(current.get("requests", {}).get("memory", "N/A"))
    current_cpu_lim = parse_resource_value(current.get("limits", {}).get("cpu", "N/A"))
    current_mem_lim = parse_resource_value(current.get("limits", {}).get("memory", "N/A"))
    
    rec_cpu_req = parse_resource_value(recommended.get("requests", {}).get("cpu", "N/A"))
    rec_mem_req = parse_resource_value(recommended.get("requests", {}).get("memory", "N/A"))
    rec_cpu_lim = parse_resource_value(recommended.get("limits", {}).get("cpu", "N/A"))
    rec_mem_lim = parse_resource_value(recommended.get("limits", {}).get("memory", "N/A"))
    
    return (
        abs(current_cpu_req - rec_cpu_req) < 0.001 and
        abs(current_mem_req - rec_mem_req) < 0.001 and
        abs(current_cpu_lim - rec_cpu_lim) < 0.001 and
        abs(current_mem_lim - rec_mem_lim) < 0.001
    )


def format_resource_value(value: float, resource_type: str) -> str:
    if resource_type == "cpu":
        return f"{int(value * 1000)}m"
    else:
        return f"{int(value / 1024 / 1024)}Mi"


def format_as_table(recommendations):
    from collections import defaultdict
    
    container_groups = defaultdict(list)
    
    for rec in recommendations:
        for container in rec["containers"]:
            if resources_are_same(container["current"], container["recommended"]):
                continue
            
            container_name = container["container"]
            container_groups[container_name].append({
                "namespace": rec["namespace"],
                "pod": rec["pod"],
                "container": container["container"],
                "current": container["current"],
                "recommended": container["recommended"]
            })
    
    if not container_groups:
        return "No recommendations - all resources are already optimized."
    
    table_data = []
    
    sorted_containers = sorted(container_groups.items(), key=lambda x: (x[1][0]["namespace"] if x[1] else "", x[0]))
    
    for container_name, containers in sorted_containers:
        namespace = containers[0]["namespace"]
        pod_name = containers[0]["pod"]
        
        max_cpu_req = 0.0
        max_mem_req = 0.0
        max_cpu_lim = 0.0
        max_mem_lim = 0.0
        total_cpu_mean = 0.0
        total_mem_mean = 0.0
        count = 0
        
        current_cpu_req = containers[0]["current"].get("requests", {}).get("cpu", "N/A")
        current_mem_req = containers[0]["current"].get("requests", {}).get("memory", "N/A")
        current_cpu_lim = containers[0]["current"].get("limits", {}).get("cpu", "N/A")
        current_mem_lim = containers[0]["current"].get("limits", {}).get("memory", "N/A")
        
        for container in containers:
            recommended = container["recommended"]
            stats = recommended.get("stats", {})
            
            cpu_req = parse_resource_value(recommended["requests"]["cpu"])
            mem_req = parse_resource_value(recommended["requests"]["memory"])
            cpu_lim = parse_resource_value(recommended["limits"]["cpu"])
            mem_lim = parse_resource_value(recommended["limits"]["memory"])
            
            max_cpu_req = max(max_cpu_req, cpu_req)
            max_mem_req = max(max_mem_req, mem_req)
            max_cpu_lim = max(max_cpu_lim, cpu_lim)
            max_mem_lim = max(max_mem_lim, mem_lim)
            
            if stats.get("cpu_mean") != "N/A":
                total_cpu_mean += float(stats.get("cpu_mean", 0))
            if stats.get("mem_mean_mb") != "N/A":
                total_mem_mean += float(stats.get("mem_mean_mb", 0))
            count += 1
        
        avg_cpu_mean = total_cpu_mean / count if count > 0 else 0.0
        avg_mem_mean = total_mem_mean / count if count > 0 else 0.0
        
        rec_cpu_req = format_resource_value(max_cpu_req, "cpu")
        rec_mem_req = format_resource_value(max_mem_req, "memory")
        rec_cpu_lim = format_resource_value(max_cpu_lim, "cpu")
        rec_mem_lim = format_resource_value(max_mem_lim, "memory")
        
        row = [
            _colorize(namespace, colorama.Fore.CYAN),
            _colorize(pod_name, colorama.Fore.CYAN),
            _colorize(container_name, colorama.Fore.YELLOW),
            _colorize(current_cpu_req, colorama.Fore.WHITE),
            _colorize_recommendation(current_cpu_req, rec_cpu_req, "cpu"),
            _colorize(current_cpu_lim, colorama.Fore.WHITE),
            _colorize_recommendation(current_cpu_lim if current_cpu_lim != "N/A" else "0m", rec_cpu_lim, "cpu"),
            _colorize(current_mem_req, colorama.Fore.WHITE),
            _colorize_recommendation(current_mem_req, rec_mem_req, "memory"),
            _colorize(current_mem_lim, colorama.Fore.WHITE),
            _colorize_recommendation(current_mem_lim if current_mem_lim != "N/A" else "0Mi", rec_mem_lim, "memory"),
            _colorize(f"{avg_cpu_mean:.2f}" if avg_cpu_mean > 0 else "N/A", colorama.Fore.MAGENTA),
            _colorize(f"{avg_mem_mean:.2f}" if avg_mem_mean > 0 else "N/A", colorama.Fore.MAGENTA)
        ]
        table_data.append(row)
    
    headers = [
        _colorize("Namespace", colorama.Fore.CYAN),
        _colorize("Pod", colorama.Fore.CYAN),
        _colorize("Container", colorama.Fore.YELLOW),
        _colorize("Curr CPU Req", colorama.Fore.WHITE),
        _colorize("Reco.. CPU Req", colorama.Fore.GREEN),
        _colorize("Curr CPU Limit", colorama.Fore.WHITE),
        _colorize("Reco.. CPU Limit", colorama.Fore.GREEN),
        _colorize("Curr Mem Req", colorama.Fore.WHITE),
        _colorize("Reco.. Mem Req", colorama.Fore.GREEN),
        _colorize("Curr Mem Limit", colorama.Fore.WHITE),
        _colorize("Reco.. Mem Limit", colorama.Fore.GREEN),
        _colorize("Avg CPU (cores)", colorama.Fore.MAGENTA),
        _colorize("Avg Mem (MB)", colorama.Fore.MAGENTA)
    ]
    
    return tabulate(table_data, headers=headers, tablefmt="pretty")


def format_as_html_table(recommendations):
    from collections import defaultdict
    
    container_groups = defaultdict(list)
    
    for rec in recommendations:
        for container in rec["containers"]:
            if resources_are_same(container["current"], container["recommended"]):
                continue
            
            container_name = container["container"]
            container_groups[container_name].append({
                "namespace": rec["namespace"],
                "pod": rec["pod"],
                "container": container["container"],
                "current": container["current"],
                "recommended": container["recommended"]
            })
    
    if not container_groups:
        return "<p>No recommendations - all resources are already optimized.</p>"
    
    html_lines = []
    html_lines.append("<!DOCTYPE html>")
    html_lines.append("<html>")
    html_lines.append("<head>")
    html_lines.append("<meta charset='utf-8'>")
    html_lines.append("<style>")
    html_lines.append("body { font-family: Arial, sans-serif; margin: 20px; }")
    html_lines.append("table { border-collapse: collapse; width: 100%; margin-top: 20px; }")
    html_lines.append("th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }")
    html_lines.append("th { background-color: #4CAF50; color: white; font-weight: bold; }")
    html_lines.append("tr:nth-child(even) { background-color: #f2f2f2; }")
    html_lines.append("tr:hover { background-color: #ddd; }")
    html_lines.append(".increase { color: #2e7d32; font-weight: bold; }")
    html_lines.append(".decrease { color: #1976d2; font-weight: bold; }")
    html_lines.append(".new { color: #2e7d32; font-weight: bold; }")
    html_lines.append(".minor { color: #0288d1; }")
    html_lines.append("</style>")
    html_lines.append("</head>")
    html_lines.append("<body>")
    html_lines.append("<h2>Kubernetes Resource Recommendations</h2>")
    html_lines.append("<table>")
    
    headers = [
        "Namespace", "Pod", "Container",
        "Curr CPU Req", "Reco.. CPU Req",
        "Curr CPU Limit", "Reco.. CPU Limit",
        "Curr Mem Req", "Reco.. Mem Req",
        "Curr Mem Limit", "Reco.. Mem Limit",
        "Avg CPU (cores)", "Avg Mem (MB)"
    ]
    
    html_lines.append("<thead><tr>")
    for header in headers:
        html_lines.append(f"<th>{header}</th>")
    html_lines.append("</tr></thead>")
    html_lines.append("<tbody>")
    
    sorted_containers = sorted(container_groups.items(), key=lambda x: (x[1][0]["namespace"] if x[1] else "", x[0]))
    
    for container_name, containers in sorted_containers:
        namespace = containers[0]["namespace"]
        pod_name = containers[0]["pod"]
        
        max_cpu_req = 0.0
        max_mem_req = 0.0
        max_cpu_lim = 0.0
        max_mem_lim = 0.0
        total_cpu_mean = 0.0
        total_mem_mean = 0.0
        count = 0
        
        current_cpu_req = containers[0]["current"].get("requests", {}).get("cpu", "N/A")
        current_mem_req = containers[0]["current"].get("requests", {}).get("memory", "N/A")
        current_cpu_lim = containers[0]["current"].get("limits", {}).get("cpu", "N/A")
        current_mem_lim = containers[0]["current"].get("limits", {}).get("memory", "N/A")
        
        for container in containers:
            recommended = container["recommended"]
            stats = recommended.get("stats", {})
            
            cpu_req = parse_resource_value(recommended["requests"]["cpu"])
            mem_req = parse_resource_value(recommended["requests"]["memory"])
            cpu_lim = parse_resource_value(recommended["limits"]["cpu"])
            mem_lim = parse_resource_value(recommended["limits"]["memory"])
            
            max_cpu_req = max(max_cpu_req, cpu_req)
            max_mem_req = max(max_mem_req, mem_req)
            max_cpu_lim = max(max_cpu_lim, cpu_lim)
            max_mem_lim = max(max_mem_lim, mem_lim)
            
            if stats.get("cpu_mean") != "N/A":
                total_cpu_mean += float(stats.get("cpu_mean", 0))
            if stats.get("mem_mean_mb") != "N/A":
                total_mem_mean += float(stats.get("mem_mean_mb", 0))
            count += 1
        
        avg_cpu_mean = total_cpu_mean / count if count > 0 else 0.0
        avg_mem_mean = total_mem_mean / count if count > 0 else 0.0
        
        rec_cpu_req = format_resource_value(max_cpu_req, "cpu")
        rec_mem_req = format_resource_value(max_mem_req, "memory")
        rec_cpu_lim = format_resource_value(max_cpu_lim, "cpu")
        rec_mem_lim = format_resource_value(max_mem_lim, "memory")
        
        def _get_html_class(current_val: str, recommended_val: str) -> str:
            current = parse_resource_value(current_val)
            recommended = parse_resource_value(recommended_val)
            
            if current == 0 or current_val == "N/A":
                return "new"
            
            if current == 0:
                return "new"
            
            diff_percent = ((recommended - current) / current) * 100
            
            if diff_percent > 20:
                return "increase"
            elif diff_percent < -20:
                return "decrease"
            else:
                return "minor"
        
        html_lines.append("<tr>")
        html_lines.append(f"<td>{namespace}</td>")
        html_lines.append(f"<td>{pod_name}</td>")
        html_lines.append(f"<td>{container_name}</td>")
        html_lines.append(f"<td>{current_cpu_req}</td>")
        html_lines.append(f"<td class='{_get_html_class(current_cpu_req, rec_cpu_req)}'>{rec_cpu_req}</td>")
        html_lines.append(f"<td>{current_cpu_lim}</td>")
        html_lines.append(f"<td class='{_get_html_class(current_cpu_lim if current_cpu_lim != 'N/A' else '0m', rec_cpu_lim)}'>{rec_cpu_lim}</td>")
        html_lines.append(f"<td>{current_mem_req}</td>")
        html_lines.append(f"<td class='{_get_html_class(current_mem_req, rec_mem_req)}'>{rec_mem_req}</td>")
        html_lines.append(f"<td>{current_mem_lim}</td>")
        html_lines.append(f"<td class='{_get_html_class(current_mem_lim if current_mem_lim != 'N/A' else '0Mi', rec_mem_lim)}'>{rec_mem_lim}</td>")
        avg_cpu_str = f"{avg_cpu_mean:.2f}" if avg_cpu_mean > 0 else "N/A"
        avg_mem_str = f"{avg_mem_mean:.2f}" if avg_mem_mean > 0 else "N/A"
        html_lines.append(f"<td>{avg_cpu_str}</td>")
        html_lines.append(f"<td>{avg_mem_str}</td>")
        html_lines.append("</tr>")
    
    html_lines.append("</tbody>")
    html_lines.append("</table>")
    html_lines.append("</body>")
    html_lines.append("</html>")
    
    return "\n".join(html_lines)




def main():
    settings = get_settings()
    
    end = datetime.datetime.now(datetime.timezone.utc)
    start = end - datetime.timedelta(hours=settings.hours)
    
    print(_colorize(f"Analyzing pods from {start} to {end}", colorama.Fore.GREEN))
    if settings.target_namespaces:
        print(_colorize(f"Target namespaces: {', '.join(settings.target_namespaces)}", colorama.Fore.GREEN))
    else:
        print(_colorize(f"Excluded namespaces: {', '.join(settings.excluded_namespaces)}", colorama.Fore.GREEN))
    print(_colorize(f"Buffer: {settings.buffer_percent}%\n", colorama.Fore.GREEN))
    
    pods = get_all_pods(settings.excluded_namespaces, settings.target_namespaces)
    print(_colorize(f"Found {len(pods)} pods to analyze\n", colorama.Fore.GREEN))
    
    recommendations = []
    for pod_info in pods:
        print(_colorize(f"Analyzing {pod_info['namespace']}/{pod_info['name']}...", colorama.Fore.GREEN))
        result = analyze_pod(
            pod_info['name'],
            pod_info['namespace'],
            start,
            end,
            settings.buffer_percent
        )
        if result:
            recommendations.append(result)
    
    print(_colorize(f"\n{'='*80}", colorama.Fore.GREEN))
    print(_colorize("RECOMMENDATIONS", colorama.Fore.YELLOW))
    print(_colorize(f"{'='*80}\n", colorama.Fore.GREEN))
    
    table_output = ""
    yaml_output = ""
    
    if settings.output_format in ['table', 'both']:
        table_output = format_as_table(recommendations)
        print(table_output)
        print()
    
    html_table_output = ""
    if settings.output_format in ['table', 'both']:
        html_table_output = format_as_html_table(recommendations)
    
    if settings.output_format in ['yaml', 'both']:
        print("\n" + "="*80)
        print("YAML Output:")
        print("="*80 + "\n")
        yaml_output = format_as_yaml(recommendations)
        print(yaml_output)
        
        with open('resource-recommendations.yaml', 'w') as f:
            f.write(yaml_output)
        print("YAML recommendations saved to: resource-recommendations.yaml")
    
    if settings.slack_token and settings.slack_channel and (table_output or yaml_output):
        send_to_slack(
            html_table_output or table_output or "No table output",
            yaml_output or "No YAML output",
            settings.slack_token,
            settings.slack_channel
        )


if __name__ == "__main__":
    main()
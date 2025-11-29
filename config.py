from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    prometheus_url: str = Field(
        default="http://prometheus-server.default.svc:9090",
        description="Prometheus server URL. Format: http://hostname:port or http://service.namespace.svc:port"
    )
    excluded_namespaces_str: str = Field(
        default="kube-system,kube-public,kube-node-lease",
        alias="excluded_namespaces",
        description="List of Kubernetes namespaces to exclude from analysis. Set as comma-separated values in .env file"
    )

    @computed_field
    @property
    def excluded_namespaces(self) -> List[str]:
        if not self.excluded_namespaces_str.strip():
            return []
        return [ns.strip() for ns in self.excluded_namespaces_str.split(",") if ns.strip()]
    buffer_percent: int = Field(
        default=20,
        description="Buffer percentage to add to resource recommendations. Range: 0-100. Default: 20%"
    )
    slack_token: Optional[str] = Field(
        default=None,
        description="Slack bot token for API-based notifications and file uploads. Required for Slack notifications. Format: xoxb-..."
    )
    slack_channel: Optional[str] = Field(
        default=None,
        description="Slack channel ID or name for API-based notifications. Required if using slack_token. Format: #channel-name or C1234567890"
    )
    slack_verify_ssl: bool = Field(
        default=True,
        description="Verify SSL certificates for Slack API calls. Set to 'false' to disable SSL verification (not recommended for production)"
    )
    kubernetes_use_in_cluster_config: bool = Field(
        default=False,
        description="Use in-cluster Kubernetes config (for pods running in cluster). Set to 'true' for production. If 'false', uses kubeconfig file from default location"
    )
    hours: int = Field(
        default=168,
        description="Number of hours of historical data to analyze. Default: 168 (7 days). Minimum: 1"
    )
    output_format: str = Field(
        default="both",
        description="Output format for recommendations. Possible values: 'yaml', 'table', 'both'. Default: 'both'"
    )
    target_namespaces_str: Optional[str] = Field(
        default=None,
        alias="target_namespace",
        description="Target namespace(s) to scan. Comma-separated list. If not set, scans all namespaces (excluding excluded_namespaces). If set, only scans these namespaces"
    )

    @computed_field
    @property
    def target_namespaces(self) -> Optional[List[str]]:
        if not self.target_namespaces_str or not self.target_namespaces_str.strip():
            return None
        return [ns.strip() for ns in self.target_namespaces_str.split(",") if ns.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


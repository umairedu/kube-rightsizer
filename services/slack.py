from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from config import get_settings


def _get_time_period_label(hours: int) -> str:
    if hours < 24:
        return f"{hours}-Hour"
    elif hours == 24:
        return "Daily"
    elif hours < 168:
        days = hours // 24
        return f"{days}-Day"
    elif hours == 168:
        return "Weekly"
    elif hours < 720:
        weeks = hours // 168
        return f"{weeks}-Week"
    elif hours < 2160:
        months = hours // 720
        return f"{months}-Month"
    else:
        return f"{hours // 24}-Day"


def send_to_slack(table_output: str, yaml_output: str, slack_token: Optional[str] = None, channel: Optional[str] = None) -> None:
    settings = get_settings()
    
    if not slack_token:
        slack_token = settings.slack_token
    
    if not slack_token:
        print("No Slack token provided. Skipping Slack notification.")
        return
    
    if not channel:
        channel = settings.slack_channel
    
    if not channel:
        print("No Slack channel provided. Skipping Slack notification.")
        return
    
    time_period = _get_time_period_label(settings.hours)
    _send_to_slack(slack_token, channel, table_output, yaml_output, time_period)


def _send_to_slack(slack_token: str, channel: str, table_output: str, yaml_output: str, time_period: str) -> None:
    if not channel:
        print("Slack channel not provided. Skipping Slack notification.")
        return
    
    settings = get_settings()
    
    if not settings.slack_verify_ssl:
        import urllib3
        import ssl
        import os
        
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        ssl._create_default_https_context = ssl._create_unverified_context
        os.environ['PYTHONHTTPSVERIFY'] = '0'
    
    client = WebClient(token=slack_token)
    
    summary = _create_summary_message(table_output, yaml_output, settings.hours, settings.buffer_percent)
    
    try:
        temp_dir = Path("/tmp")
        temp_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
        
        is_html = table_output.strip().startswith("<!DOCTYPE html>") or table_output.strip().startswith("<html>")
        file_extension = "html" if is_html else "txt"
        table_file = temp_dir / f"k8s_recommendations_table_{timestamp}.{file_extension}"
        yaml_file = temp_dir / f"k8s_recommendations_{timestamp}.yaml"
        
        if table_output and table_output.strip() and table_output != "No table output":
            with open(table_file, "w", encoding="utf-8") as f:
                f.write(table_output)
        
        if yaml_output and yaml_output.strip() and yaml_output != "No YAML output":
            with open(yaml_file, "w", encoding="utf-8") as f:
                f.write(yaml_output)
        
        message_response = client.chat_postMessage(
            channel=channel,
            text=f"📊 {time_period} K8s Resource Recommendations",
            blocks=[
                {
                    "type": "header",
                    "text": {
                        "type": "plain_text",
                        "text": f"📊 {time_period} K8s Resource Recommendations"
                    }
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": summary
                    }
                }
            ]
        )
        
        if not message_response.get("ok"):
            raise SlackApiError(f"Failed to post message: {message_response.get('error')}")
        
        channel_id = message_response.get("channel")
        if not channel_id:
            raise ValueError("Could not get channel ID from message response")
        
        if table_file.exists() and table_file.stat().st_size > 0:
            client.files_upload_v2(
                channel=channel_id,
                title=f"K8s Resource Recommendations Table - {timestamp}",
                file=str(table_file),
                initial_comment="Resource recommendations table"
            )
        
        if yaml_file.exists() and yaml_file.stat().st_size > 0:
            client.files_upload_v2(
                channel=channel_id,
                title=f"K8s Resource Recommendations YAML - {timestamp}",
                file=str(yaml_file),
                initial_comment="Resource recommendations YAML for patching deployments"
            )
        
        if table_file.exists():
            table_file.unlink()
        if yaml_file.exists():
            yaml_file.unlink()
        
        print("Successfully sent recommendations to Slack with file attachments")
    except SlackApiError as e:
        print(f"Error sending to Slack: {e}")
    except Exception as e:
        print(f"Error creating or uploading files: {e}")


def _create_summary_message(table_output: str, yaml_output: str, hours: int, buffer_percent: int) -> str:
    if "No recommendations" in table_output:
        return "✅ All resources are already optimized. No changes needed."
    
    time_period = _get_time_period_label(hours).lower()
    
    return (
        f"Hey there! 👋\n\n"
        f"Based on *{time_period}* historical analysis according to your usage, "
        f"you are requested to adjust your pods resource allocation. "
        f"Detailed report and patch file are attached with an additional *{buffer_percent}%* buffer applied.\n\n"
        f"📎 *Attachments:*\n"
        f"• Resource recommendations table\n"
        f"• YAML patch file for deployment updates"
    )


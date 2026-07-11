"""Ensure follow-up emails send automatically (GitHub Actions, VPS, or local Windows)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from cloud_sync import is_cloud_configured, push_followup_state

TASK_NAME = "ClayOutboundFollowups"
PROJECT_DIR = Path(__file__).parent.resolve()
RUNNER = PROJECT_DIR / "run_scheduled_outbound.py"


def is_task_installed() -> bool:
    result = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"Get-ScheduledTask -TaskName '{TASK_NAME}' -ErrorAction SilentlyContinue",
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and TASK_NAME in result.stdout


def install_windows_task() -> int:
    python_path = str(Path(sys.executable).resolve()).replace("'", "''")
    runner_path = str(RUNNER).replace("'", "''")
    working_dir = str(PROJECT_DIR).replace("'", "''")
    task_name = TASK_NAME.replace("'", "''")

    powershell = f"""
$action = New-ScheduledTaskAction `
    -Execute '{python_path}' `
    -Argument '"{runner_path}"' `
    -WorkingDirectory '{working_dir}'

$repeat = New-ScheduledTaskTrigger `
    -Once `
    -At (Get-Date).Date `
    -RepetitionInterval (New-TimeSpan -Minutes 15) `
    -RepetitionDuration ([TimeSpan]::MaxValue)

$logon = New-ScheduledTaskTrigger -AtLogOn

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5)

Register-ScheduledTask `
    -TaskName '{task_name}' `
    -Action $action `
    -Trigger @($repeat, $logon) `
    -Settings $settings `
    -Force | Out-Null

[xml]$xml = Export-ScheduledTask -TaskName '{task_name}'
$namespace = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
$manager = New-Object System.Xml.XmlNamespaceManager($xml.NameTable)
$manager.AddNamespace('task', $namespace)
$timeTrigger = $xml.SelectSingleNode('//task:TimeTrigger', $manager)
if ($null -ne $timeTrigger) {{
    $repetition = $timeTrigger.SelectSingleNode('task:Repetition', $manager)
    if ($null -eq $repetition) {{
        $repetition = $xml.CreateElement('Repetition', $namespace)
        [void]$timeTrigger.AppendChild($repetition)
    }}
    $interval = $repetition.SelectSingleNode('task:Interval', $manager)
    if ($null -eq $interval) {{
        $interval = $xml.CreateElement('Interval', $namespace)
        [void]$repetition.AppendChild($interval)
    }}
    $interval.InnerText = 'PT15M'
    $duration = $repetition.SelectSingleNode('task:Duration', $manager)
    if ($null -eq $duration) {{
        $duration = $xml.CreateElement('Duration', $namespace)
        [void]$repetition.AppendChild($duration)
    }}
    $duration.InnerText = 'P9999D'
    $stop = $repetition.SelectSingleNode('task:StopAtDurationEnd', $manager)
    if ($null -eq $stop) {{
        $stop = $xml.CreateElement('StopAtDurationEnd', $namespace)
        [void]$repetition.AppendChild($stop)
    }}
    $stop.InnerText = 'false'
}}

Register-ScheduledTask `
    -TaskName '{task_name}' `
    -Xml $xml.OuterXml `
    -Force | Out-Null

Write-Output 'SUCCESS'
"""

    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        powershell,
    ]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout.strip(), file=sys.stderr)
        print(result.stderr.strip(), file=sys.stderr)
        return result.returncode
    return 0


def ensure_automatic_followups(*, quiet: bool = False) -> bool:
    """Enable automatic follow-ups via cloud (free GitHub Actions) or local Windows task."""
    if is_cloud_configured():
        if not quiet:
            print("Syncing follow-up state to cloud...")
        try:
            push_followup_state(quiet=quiet)
        except Exception as exc:
            if not quiet:
                print(f"Cloud sync failed: {exc}", file=sys.stderr)
            return False
        if not quiet:
            print(
                "Follow-ups are automatic in the cloud and run even when your PC is off."
            )
        return True

    if is_task_installed():
        if not quiet:
            print(
                f"Automatic follow-ups enabled via Windows task '{TASK_NAME}' "
                "(requires your PC to be on)."
            )
            print(
                "For free PC-off follow-ups: python cloud/deploy_github.py"
            )
        return True

    if not quiet:
        print("Setting up local automatic follow-up emails...")
    if install_windows_task() != 0:
        if not quiet:
            print(
                "Could not install the Windows scheduled task. "
                "Use free GitHub Actions: python cloud/deploy_github.py",
                file=sys.stderr,
            )
        return False

    if not quiet:
        print(
            f"Local follow-ups enabled via '{TASK_NAME}' (PC must be on). "
            "For free PC-off follow-ups: python cloud/deploy_github.py"
        )
        print(f"Log file: {PROJECT_DIR / 'scheduler.log'}")
    return True

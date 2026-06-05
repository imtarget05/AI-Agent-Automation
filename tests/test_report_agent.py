import asyncio

from apps.report_agent.main import TaskRequest, execute_task


def test_report_accepts_aiops_anomalies_detected_context():
    result = asyncio.run(
        execute_task(
            TaskRequest(
                instruction="Create incident report",
                context={
                    "anomalies_detected": [
                        {
                            "metric": "cpu",
                            "value": "96%",
                            "threshold": "80%",
                            "severity": "high",
                        }
                    ]
                },
            )
        )
    )

    assert result["data"]["metadata"]["anomaly_count"] == 1
    assert "**cpu**: 96%" in result["data"]["report_markdown"]

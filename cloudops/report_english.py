"""English presentation of authoritative reports; no numeric recalculation."""

from core.language import tr


def markdown_english(task: dict) -> str:
    labels = {
        "low_utilization": "Low utilization candidate",
        "normal": "Normal load",
        "peak_risk": "Peak risk",
        "insufficient_data": "Insufficient data",
        "stopped": "Stopped",
    }
    translate = lambda value: tr(value, "en")
    lines = [
        "# Cloud resource analysis report",
        f"Source: {translate(task['source'])} | Region: {task['region']} | Status: {task['status']}",
        f"Rule version: {task['rule_version']} | UTC window: {task.get('window_start','—')} to {task.get('window_end','—')} (end exclusive)",
        "This report provides screening advice. Verify peak demand, compatibility and availability before changing capacity.",
    ]
    for result in task["results"]:
        if "error" in result:
            lines += [f"## {result['resource_id']}", translate(result["error"])]
            continue
        resource = result["resource"]
        lines += [
            f"## {translate(resource['name'])} ({resource['id']})",
            f"Diagnosis: {labels.get(result['diagnosis'],result['diagnosis'])}",
        ]
        for name in ("cpu", "memory"):
            metric = result["metrics"][name]
            lines.append(
                f"- {name.upper()}: average {metric['average']}%, peak {metric['maximum']}%, coverage {metric['coverage']*100:.2f}%"
            )
        lines += ["- " + translate(risk) for risk in result["risks"]]
        if result["candidate"]:
            lines.append(
                f"Candidate type: {result['candidate']['id']} (requires manual verification)"
            )
        if result["savings"]:
            savings = result["savings"]
            lines += [
                f"Monthly equivalent estimate: {savings['monthly_equivalent_saving']} {savings['currency']} ({savings['hours']} hours)",
                translate(savings["scope"]),
                translate(savings["source"]),
            ]
        else:
            lines.append(translate(result["pricing_note"]))
    explanation = task.get("explanation")
    if explanation:
        lines += [
            (
                "## Model explanation"
                if task.get("language") == "en"
                else "## Original model explanation (Chinese)"
            ),
            explanation,
        ]
    lines += ["## Execution steps"]
    for step in task.get("steps", []):
        lines.append(
            f"- {step['tool']} | {step['source']} | {step['status']} | {step['duration_ms']} ms"
        )
    return "\n\n".join(lines) + "\n"

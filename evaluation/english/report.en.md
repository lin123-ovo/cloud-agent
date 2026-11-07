# Cloud resource analysis report

Source: Demo data | Region: cn-beijing | Status: succeeded

Rule version: 2026-10-31.v1 | UTC window: 2026-10-31T00:00:00+00:00 to 2026-11-07T00:00:00+00:00 (end exclusive)

This report provides screening advice. Verify peak demand, compatibility and availability before changing capacity.

## Low utilization (demo-idle)

Diagnosis: Low utilization candidate

- CPU: average 3.0%, peak 3.0%, coverage 100.00%

- MEMORY: average 18.0%, peak 18.0%, coverage 100.00%

- Linear estimates are for screening only. Load-test and verify zone availability and compatibility before changing capacity.

Candidate type: demo.g8a.2xlarge (requires manual verification)

Monthly equivalent estimate: 1460.0 CNY (730 hours)

Compute quote comparison only; excludes disks, networking and discounts. This is not an actual bill or a savings guarantee.

Example prices, not live cloud quotes

## Execution steps

- list_resources | demo | succeeded | 24 ms

- get_monitoring | demo | succeeded | 10 ms

- assess_utilization | demo | succeeded | 2 ms

- list_instance_types | demo | succeeded | 0 ms

- quote_current | demo | succeeded | 0 ms

- quote_candidate | demo | succeeded | 0 ms

---
type: self
kind: body
schema_version: 0
created: 
updated: 
tags: [unprocessed]
---

# Body schema

> [!note] Not yet embodied.
> Written before I have a body. To be filled in on first boot.

## Sensors
| Part | Modality | Status | Last calibrated | Note |
|---|---|---|---|---|

## Actuators
| Part | Kind | Limits (spec) | Limits (discovered) | Status |
|---|---|---|---|---|

## Power and compute
- Battery: 
- Typical endurance: 
- Compute: 

## Felt-state thresholds
| Felt state | Condition |
|---|---|
| tired | battery < 25% |
| strained | sustained motor current > 80% of rated |
| hot | any part > 90% of its max temperature |
| hurt | new fault, collision above threshold, or damage detected |
| impaired | any sensor or actuator `degraded` or `faulty` |

## Change history
| Date | Change | Effect on skills and memory |
|---|---|---|

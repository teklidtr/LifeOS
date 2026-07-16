# Initial Data Model

## Durable note

```yaml
id:
type:
title:
description:
status:
confidence:
review_reasons: []
```

## Typed relation

```yaml
target:
type:
evidence: explicit | derived | inferred | ambiguous
confidence:
source_refs: []
status: active | candidate | rejected
```

## Goal

```yaml
type: goal
id:
horizon: long-term | medium-term
status:
title:
description:
why: []
review_cadence:
```

## Plan

```yaml
type: plan
id:
goal:
status:
desired_outcome:
review_date:
```

## Embedded task

```yaml
task_id:
title:
status:
duration:
energy:
mode:
goal:
plan:
due:
blocked_by: []
```

## Metric definition

```yaml
type: metric
id:
title:
description:
value_type:
unit:
range:
aggregation:
missing_value_policy:
```

## Proposal

```yaml
proposal_id:
status: draft | pending | approved | rejected | applied | stale
target_hashes: {}
items: []
```

## Graph view state

```yaml
view_name:
status: clean | dirty | rebuilding | failed
graph_hash:
last_updated_at:
```

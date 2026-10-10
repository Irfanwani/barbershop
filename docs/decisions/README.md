# Architecture Decision Records

Short, dated notes on decisions that were not obvious.

| #                                          | Decision                              | Status   |
| ------------------------------------------ | ------------------------------------- | -------- |
| [0001](./0001-single-app-two-modes.md)     | One app, role-based modes              | Accepted |
| [0002](./0002-versioned-api.md)           | Version the API under `/api/v1/`       | Accepted |
| [0003](./0003-server-authoritative-pricing.md) | Never trust a client-supplied price | Accepted |
| [0004](./0004-uv-for-dependency-management.md) | `uv` over Poetry + requirements.txt | Accepted |

## The template

```markdown
# NNNN. <Title>

- **Status**: Proposed | Accepted | Superseded by [NNNN](./NNNN-....md)
- **Date**: YYYY-MM-DD

## Context
What is the problem? What forces are at play?

## Decision
What was decided, in the present tense.

## Consequences
What this makes easy. What it makes hard. What we give up.
```
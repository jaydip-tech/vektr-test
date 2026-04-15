# vektr-test

## Jira workflow automation scaffold

This repository contains a minimal implementation scaffold for automatically
updating Jira tickets from development events.

See `src/jira_automation.py` for the event processing flow and
`tests/test_jira_automation.py` for the baseline unit coverage.

## Notable behaviors

- Extracts Jira keys from titles, branch names, PR bodies, commit messages, and metadata.
- Deduplicates repeated deliveries with an explicit idempotency key builder.
- Supports safe event-to-status overrides with input validation for transition names.
- Keeps the Jira client interface narrow and easy to mock in unit tests.

## Running tests

```bash
python -m unittest discover -s tests
```

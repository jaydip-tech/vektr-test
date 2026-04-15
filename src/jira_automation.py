"""Minimal Jira workflow automation scaffold.

This module provides a small, testable design for mapping development events
into Jira updates while keeping idempotency and security concerns explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Any, Dict, Iterable, List, Mapping, Sequence

JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")
SAFE_STATUS_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]{1,48}$")
DEFAULT_EVENT_STATUS_MAP: Dict[str, str] = {
    "pull_request_merged": "Done",
    "deployment_succeeded": "Done",
    "pull_request_opened": "In Progress",
    "branch_created": "In Progress",
}


@dataclass(frozen=True)
class DevEvent:
    event_type: str
    title: str = ""
    branch: str = ""
    commit_messages: List[str] = field(default_factory=list)
    pr_body: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class IdempotencyStore:
    def __init__(self) -> None:
        self._seen: set[str] = set()

    def seen(self, key: str) -> bool:
        return key in self._seen

    def mark(self, key: str) -> None:
        self._seen.add(key)


class JiraClient:
    """Interface-like client wrapper for Jira operations."""

    def transition_issue(self, issue_key: str, status: str) -> Dict[str, Any]:
        raise NotImplementedError

    def add_comment(self, issue_key: str, body: str) -> Dict[str, Any]:
        raise NotImplementedError

    def update_fields(self, issue_key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError


class MockJiraClient(JiraClient):
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    def transition_issue(self, issue_key: str, status: str) -> Dict[str, Any]:
        payload = {"action": "transition", "issue_key": issue_key, "status": status}
        self.calls.append(payload)
        return payload

    def add_comment(self, issue_key: str, body: str) -> Dict[str, Any]:
        payload = {"action": "comment", "issue_key": issue_key, "body": body}
        self.calls.append(payload)
        return payload

    def update_fields(self, issue_key: str, fields: Dict[str, Any]) -> Dict[str, Any]:
        payload = {"action": "fields", "issue_key": issue_key, "fields": fields}
        self.calls.append(payload)
        return payload


def _normalize_issue_key(value: object) -> str | None:
    if value is None:
        return None
    candidate = str(value).strip().upper()
    return candidate if JIRA_KEY_PATTERN.fullmatch(candidate) else None


def extract_jira_keys(event: DevEvent) -> List[str]:
    candidates: List[str] = []
    text_sources: Iterable[str] = [
        event.title,
        event.branch,
        event.pr_body,
        *event.commit_messages,
    ]
    for text in text_sources:
        candidates.extend(match.group(1) for match in JIRA_KEY_PATTERN.finditer(text or ""))

    metadata_key = _normalize_issue_key(event.metadata.get("jira_key"))
    if metadata_key:
        candidates.append(metadata_key)

    metadata_keys = event.metadata.get("jira_keys")
    if isinstance(metadata_keys, Sequence) and not isinstance(metadata_keys, (str, bytes, bytearray)):
        for key in metadata_keys:
            normalized = _normalize_issue_key(key)
            if normalized:
                candidates.append(normalized)

    deduped: List[str] = []
    seen: set[str] = set()
    for key in candidates:
        normalized = key.upper()
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def summarize_event(event: DevEvent) -> str:
    details = [f"Event: {event.event_type}"]
    if event.title:
        details.append(f"Title: {event.title}")
    if event.branch:
        details.append(f"Branch: {event.branch}")
    if event.commit_messages:
        details.append("Commits: " + "; ".join(event.commit_messages))
    return " | ".join(details)


def build_idempotency_key(event: DevEvent) -> str:
    parts = [
        event.event_type.strip().lower(),
        event.title.strip(),
        event.branch.strip(),
        "|".join(message.strip() for message in event.commit_messages),
        event.pr_body.strip(),
        str(event.metadata.get("delivery_id", "")).strip(),
    ]
    return ":".join(parts)


def _get_status_for_event(event_type: str, status_map: Mapping[str, str]) -> str | None:
    status = status_map.get(event_type.lower())
    if not status:
        return None
    cleaned_status = status.strip()
    if not SAFE_STATUS_PATTERN.fullmatch(cleaned_status):
        raise ValueError(f"Unsafe Jira status configured for event type: {event_type}")
    return cleaned_status


def map_event_to_actions(
    event: DevEvent,
    status_map: Mapping[str, str] | None = None,
) -> List[Dict[str, Any]]:
    resolved_status_map = dict(DEFAULT_EVENT_STATUS_MAP)
    if status_map:
        resolved_status_map.update(status_map)

    actions: List[Dict[str, Any]] = [{"type": "comment", "body": summarize_event(event)}]
    status = _get_status_for_event(event.event_type, resolved_status_map)
    if status:
        actions.append({"type": "transition", "status": status})
    if event.event_type.lower() in {"pull_request_merged", "deployment_succeeded"}:
        actions.append({"type": "fields", "fields": {"labels": ["auto-updated"]}})
    if event.event_type.lower() in {"test_failed", "deployment_failed"}:
        actions.append({"type": "comment", "body": "Automation detected a failed validation step."})
    return actions


def process_event(
    event: DevEvent,
    jira_client: JiraClient,
    store: IdempotencyStore,
    status_map: Mapping[str, str] | None = None,
) -> List[Dict[str, Any]]:
    dedupe_key = build_idempotency_key(event)
    if store.seen(dedupe_key):
        return []

    keys = extract_jira_keys(event)
    if not keys:
        raise ValueError("No Jira issue key found in event payload")

    issue_key = keys[0]
    applied: List[Dict[str, Any]] = []
    for action in map_event_to_actions(event, status_map=status_map):
        if action["type"] == "transition":
            applied.append(jira_client.transition_issue(issue_key, action["status"]))
        elif action["type"] == "comment":
            applied.append(jira_client.add_comment(issue_key, action["body"]))
        elif action["type"] == "fields":
            applied.append(jira_client.update_fields(issue_key, action["fields"]))
    store.mark(dedupe_key)
    return applied

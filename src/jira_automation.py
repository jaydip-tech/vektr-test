"""Minimal Jira workflow automation scaffold.

This module provides a small, testable design for mapping development events
into Jira updates while keeping idempotency and security concerns explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
import re

JIRA_KEY_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+-\d+)\b")


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
    metadata_key = event.metadata.get("jira_key")
    if metadata_key:
        candidates.append(str(metadata_key))
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


def map_event_to_actions(event: DevEvent) -> List[Dict[str, Any]]:
    event_type = event.event_type.lower()
    actions: List[Dict[str, Any]] = [{"type": "comment", "body": summarize_event(event)}]
    if event_type in {"pull_request_merged", "deployment_succeeded"}:
        actions.append({"type": "transition", "status": "Done"})
        actions.append({"type": "fields", "fields": {"labels": ["auto-updated"]}})
    elif event_type in {"pull_request_opened", "branch_created"}:
        actions.append({"type": "transition", "status": "In Progress"})
    elif event_type in {"test_failed", "deployment_failed"}:
        actions.append({"type": "comment", "body": "Automation detected a failed validation step."})
    return actions


def process_event(event: DevEvent, jira_client: JiraClient, store: IdempotencyStore) -> List[Dict[str, Any]]:
    dedupe_key = f"{event.event_type}:{event.title}:{event.branch}:{'|'.join(event.commit_messages)}"
    if store.seen(dedupe_key):
        return []

    keys = extract_jira_keys(event)
    if not keys:
        raise ValueError("No Jira issue key found in event payload")

    issue_key = keys[0]
    applied: List[Dict[str, Any]] = []
    for action in map_event_to_actions(event):
        if action["type"] == "transition":
            applied.append(jira_client.transition_issue(issue_key, action["status"]))
        elif action["type"] == "comment":
            applied.append(jira_client.add_comment(issue_key, action["body"]))
        elif action["type"] == "fields":
            applied.append(jira_client.update_fields(issue_key, action["fields"]))
    store.mark(dedupe_key)
    return applied

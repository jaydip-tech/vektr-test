import unittest

from src.jira_automation import (
    DEFAULT_EVENT_STATUS_MAP,
    DevEvent,
    IdempotencyStore,
    MockJiraClient,
    build_idempotency_key,
    extract_jira_keys,
    map_event_to_actions,
    process_event,
)


class JiraAutomationTests(unittest.TestCase):
    def test_extract_jira_keys_from_multiple_sources(self):
        event = DevEvent(
            event_type="pull_request_opened",
            title="Implement payment fix for ABC-123",
            branch="feature/abc-123-fix",
            commit_messages=["Refine parser for XYZ-9", "No ticket here"],
            metadata={"jira_key": "ops-4", "jira_keys": ["qa-7", "bad key"]},
        )
        self.assertEqual(extract_jira_keys(event), ["ABC-123", "XYZ-9", "OPS-4", "QA-7"])

    def test_build_idempotency_key_prefers_delivery_id_when_present(self):
        event = DevEvent(
            event_type="pull_request_opened",
            title="Implement ABC-123",
            metadata={"delivery_id": "evt-123"},
        )
        self.assertTrue(build_idempotency_key(event).endswith(":evt-123"))

    def test_process_event_applies_actions_once(self):
        client = MockJiraClient()
        store = IdempotencyStore()
        event = DevEvent(
            event_type="pull_request_merged",
            title="Merge DEF-10 feature",
            branch="feature/def-10-feature",
            commit_messages=["Complete DEF-10 implementation"],
        )

        first = process_event(event, client, store)
        second = process_event(event, client, store)

        self.assertEqual(len(first), 3)
        self.assertEqual(second, [])
        self.assertEqual(client.calls[0]["action"], "comment")
        self.assertEqual(client.calls[1]["status"], "Done")
        self.assertEqual(client.calls[2]["fields"]["labels"], ["auto-updated"])

    def test_process_event_requires_jira_key(self):
        client = MockJiraClient()
        store = IdempotencyStore()
        event = DevEvent(event_type="branch_created", title="No linked ticket")
        with self.assertRaises(ValueError):
            process_event(event, client, store)

    def test_map_event_to_actions_supports_safe_status_override(self):
        event = DevEvent(event_type="pull_request_opened", title="ABC-1")
        actions = map_event_to_actions(event, status_map={"pull_request_opened": "Ready For QA"})
        self.assertEqual(actions[1], {"type": "transition", "status": "Ready For QA"})

    def test_map_event_to_actions_rejects_unsafe_status_override(self):
        event = DevEvent(event_type="pull_request_opened", title="ABC-1")
        with self.assertRaises(ValueError):
            map_event_to_actions(event, status_map={"pull_request_opened": "Done; drop table"})

    def test_default_status_map_is_not_mutated_by_override(self):
        event = DevEvent(event_type="pull_request_opened", title="ABC-1")
        map_event_to_actions(event, status_map={"pull_request_opened": "Review"})
        self.assertEqual(DEFAULT_EVENT_STATUS_MAP["pull_request_opened"], "In Progress")


if __name__ == "__main__":
    unittest.main()

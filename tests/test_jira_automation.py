import unittest

from src.jira_automation import DevEvent, IdempotencyStore, MockJiraClient, extract_jira_keys, process_event


class JiraAutomationTests(unittest.TestCase):
    def test_extract_jira_keys_from_multiple_sources(self):
        event = DevEvent(
            event_type="pull_request_opened",
            title="Implement payment fix for ABC-123",
            branch="feature/abc-123-fix",
            commit_messages=["Refine parser for XYZ-9", "No ticket here"],
            metadata={"jira_key": "OPS-4"},
        )
        self.assertEqual(extract_jira_keys(event), ["ABC-123", "XYZ-9", "OPS-4"])

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

    def test_process_event_requires_jira_key(self):
        client = MockJiraClient()
        store = IdempotencyStore()
        event = DevEvent(event_type="branch_created", title="No linked ticket")
        with self.assertRaises(ValueError):
            process_event(event, client, store)


if __name__ == "__main__":
    unittest.main()

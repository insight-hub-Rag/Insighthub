from app.core.models import RawRecord
from app.connectors.jira.transformer import JiraTransformer


def test_normalize_extracts_basic_fields():
    issue = {
        "key": "IH-1",
        "fields": {
            "summary": "Example issue",
            "description": {
                "type": "doc",
                "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": "Hello Jira"}]}
                ],
            },
            "status": {"name": "In Progress"},
            "priority": {"name": "High"},
            "assignee": {"displayName": "Alice"},
            "reporter": {"displayName": "Bob"},
            "issuetype": {"name": "Task"},
            "created": "2024-01-01T00:00:00.000Z",
            "updated": "2024-01-02T00:00:00.000Z",
            "comment": {"comments": []},
        },
    }

    normalized = JiraTransformer._normalize(issue)

    assert normalized["external_id"] == "IH-1"
    assert normalized["title"] == "Example issue"
    assert normalized["description"] == "Hello Jira"


def test_transform_creates_body_and_comment_chunks():
    record = RawRecord(
        source_type="jira",
        record_id="IH-2",
        raw_data={
            "key": "IH-2",
            "fields": {
                "summary": "Needs follow-up",
                "description": "Detailed description",
                "status": {"name": "To Do"},
                "priority": {"name": "Medium"},
                "assignee": {"displayName": "Alice"},
                "reporter": {"displayName": "Bob"},
                "issuetype": {"name": "Bug"},
                "created": "2024-01-01T00:00:00.000Z",
                "updated": "2024-01-02T00:00:00.000Z",
                "comment": {
                    "comments": [
                        {"author": {"displayName": "Carol"}, "body": "Looks good", "created": "2024-01-02T00:00:00.000Z"}
                    ]
                },
            },
        },
    )

    chunks = JiraTransformer().transform(record)

    assert len(chunks) >= 2
    assert any(c.metadata["chunk_type"] == "body" for c in chunks)
    assert any(c.metadata["chunk_type"] == "comment" for c in chunks)


import sys
sys.path.insert(0, ".")

import boto3
from botocore.stub import Stubber

from infrastructure.eventbridge import rules


def test_create_or_update_rule():
    events_client = boto3.client("events", region_name="us-east-1")
    lambda_client = boto3.client("lambda", region_name="us-east-1")

    stub_events = Stubber(events_client)
    stub_lambda = Stubber(lambda_client)

    connector_id = "abc-123"
    lambda_arn = "arn:aws:lambda:us-east-1:123456789012:function:sync_trigger"
    rule_arn = "arn:aws:events:us-east-1:123456789012:rule/insighthub-sync-abc-123"

    stub_events.add_response(
        "put_rule",
        {"RuleArn": rule_arn},
        {
            "Name": "insighthub-sync-abc-123",
            "ScheduleExpression": "rate(15 minutes)",
            "State": "ENABLED",
            "Description": "Sync automatique InsightHub — connecteur abc-123",
        },
    )
    stub_events.add_response(
        "put_targets",
        {"FailedEntryCount": 0, "FailedEntries": []},
        {
            "Rule": "insighthub-sync-abc-123",
            "Targets": [
                {
                    "Id": "sync-trigger-abc-123",
                    "Arn": lambda_arn,
                    "Input": '{"connector_id": "abc-123"}',
                }
            ],
        },
    )
    stub_lambda.add_response(
        "add_permission",
        {"Statement": "{}"},
        {
            "FunctionName": lambda_arn,
            "StatementId": "insighthub-eventbridge-abc-123",
            "Action": "lambda:InvokeFunction",
            "Principal": "events.amazonaws.com",
            "SourceArn": rule_arn,
        },
    )

    stub_events.activate()
    stub_lambda.activate()

    rules._client = lambda: events_client
    rules._lambda_client = lambda: lambda_client

    result_arn = rules.create_or_update_rule(
        connector_id, frequency_minutes=15, lambda_arn=lambda_arn
    )

    assert result_arn == rule_arn
    stub_events.assert_no_pending_responses()
    stub_lambda.assert_no_pending_responses()
    print("test_create_or_update_rule : OK")


def test_set_rule_enabled():
    events_client = boto3.client("events", region_name="us-east-1")
    stub = Stubber(events_client)

    stub.add_response("disable_rule", {}, {"Name": "insighthub-sync-abc-123"})
    stub.add_response("enable_rule", {}, {"Name": "insighthub-sync-abc-123"})
    stub.activate()

    rules._client = lambda: events_client

    rules.set_rule_enabled("abc-123", enabled=False)
    rules.set_rule_enabled("abc-123", enabled=True)

    stub.assert_no_pending_responses()
    print("test_set_rule_enabled : OK")


def test_delete_rule():
    events_client = boto3.client("events", region_name="us-east-1")
    stub = Stubber(events_client)

    stub.add_response(
        "remove_targets", {"FailedEntryCount": 0, "FailedEntries": []},
        {"Rule": "insighthub-sync-abc-123", "Ids": ["sync-trigger-abc-123"]},
    )
    stub.add_response("delete_rule", {}, {"Name": "insighthub-sync-abc-123"})
    stub.activate()

    rules._client = lambda: events_client

    rules.delete_rule("abc-123")

    stub.assert_no_pending_responses()
    print("test_delete_rule : OK")


if __name__ == "__main__":
    test_create_or_update_rule()
    test_set_rule_enabled()
    test_delete_rule()
    print("\n✅ Tous les tests eventbridge/rules.py passent (simulés, sans compte AWS)")
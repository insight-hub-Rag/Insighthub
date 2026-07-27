

import json
import logging
from typing import Optional

import boto3
from botocore.exceptions import ClientError

from config import settings

logger = logging.getLogger(__name__)

RULE_NAME_PREFIX = "insighthub-sync-"
LAMBDA_PERMISSION_STATEMENT_PREFIX = "insighthub-eventbridge-"


def _rule_name(connector_id: str) -> str:
    return f"{RULE_NAME_PREFIX}{connector_id}"


def _schedule_expression(frequency_minutes: int) -> str:
    """AWS exige le singulier quand la valeur est 1 (ex: 'rate(1 hour)',
    pas 'rate(1 hours)')."""
    if frequency_minutes % 60 == 0:
        hours = frequency_minutes // 60
        unit = "hour" if hours == 1 else "hours"
        return f"rate({hours} {unit})"
    unit = "minute" if frequency_minutes == 1 else "minutes"
    return f"rate({frequency_minutes} {unit})"


def _client():
    return boto3.client(
        "events",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def _lambda_client():
    return boto3.client(
        "lambda",
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )


def create_or_update_rule(
    connector_id: str,
    frequency_minutes: int,
    lambda_arn: str,
    enabled: bool = True,
) -> str:
    """
    Crée la règle si elle n'existe pas, ou met à jour sa fréquence si
    elle existe déjà (idempotent — rejouable sans erreur). Retourne
    l'ARN de la règle créée/mise à jour.
    """
    client = _client()
    rule_name = _rule_name(connector_id)

    response = client.put_rule(
        Name=rule_name,
        ScheduleExpression=_schedule_expression(frequency_minutes),
        State="ENABLED" if enabled else "DISABLED",
        Description=f"Sync automatique InsightHub — connecteur {connector_id}",
    )
    rule_arn = response["RuleArn"]

    client.put_targets(
        Rule=rule_name,
        Targets=[
            {
                "Id": f"sync-trigger-{connector_id}",
                "Arn": lambda_arn,
                "Input": json.dumps({"connector_id": connector_id}),
            }
        ],
    )

    _ensure_lambda_permission(rule_arn, connector_id, lambda_arn)

    logger.info(
        f"[EventBridge] Règle {rule_name} créée/mise à jour "
        f"(fréquence={frequency_minutes}min, enabled={enabled})"
    )
    return rule_arn


def set_rule_enabled(connector_id: str, enabled: bool) -> None:
    """Utilisé par le toggle actif/inactif de l'UI — met la règle en
    pause SANS la supprimer (garde la config de fréquence intacte)."""
    client = _client()
    rule_name = _rule_name(connector_id)
    if enabled:
        client.enable_rule(Name=rule_name)
    else:
        client.disable_rule(Name=rule_name)
    logger.info(f"[EventBridge] Règle {rule_name} {'activée' if enabled else 'mise en pause'}")


def delete_rule(connector_id: str) -> None:
    """Supprime la règle et sa cible — appelé quand un connecteur est
    supprimé de l'écran Connecteurs. Tolère l'absence de règle (déjà
    supprimée, ou jamais créée) sans lever d'erreur."""
    client = _client()
    rule_name = _rule_name(connector_id)

    try:
        client.remove_targets(Rule=rule_name, Ids=[f"sync-trigger-{connector_id}"])
        client.delete_rule(Name=rule_name)
        logger.info(f"[EventBridge] Règle {rule_name} supprimée")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            logger.info(f"[EventBridge] Règle {rule_name} déjà absente, rien à supprimer")
        else:
            raise


def _ensure_lambda_permission(rule_arn: str, connector_id: str, lambda_arn: str) -> None:
    """
    EventBridge a besoin d'une permission explicite pour invoquer la
    Lambda. add_permission lève ResourceConflictException si la
    permission existe déjà (rejouable) — on l'ignore, c'est le
    comportement attendu en cas de mise à jour d'une règle existante.
    """
    statement_id = f"{LAMBDA_PERMISSION_STATEMENT_PREFIX}{connector_id}"
    try:
        _lambda_client().add_permission(
            FunctionName=lambda_arn,
            StatementId=statement_id,
            Action="lambda:InvokeFunction",
            Principal="events.amazonaws.com",
            SourceArn=rule_arn,
        )
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
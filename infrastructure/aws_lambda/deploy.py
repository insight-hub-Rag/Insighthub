import io 
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, ".")

import boto3
from botocore.exceptions import ClientError

from config import settings

FUNCTION_NAME = "insighthub-sync-trigger"
ROLE_NAME = "insighthub-sync-trigger-role"
HANDLER_PATH = os.path.join(os.path.dirname(__file__), "sync_trigger", "handler.py")

ASSUME_ROLE_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": "sts:AssumeRole",
    }],
})


# elle fait un simple appel HTTP sortant vers le backend.
LOGS_POLICY_ARN = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"


def _iam_client():
    return boto3.client(
        "iam",
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


def _build_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(HANDLER_PATH, arcname="handler.py")
    return buffer.getvalue()


def _ensure_role() -> str:
    iam = _iam_client()
    try:
        response = iam.get_role(RoleName=ROLE_NAME)
        print(f"Rôle IAM existant réutilisé : {ROLE_NAME}")
        return response["Role"]["Arn"]
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            raise

    print(f"Création du rôle IAM : {ROLE_NAME}")
    response = iam.create_role(
        RoleName=ROLE_NAME,
        AssumeRolePolicyDocument=ASSUME_ROLE_POLICY,
        Description="Rôle minimal pour la Lambda InsightHub sync_trigger (logs uniquement)",
    )
    iam.attach_role_policy(RoleName=ROLE_NAME, PolicyArn=LOGS_POLICY_ARN)

    # IAM est éventuellement cohérent — le rôle peut ne pas être encore
    # utilisable immédiatement après sa création. Petite pause pour
    # éviter un échec de create_function juste après.
    print("Attente de la propagation IAM (10s)...")
    time.sleep(10)

    return response["Role"]["Arn"]


def deploy() -> str:
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        raise RuntimeError(
            "Identifiants AWS manquants (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY "
            "dans .env) — impossible de déployer."
        )

    backend_url = os.environ.get("BACKEND_URL")
    if not backend_url:
        raise RuntimeError(
            "BACKEND_URL manquant — définis l'URL publique de ton backend "
           
        )

    role_arn = _ensure_role()
    zip_bytes = _build_zip()
    lambda_client = _lambda_client()

    env_vars = {"BACKEND_URL": backend_url}
    if settings.lambda_sync_secret:
        env_vars["SYNC_SECRET"] = settings.lambda_sync_secret

    try:
        lambda_client.get_function(FunctionName=FUNCTION_NAME)
        exists = True
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
        exists = False

    if exists:
        print(f"Mise à jour de la fonction existante : {FUNCTION_NAME}")
        lambda_client.update_function_code(FunctionName=FUNCTION_NAME, ZipFile=zip_bytes)
        lambda_client.update_function_configuration(
            FunctionName=FUNCTION_NAME,
            Environment={"Variables": env_vars},
            Timeout=600,
        )
        response = lambda_client.get_function(FunctionName=FUNCTION_NAME)
        function_arn = response["Configuration"]["FunctionArn"]
    else:
        print(f"Création de la fonction : {FUNCTION_NAME}")
        response = lambda_client.create_function(
            FunctionName=FUNCTION_NAME,
            Runtime="python3.12",
            Role=role_arn,
            Handler="handler.lambda_handler",
            Code={"ZipFile": zip_bytes},
            Timeout=600,  # une sync complète peut prendre du temps
            MemorySize=128,  # aucun calcul lourd, juste un appel HTTP
            Environment={"Variables": env_vars},
            Description="Déclenche une synchronisation InsightHub planifiée par EventBridge",
        )
        function_arn = response["FunctionArn"]

    print(f"\n✅ Lambda déployée : {function_arn}")
    print(f"   -> Mets cette valeur dans .env : SYNC_LAMBDA_ARN={function_arn}")
    return function_arn


if __name__ == "__main__":
    deploy()
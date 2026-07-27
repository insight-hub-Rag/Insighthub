

import sys
sys.path.insert(0, ".")

import boto3
from botocore.exceptions import ClientError

from config import settings


def check(service_name: str, action_description: str, call):
    try:
        call()
        print(f"✅ {service_name:12} — {action_description}")
        return True
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("AccessDenied", "UnauthorizedOperation", "AccessDeniedException"):
            print(f"❌ {service_name:12} — {action_description} : ACCÈS REFUSÉ ({code})")
        else:
            # Une erreur différente d'un refus de droit (ex: ressource
            # introuvable) veut souvent dire que l'appel était AUTORISÉ,
            # juste que la ressource testée n'existe pas — on le signale
            # sans le compter comme un vrai problème de permission.
            print(f"⚠️  {service_name:12} — {action_description} : {code} (probablement OK, pas un souci de droit)")
        return False
    except Exception as e:
        print(f"❌ {service_name:12} — {action_description} : erreur inattendue ({e})")
        return False


def main():
    if not settings.aws_access_key_id or not settings.aws_secret_access_key:
        print("❌ Aucune clé AWS configurée dans .env (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY)")
        return

    kwargs = dict(
        region_name=settings.aws_region,
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )

    print(f"Région : {settings.aws_region}\n")

    iam = boto3.client("iam", **kwargs)
    check("IAM", "lister les rôles (droit de lecture minimal)", lambda: iam.list_roles(MaxItems=1))

    lambda_client = boto3.client("lambda", **kwargs)
    check("Lambda", "lister les fonctions", lambda: lambda_client.list_functions(MaxItems=1))

    events = boto3.client("events", **kwargs)
    check("EventBridge", "lister les règles", lambda: events.list_rules(Limit=1))

   


if __name__ == "__main__":
    main()
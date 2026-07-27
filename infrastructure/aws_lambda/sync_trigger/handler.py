

import json
import os
import urllib.error
import urllib.request


def lambda_handler(event, context):
    connector_id = event.get("connector_id")
    if not connector_id:
        return {"statusCode": 400, "body": json.dumps({"error": "connector_id manquant dans l'event"})}

    backend_url = os.environ["BACKEND_URL"].rstrip("/")
    sync_secret = os.environ.get("SYNC_SECRET", "")

    url = f"{backend_url}/connectors/{connector_id}/sync"
    headers = {"Content-Type": "application/json"}
    if sync_secret:
        headers["X-Sync-Secret"] = sync_secret

    req = urllib.request.Request(url, method="POST", headers=headers, data=b"")

    try:
        # Une sync complète peut prendre du temps (plusieurs projets,
        # beaucoup de tickets) — timeout large pour ne pas couper une
        # sync légitime en cours. Le timeout MAX d'une Lambda elle-même
        # (configuré côté AWS, jusqu'à 15 min) est la vraie limite haute.
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read())
            print(f"[SyncTrigger] connector_id={connector_id} -> {body}")
            return {"statusCode": resp.status, "body": json.dumps(body)}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"[SyncTrigger] Échec HTTP {e.code} pour connector_id={connector_id} : {error_body}")
        return {"statusCode": e.code, "body": error_body}

    except Exception as e:
        print(f"[SyncTrigger] Erreur inattendue pour connector_id={connector_id} : {e}")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}
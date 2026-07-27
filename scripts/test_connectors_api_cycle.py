

import httpx

BASE_URL = "http://localhost:8000"
client = httpx.Client(base_url=BASE_URL, timeout=10)


def main():
    # Nettoyage préventif : si un run précédent a planté avant d'atteindre
    # le DELETE final (ex: erreur de config), une ligne de test peut
    # rester en base et faire échouer le CREATE (contrainte UNIQUE sur
    # source_type + instance_label). On la supprime si elle existe déjà,
    # pour que ce script reste rejouable sans intervention manuelle.
    existing = client.get("/connectors").json()
    for c in existing:
        if c["instance_label"] == "Jira — Test Cycle E2E":
            client.delete(f"/connectors/{c['id']}")
            print("(nettoyage d'un résidu du run précédent)")

    print("1. CREATE — POST /connectors")
    resp = client.post("/connectors", json={
        "source_type": "jira",
        "instance_label": "Jira — Test Cycle E2E",
        "auth_fields": {
            "url": "https://acme.atlassian.net",
            "email": "bot@acme.com",
            "token": "fake-token-xyz",
        },
        "sync_scope": {"projects": ["INFRA", "DEV"]},
        "sync_frequency_minutes": 15,
    })
    print(f"   status={resp.status_code}")
    assert resp.status_code == 201, resp.text
    connector = resp.json()
    connector_id = connector["id"]
    print(f"   id={connector_id}")
    print(f"   auth_fields (masqué) : {connector['auth_fields']}")
    assert connector["auth_fields"]["token"] != "fake-token-xyz", "Le token ne doit JAMAIS revenir en clair !"
    assert connector["status"] == "pending", "Jamais synchronisé -> statut 'pending' attendu"

    print("\n2. LIST — GET /connectors")
    resp = client.get("/connectors")
    print(f"   status={resp.status_code} | {len(resp.json())} connecteur(s)")
    assert resp.status_code == 200
    assert any(c["id"] == connector_id for c in resp.json())

    print("\n3. GET DETAIL — GET /connectors/{id}")
    resp = client.get(f"/connectors/{connector_id}")
    print(f"   status={resp.status_code}")
    assert resp.status_code == 200
    assert resp.json()["instance_label"] == "Jira — Test Cycle E2E"

    print("\n4. UPDATE — PATCH /connectors/{id}")
    resp = client.patch(f"/connectors/{connector_id}", json={
        "sync_frequency_minutes": 60,
    })
    print(f"   status={resp.status_code}")
    assert resp.status_code == 200
    assert resp.json()["sync_frequency_minutes"] == 60

    print("\n5. TOGGLE — PATCH /connectors/{id}/toggle?enabled=false")
    resp = client.patch(f"/connectors/{connector_id}/toggle", params={"enabled": "false"})
    print(f"   status={resp.status_code}")
    assert resp.status_code == 200
    assert resp.json()["status"] == "paused"

    print("\n6. DELETE — DELETE /connectors/{id}")
    resp = client.delete(f"/connectors/{connector_id}")
    print(f"   status={resp.status_code}")
    assert resp.status_code == 204

    print("\n7. GET après suppression — doit renvoyer 404")
    resp = client.get(f"/connectors/{connector_id}")
    print(f"   status={resp.status_code}")
    assert resp.status_code == 404

    print("\n✅ CYCLE COMPLET RÉUSSI — les 7 étapes sont passées")


if __name__ == "__main__":
    main()
from app.config import settings

FINGERPRINT = "AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99:AA:BB:CC:DD:EE:FF:00:11:22:33:44:55:66:77:88:99"


def test_assetlinks_absent_until_configured(client):
    assert client.get("/.well-known/assetlinks.json").status_code == 404


def test_assetlinks_lists_package_and_fingerprints(client, monkeypatch):
    monkeypatch.setattr(settings, "android_cert_fingerprints", f" {FINGERPRINT.lower()}, {FINGERPRINT} ")
    response = client.get("/.well-known/assetlinks.json")
    assert response.status_code == 200
    body = response.json()
    assert body == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": "ie.yarodev.pam",
                "sha256_cert_fingerprints": [FINGERPRINT, FINGERPRINT],
            },
        }
    ]


def test_assetlinks_is_public(client):
    # No auth: Chrome fetches it anonymously.
    assert client.get("/.well-known/assetlinks.json").status_code in (200, 404)

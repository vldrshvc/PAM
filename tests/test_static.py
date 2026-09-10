def test_root_redirects_to_app(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/"


def test_app_shell_is_served_without_auth(client):
    response = client.get("/app/")
    assert response.status_code == 200
    assert "<title>PAM</title>" in response.text
    assert client.get("/app/manifest.json").json()["start_url"] == "/app/"

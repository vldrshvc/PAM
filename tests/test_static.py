from pathlib import Path

import app.main
from app.webclient import fingerprint


def test_root_redirects_to_app(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "/app/"


def test_app_shell_is_served_without_auth(client):
    response = client.get("/app/")
    assert response.status_code == 200
    assert "<title>PAM</title>" in response.text
    assert client.get("/app/manifest.json").json()["start_url"] == "/app/"


# Caching. A browser given only an ETag applies heuristic freshness and may
# reuse a file for days without asking, which is how an installed phone keeps
# running a deploy that has already been replaced.

STATIC = Path(app.main.__file__).parent / "static"


def test_shell_is_always_revalidated(client):
    for path in ("/app/", "/app/index.html", "/app/manifest.json"):
        assert client.get(path).headers["cache-control"] == "no-cache", path


def test_shell_links_carry_the_hash_of_the_file_it_points_at(client):
    html = client.get("/app/").text
    for name in ("app.js", "styles.css", "fonts.css"):
        assert f"{name}?v={fingerprint(STATIC / name)}" in html, name


def test_an_asset_asked_for_by_its_hash_may_be_cached_forever(client):
    response = client.get(f"/app/app.js?v={fingerprint(STATIC / 'app.js')}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


def test_an_asset_asked_for_without_its_hash_is_revalidated(client):
    assert client.get("/app/app.js").headers["cache-control"] == "no-cache"
    assert client.get("/app/app.js?v=stale123").headers["cache-control"] == "no-cache"


def test_an_unchanged_shell_answers_304(client):
    etag = client.get("/app/").headers["etag"]
    again = client.get("/app/", headers={"If-None-Match": etag})
    assert again.status_code == 304
    assert again.headers["cache-control"] == "no-cache"

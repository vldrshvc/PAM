"""Serving the web client so that a deploy actually reaches the phone.

Static files answered with only `ETag` and `Last-Modified` let a browser apply
*heuristic freshness* (RFC 9111 §4.2.2): with no `Cache-Control` it may reuse a
cached copy for roughly a tenth of the file's age without asking the server at
all, so a redeploy stays invisible for days. An installed PWA is served by the
same browser cache, which survives uninstalling and reinstalling the app, and
because each file ages independently you can end up with new markup driving old
scripts.

So the shell is always revalidated and everything it references is
fingerprinted. `index.html` and `manifest.json` go out as `no-cache` — still
cheap, because an unchanged one answers 304 — and their links carry the content
hash of the file they point at, which earns that file a year of `immutable`
caching. A new deploy changes the hash, the URL, and therefore the cache entry;
nothing has to expire for the new version to load.
"""

import hashlib
from pathlib import Path
from urllib.parse import parse_qs

from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

# Only files the shell links to are worth fingerprinting; anything else is
# served unversioned and therefore revalidated, which is the safe default.
VERSIONED = ("app.js", "styles.css", "fonts.css")
# Always revalidate: these name the versioned URLs, so they must never be stale.
SHELL = ("index.html", "manifest.json")

IMMUTABLE = "public, max-age=31536000, immutable"
REVALIDATE = "no-cache"


def fingerprint(path: Path) -> str:
    """A short content hash. Same bytes, same URL; one byte different, new URL."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def versioned_index(directory: Path, versions: dict[str, str]) -> bytes:
    """`index.html` with each asset link carrying that asset's hash."""
    html = (directory / "index.html").read_text(encoding="utf-8")
    for name, version in versions.items():
        html = html.replace(f'"{name}"', f'"{name}?v={version}"')
    return html.encode("utf-8")


class WebClient(StaticFiles):
    """The client's static files, each answered with how long it may be reused.

    The versions are read once at start-up: the files are baked into the image
    and cannot change under a running process.
    """

    def __init__(self, directory: Path) -> None:
        super().__init__(directory=directory, html=True)
        self.versions = {name: fingerprint(directory / name) for name in VERSIONED}
        self.index = versioned_index(directory, self.versions)
        self.index_etag = f'"{hashlib.sha256(self.index).hexdigest()}"'

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path in ("", ".", "index.html"):
            return self._index_response(scope)
        return await super().get_response(path, scope)

    def _index_response(self, scope: Scope) -> Response:
        headers = {"Cache-Control": REVALIDATE, "ETag": self.index_etag}
        if_none_match = next(
            (v.decode() for k, v in scope.get("headers", ()) if k == b"if-none-match"), ""
        )
        # A quoted list, per the header's grammar; the shell is small enough
        # that an exact-match check is all it needs.
        if self.index_etag in [tag.strip() for tag in if_none_match.split(",")]:
            return Response(status_code=304, headers=headers)
        return Response(self.index, media_type="text/html; charset=utf-8", headers=headers)

    def file_response(self, full_path, stat_result, scope: Scope, status_code: int = 200) -> Response:
        response = super().file_response(full_path, stat_result, scope, status_code)
        response.headers["Cache-Control"] = self._caching(Path(full_path).name, scope)
        return response

    def _caching(self, name: str, scope: Scope) -> str:
        """A file may be cached forever only when asked for by its own hash."""
        if name in SHELL:
            return REVALIDATE
        wanted = self.versions.get(name)
        asked = parse_qs(scope.get("query_string", b"").decode()).get("v", [None])[0]
        return IMMUTABLE if wanted is not None and asked == wanted else REVALIDATE

from fastapi import APIRouter, HTTPException, status

from app.config import settings

router = APIRouter(tags=["android"])


@router.get("/.well-known/assetlinks.json", include_in_schema=False)
def asset_links() -> list[dict]:
    """Tells Chrome the Android app may open this site full screen.
    Served only when signing-certificate fingerprints are configured."""
    fingerprints = [f.strip().upper() for f in settings.android_cert_fingerprints.split(",") if f.strip()]
    if not fingerprints:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")
    return [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": settings.android_package_name,
                "sha256_cert_fingerprints": fingerprints,
            },
        }
    ]

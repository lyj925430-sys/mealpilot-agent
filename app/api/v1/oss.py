from datetime import timedelta
from pathlib import PurePosixPath

import alibabacloud_oss_v2 as oss
from fastapi import APIRouter, HTTPException, Query

from app.core.settings import settings


router = APIRouter()

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}


def _validate_filename(filename: str) -> str:
    cleaned = filename.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="filename is required")

    path = PurePosixPath(cleaned)
    if path.name != cleaned or cleaned.startswith((".", "/")) or "\\" in cleaned:
        raise HTTPException(status_code=400, detail="filename must be a simple file name")

    ext = cleaned.rsplit(".", 1)[-1].lower() if "." in cleaned else ""
    if ext not in CONTENT_TYPES:
        raise HTTPException(status_code=400, detail="unsupported image type")

    return cleaned


def _create_client() -> oss.Client:
    cfg = oss.config.load_default()
    cfg.credentials_provider = oss.credentials.EnvironmentVariableCredentialsProvider()
    cfg.region = settings.oss_region
    return oss.Client(cfg)


@router.get("/oss/presign")
def presign_upload(
    filename: str = Query(..., min_length=1, max_length=200),
):
    object_name = _validate_filename(filename)

    if not settings.oss_ready:
        raise HTTPException(status_code=503, detail="OSS_BUCKET is not configured")

    ext = object_name.rsplit(".", 1)[-1].lower()
    content_type = CONTENT_TYPES[ext]

    try:
        pre_result = _create_client().presign(
            oss.PutObjectRequest(
                bucket=settings.oss_bucket,
                key=object_name,
                content_type=content_type,
            ),
            expires=timedelta(seconds=settings.oss_presign_expires_seconds),
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="failed to create OSS upload URL") from exc

    return {
        "uploadUrl": pre_result.url.strip('"'),
        "contentType": content_type,
        "accessUrl": f"https://{settings.oss_bucket}.{settings.oss_endpoint}/{object_name}",
        "expiresIn": settings.oss_presign_expires_seconds,
    }

from datetime import timedelta
from pathlib import PurePosixPath
from uuid import uuid4

import alibabacloud_oss_v2 as oss
from fastapi import APIRouter, File, HTTPException, Query, UploadFile

from app.core.settings import settings


router = APIRouter()

CONTENT_TYPES = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "gif": "image/gif",
    "webp": "image/webp",
}

MAX_UPLOAD_BYTES = 8 * 1024 * 1024


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


def _access_url(object_name: str) -> str:
    return f"https://{settings.oss_bucket}.{settings.oss_endpoint}/{object_name}"


def _oss_error_detail(exc: Exception) -> str:
    if isinstance(exc, oss.exceptions.ServiceError):
        parts = ["OSS upload failed"]
        if exc.status_code:
            parts.append(f"status={exc.status_code}")
        if exc.code:
            parts.append(f"code={exc.code}")
        if exc.message:
            parts.append(f"message={exc.message}")
        if exc.request_id:
            parts.append(f"request_id={exc.request_id}")
        return ", ".join(parts)

    if isinstance(exc, oss.exceptions.RequestError):
        detail = exc.unwrap()
        return f"OSS request failed: {detail or exc}"

    if isinstance(exc, oss.exceptions.OperationError):
        detail = exc.unwrap()
        return f"OSS operation failed: {detail or exc}"

    if isinstance(exc, oss.exceptions.CredentialsBaseError):
        return "OSS credentials are missing or invalid. Please check OSS_ACCESS_KEY_ID and OSS_ACCESS_KEY_SECRET."

    return f"failed to upload image to OSS: {exc.__class__.__name__}"


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
        "accessUrl": _access_url(object_name),
        "expiresIn": settings.oss_presign_expires_seconds,
    }


@router.post("/oss/upload")
async def upload_image(file: UploadFile = File(...)):
    object_name = _validate_filename(file.filename or "")

    if not settings.oss_ready:
        raise HTTPException(status_code=503, detail="OSS_BUCKET is not configured")

    ext = object_name.rsplit(".", 1)[-1].lower()
    content_type = file.content_type or CONTENT_TYPES[ext]
    if content_type not in CONTENT_TYPES.values():
        raise HTTPException(status_code=400, detail="unsupported image content type")

    body = await file.read(MAX_UPLOAD_BYTES + 1)
    if not body:
        raise HTTPException(status_code=400, detail="empty file")
    if len(body) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="image is too large")

    stored_name = f"uploads/{uuid4().hex}.{ext}"

    try:
        _create_client().put_object(
            oss.PutObjectRequest(
                bucket=settings.oss_bucket,
                key=stored_name,
                content_type=content_type,
                content_length=len(body),
                body=body,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_oss_error_detail(exc)) from exc

    return {
        "accessUrl": _access_url(stored_name),
        "contentType": content_type,
        "size": len(body),
    }


@router.get("/oss/diagnose")
def diagnose_oss():
    if not settings.oss_ready:
        raise HTTPException(status_code=503, detail="OSS_BUCKET is not configured")

    object_name = f"diagnostics/{uuid4().hex}.txt"
    body = b"ok"
    try:
        _create_client().put_object(
            oss.PutObjectRequest(
                bucket=settings.oss_bucket,
                key=object_name,
                content_type="text/plain",
                content_length=len(body),
                body=body,
            )
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=_oss_error_detail(exc)) from exc

    return {
        "ok": True,
        "bucket": settings.oss_bucket,
        "region": settings.oss_region,
        "endpoint": settings.oss_endpoint,
        "object": object_name,
    }

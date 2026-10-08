"""Object storage, for moving macOS VMs between Macs (server/macos.py, move).

ZOO_OBJECT_STORE is s3://<bucket>[/<prefix>], on AWS S3 or, with ZOO_S3_ENDPOINT (e.g. a MinIO or R2 URL), any
S3-compatible store. Credentials come from AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY (and AWS_SESSION_TOKEN), or
the pod's identity on EKS (kms.aws_credentials); the region from ZOO_S3_REGION, else AWS_REGION, else us-east-1.

The API never carries the data: it presigns URLs, and the Macs upload and download with curl."""

import hashlib
import hmac
import os
from datetime import UTC, datetime
from urllib.parse import quote, urlparse

import httpx

from server.kms import aws_credentials, signing_key

EXPIRES = 6 * 3600


def configured() -> bool:
    return os.environ.get("ZOO_OBJECT_STORE", "").startswith("s3://")


def region() -> str:
    return os.environ.get("ZOO_S3_REGION") or os.environ.get("AWS_REGION") or "us-east-1"


def location(key: str) -> tuple[str, str]:
    """The host and path of an object, under ZOO_OBJECT_STORE's prefix: path-style on a custom endpoint, and
    virtual-hosted on AWS."""
    target = urlparse(os.environ["ZOO_OBJECT_STORE"])
    bucket, prefix = target.netloc, target.path.strip("/")
    name = f"{prefix}/{key}" if prefix else key
    endpoint = os.environ.get("ZOO_S3_ENDPOINT", "").rstrip("/")
    if endpoint:
        return urlparse(endpoint).netloc, f"/{bucket}/{name}"
    return f"{bucket}.s3.{region()}.amazonaws.com", f"/{name}"


def presign_url(
    method: str,
    host: str,
    path: str,
    region: str,
    access_key: str,
    secret_key: str,
    amz_date: str,
    expires: int,
    token: str | None = None,
    scheme: str = "https",
) -> str:
    """A SigV4 query-string presigned URL (signed headers: host; payload: UNSIGNED-PAYLOAD)."""
    scope = f"{amz_date[:8]}/{region}/s3/aws4_request"
    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    if token:
        params["X-Amz-Security-Token"] = token
    query = "&".join(f"{quote(k, safe='')}={quote(v, safe='')}" for k, v in sorted(params.items()))
    uri = quote(path, safe="/")
    canonical = "\n".join([method, uri, query, f"host:{host}", "", "host", "UNSIGNED-PAYLOAD"])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    signature = hmac.new(signing_key(secret_key, amz_date[:8], region, "s3"), to_sign.encode(), hashlib.sha256)
    return f"{scheme}://{host}{uri}?{query}&X-Amz-Signature={signature.hexdigest()}"


def presign(method: str, key: str, expires: int = EXPIRES) -> str:
    access_key, secret_key, session_token = aws_credentials("object storage")
    host, path = location(key)
    scheme = urlparse(os.environ.get("ZOO_S3_ENDPOINT") or "https://").scheme or "https"
    return presign_url(
        method,
        host,
        path,
        region(),
        access_key,
        secret_key,
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"),
        expires,
        session_token,
        scheme,
    )


def delete(key: str):
    response = httpx.delete(presign("DELETE", key, 600), timeout=30)
    if response.status_code not in (200, 204, 404):
        raise RuntimeError(f"couldn't delete {key} from object storage: {response.status_code} {response.text[:300]}")

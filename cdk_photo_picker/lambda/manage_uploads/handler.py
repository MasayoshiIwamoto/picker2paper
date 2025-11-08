import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List

import boto3

s3 = boto3.client("s3")
BUCKET = os.environ.get("UPLOAD_BUCKET")
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "*")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
UPLOAD_PREFIX = os.environ.get("UPLOAD_PREFIX", "uploads/")
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed/")
MAX_ITEMS = int(os.environ.get("MAX_ITEMS", "200"))
DEFAULT_PAGE_SIZE = 10
ALLOWED_EMAIL_DOMAINS = {
    d.strip().lower()
    for d in (os.environ.get("ALLOWED_EMAIL_DOMAINS") or "").split(",")
    if d.strip()
}
ALLOWED_EMAILS = {
    e.strip().lower()
    for e in (os.environ.get("ALLOWED_EMAILS") or "").split(",")
    if e.strip()
}


def _response(status: int, body: Dict):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": ALLOW_ORIGIN,
            "access-control-allow-headers": "authorization,content-type",
            "access-control-allow-methods": "OPTIONS,GET,DELETE",
        },
        "body": json.dumps(body),
    }


def _verify_google_id_token(id_token: str):
    if not id_token:
        return False, {"error": "missing id token"}
    url = f"https://oauth2.googleapis.com/tokeninfo?id_token={id_token}"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return False, {"error": f"tokeninfo http {exc.code}"}
    except Exception as exc:
        return False, {"error": str(exc)}

    aud = data.get("aud")
    iss = data.get("iss")
    exp = int(data.get("exp", "0")) if data.get("exp") else 0
    now = int(time.time())
    if GOOGLE_CLIENT_ID and aud != GOOGLE_CLIENT_ID:
        return False, {"error": "invalid audience"}
    if iss not in ("accounts.google.com", "https://accounts.google.com"):
        return False, {"error": "invalid issuer"}
    if exp and now > exp:
        return False, {"error": "token expired"}
    return True, data


def _list_objects(prefix: str) -> List[Dict]:
    items: List[Dict] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key")
            if not key or key.endswith("/"):
                continue
            items.append(obj)
    return items


def _generate_get_url(key: str) -> str:
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET, "Key": key},
        ExpiresIn=600,
    )


def _list_uploads(limit: int, offset: int = 0):
    uploads = _list_objects(UPLOAD_PREFIX)
    processed_items = _list_objects(PROCESSED_PREFIX)
    processed_map = {
        os.path.basename(item["Key"]): item for item in processed_items
    }

    entries = []
    sorted_uploads = sorted(
        uploads,
        key=lambda o: o.get("LastModified", datetime.now(timezone.utc)),
        reverse=True,
    )

    sliced = sorted_uploads[offset: offset + limit]

    for obj in sliced:
        key = obj["Key"]
        base_name = os.path.basename(key)
        root, _ext = os.path.splitext(base_name)
        processed_name = f"{(root or base_name)}.bmp"
        processed_key = f"{PROCESSED_PREFIX}{processed_name}"
        processed_obj = processed_map.get(processed_name)
        entry = {
            "key": key,
            "size": obj.get("Size", 0),
            "lastModified": obj.get("LastModified").isoformat() if obj.get("LastModified") else None,
            "downloadUrl": _generate_get_url(key),
            "etag": obj.get("ETag", "").strip('"'),
        }
        if processed_obj:
            entry.update({
                "processedKey": processed_key,
                "processedSize": processed_obj.get("Size", 0),
                "processedLastModified": processed_obj.get("LastModified").isoformat() if processed_obj.get("LastModified") else None,
                "processedUrl": _generate_get_url(processed_key),
            })
        entries.append(entry)
    return entries, len(sorted_uploads)


def _delete_upload(key: str):
    removed = []
    s3.delete_object(Bucket=BUCKET, Key=key)
    removed.append(key)
    base_name = os.path.basename(key)
    root, _ext = os.path.splitext(base_name)
    processed_key = f"{PROCESSED_PREFIX}{(root or base_name)}.bmp"
    try:
        s3.delete_object(Bucket=BUCKET, Key=processed_key)
        removed.append(processed_key)
    except s3.exceptions.NoSuchKey:
        pass
    except Exception as exc:
        return removed, str(exc)
    return removed, None


def handler(event, _context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"ok": True})

    headers = event.get("headers") or {}
    auth = headers.get("Authorization") or headers.get("authorization")
    if not auth or not auth.lower().startswith("bearer "):
        return _response(401, {"error": "missing Authorization bearer"})
    id_token = auth.split(" ", 1)[1].strip()
    ok, claims = _verify_google_id_token(id_token)
    if not ok:
        claims.setdefault("error", "invalid id token")
        return _response(401, claims)

    email = (claims.get("email") or "").lower()
    if ALLOWED_EMAIL_DOMAINS:
        if not email or "@" not in email:
            return _response(403, {"error": "email claim required"})
        domain = email.split("@")[-1]
        if domain not in ALLOWED_EMAIL_DOMAINS:
            return _response(403, {"error": "email domain not allowed", "email": email})
    if ALLOWED_EMAILS and email not in ALLOWED_EMAILS:
        return _response(403, {"error": "email not allowed", "email": email})

    if not BUCKET:
        return _response(500, {"error": "UPLOAD_BUCKET not set"})

    method = event.get("httpMethod")
    try:
        if method == "GET":
            params = event.get("queryStringParameters") or {}
            try:
                limit = int(params.get("limit", DEFAULT_PAGE_SIZE))
            except Exception:
                limit = DEFAULT_PAGE_SIZE
            try:
                offset = int(params.get("offset", 0))
            except Exception:
                offset = 0
            limit = max(1, min(limit, MAX_ITEMS))
            offset = max(0, offset)

            items, total_count = _list_uploads(limit, offset)
            next_offset = offset + len(items)
            has_more = next_offset < total_count

            return _response(
                200,
                {
                    "items": items,
                    "count": len(items),
                    "total": total_count,
                    "nextOffset": next_offset if has_more else None,
                    "hasMore": has_more,
                },
            )

        if method == "DELETE":
            body = event.get("body")
            if isinstance(body, str):
                body = json.loads(body or "{}")
            elif body is None:
                body = {}
            key = body.get("key")
            if not key:
                return _response(400, {"error": "key required"})
            if not key.startswith(UPLOAD_PREFIX):
                return _response(400, {"error": "invalid key"})
            removed, err = _delete_upload(key)
            resp = {"removed": removed}
            if err:
                resp["warning"] = err
            return _response(200, resp)

        return _response(405, {"error": "method not allowed"})
    except Exception as exc:
        return _response(500, {"error": str(exc)})

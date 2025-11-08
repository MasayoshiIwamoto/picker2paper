import json
import os
import time
import urllib.request
import urllib.error
import boto3


s3 = boto3.client("s3")
BUCKET = os.environ.get("UPLOAD_BUCKET")
ALLOW_ORIGIN = os.environ.get("ALLOW_ORIGIN", "*")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
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


def _response(status: int, body: dict):
    return {
        "statusCode": status,
        "headers": {
            "content-type": "application/json",
            "access-control-allow-origin": ALLOW_ORIGIN,
            "access-control-allow-headers": "authorization,content-type",
            "access-control-allow-methods": "OPTIONS,POST",
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
    except urllib.error.HTTPError as e:
        return False, {"error": f"tokeninfo http {e.code}"}
    except Exception as e:
        return False, {"error": str(e)}

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


def handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return _response(200, {"ok": True})
    try:
        headers = event.get("headers") or {}
        auth = headers.get("Authorization") or headers.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return _response(401, {"error": "missing Authorization bearer"})
        id_token = auth.split(" ", 1)[1].strip()
        ok, idinfo = _verify_google_id_token(id_token)
        if not ok:
            return _response(401, {"error": "invalid id token", "detail": idinfo})

        if ALLOWED_EMAIL_DOMAINS:
            email = (idinfo.get("email") or "").lower()
            if not email or "@" not in email:
                return _response(403, {"error": "email claim required"})
            email_domain = email.split("@")[-1]
            if email_domain not in ALLOWED_EMAIL_DOMAINS:
                return _response(403, {"error": "email domain not allowed", "email": email})

        if ALLOWED_EMAILS:
            email = (idinfo.get("email") or "").lower()
            if not email:
                return _response(403, {"error": "email claim required"})
            if email not in ALLOWED_EMAILS:
                return _response(403, {"error": "email not allowed", "email": email})

        body = event.get("body")
        if isinstance(body, str):
            body = json.loads(body or "{}")
        elif body is None:
            body = {}
        key = body.get("key")
        content_type = body.get("contentType", "application/octet-stream")
        if not key:
            return _response(400, {"error": "key required"})
        if not BUCKET:
            return _response(500, {"error": "UPLOAD_BUCKET not set"})

        url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": BUCKET, "Key": key, "ContentType": content_type},
            ExpiresIn=900,
        )

        return _response(200, {"url": url})
    except Exception as e:
        return _response(500, {"error": str(e)})

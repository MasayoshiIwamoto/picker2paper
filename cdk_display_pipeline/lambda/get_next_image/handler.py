import json
import logging
import os
import time
from typing import Dict, List

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ASSETS_BUCKET = os.environ["ASSETS_BUCKET"]
PROCESSED_PREFIX = os.environ.get("PROCESSED_PREFIX", "processed/")
STATE_KEY = os.environ.get("STATE_KEY", "state/.display_state.json")

MAX_KEYS = int(os.environ.get("MAX_KEYS", "500"))
URL_TTL_SECONDS = int(os.environ.get("URL_TTL_SECONDS", "120"))
s3 = boto3.client("s3")


def handler(event, _context):
    logger.info("Received event: %s", json.dumps({k: event.get(k) for k in ("httpMethod", "path")}))

    if "httpMethod" in event:
        try:
            payload = _process_next_image()
            return _response(200, payload)
        except Exception as exc:  # pragma: no cover
            logger.exception("Failed to process HTTP request")
            return _response(500, {"error": str(exc)})

    logger.error("Unsupported event payload")
    return _response(400, {"error": "unsupported-event"})


def _process_next_image() -> Dict[str, object]:
    state = _load_state()
    keys = _list_processed_keys()
    state_changed = _align_state_with_keys(state, keys)

    if not state:
        raise LookupError("No images available")

    chosen = _select_next_key(state)
    if not chosen:
        raise LookupError("No image candidate")

    try:
        s3.head_object(Bucket=ASSETS_BUCKET, Key=chosen)
    except ClientError as exc:  # pragma: no cover
        logger.warning("Stale entry %s detected (%s); pruning and retrying", chosen, exc)
        state.pop(chosen, None)
        _save_state(state)
        return _process_next_image()

    now_ts = int(time.time())
    state[chosen] = now_ts
    state_changed = True

    if state_changed:
        _save_state(state)

    presigned_url = s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": ASSETS_BUCKET, "Key": chosen},
        ExpiresIn=URL_TTL_SECONDS,
    )

    return {
        "bmp_url": presigned_url,
        "object_key": chosen,
        "displayed_at": now_ts,
        "expires_in": URL_TTL_SECONDS,
    }


def _response(status: int, body: Dict) -> Dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def _load_state() -> Dict[str, int]:
    try:
        obj = s3.get_object(Bucket=ASSETS_BUCKET, Key=STATE_KEY)
        data = obj["Body"].read().decode("utf-8")
        return json.loads(data)
    except s3.exceptions.NoSuchKey:
        logger.info("State file not found; initializing")
        state = {key: 0 for key in _list_processed_keys()}
        _save_state(state)
        return state


def _save_state(state: Dict[str, int]) -> None:
    s3.put_object(
        Bucket=ASSETS_BUCKET,
        Key=STATE_KEY,
        Body=json.dumps(state, indent=2, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
    )


def _list_processed_keys() -> List[str]:
    keys: List[str] = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(
        Bucket=ASSETS_BUCKET,
        Prefix=PROCESSED_PREFIX,
        PaginationConfig={"PageSize": 1000},
    ):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/"):
                continue
            if not key.lower().endswith(".bmp"):
                continue
            keys.append(key)
        if len(keys) >= MAX_KEYS:
            break
    if len(keys) > MAX_KEYS:
        keys = keys[:MAX_KEYS]
    return keys


def _align_state_with_keys(state: Dict[str, int], keys: List[str]) -> bool:
    changed = False
    for key in keys:
        if key not in state:
            state[key] = 0
            changed = True
    for key in list(state.keys()):
        if key not in keys:
            state.pop(key, None)
            changed = True
    return changed


def _select_next_key(state: Dict[str, int]) -> str:
    if not state:
        return ""

    def sort_key(item):
        key, ts = item
        if ts <= 0:
            return (0, 0, key)
        return (1, ts, key)

    sorted_items = sorted(state.items(), key=sort_key)
    return sorted_items[0][0]

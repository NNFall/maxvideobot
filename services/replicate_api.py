from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

ASPECT_RATIOS = {
    '16:9': 16 / 9,
    '4:3': 4 / 3,
    '3:2': 3 / 2,
    '1:1': 1.0,
    '2:3': 2 / 3,
    '3:4': 3 / 4,
    '9:16': 9 / 16,
}


def closest_aspect_ratio(width: int, height: int) -> str:
    if width <= 0 or height <= 0:
        return '16:9'
    ratio = width / height
    return min(ASPECT_RATIOS.items(), key=lambda item: abs(item[1] - ratio))[0]


def _headers(api_token: str) -> dict[str, str]:
    return {
        'Authorization': f'Token {api_token}',
        'Content-Type': 'application/json',
    }


def _ensure_ok(response: requests.Response, context: str) -> None:
    if response.status_code < 400:
        return
    body = response.text[:800]
    retry_after = response.headers.get('Retry-After')
    suffix = f' retry_after={retry_after}' if retry_after else ''
    raise RuntimeError(f'{context} failed status={response.status_code}{suffix}: {body}')


_VERSION_RE = re.compile(r'^[0-9a-f]{64}$')
_MODEL_VERSION_CACHE: dict[str, str] = {}


def _api_root(api_url: str) -> str:
    if '/predictions' in api_url:
        return api_url.rsplit('/predictions', 1)[0]
    return 'https://api.replicate.com/v1'


def _resolve_model_version(
    model_or_version: str,
    api_token: str,
    api_url: str,
    timeout_sec: int = 30,
) -> str:
    value = (model_or_version or '').strip()
    if not value:
        raise RuntimeError('Replicate model/version is empty')
    if _VERSION_RE.fullmatch(value):
        return value
    cached = _MODEL_VERSION_CACHE.get(value)
    if cached:
        return cached
    if '/' not in value:
        raise RuntimeError(f'Invalid Replicate model slug: {value}')

    model_url = f"{_api_root(api_url)}/models/{value}"
    response = requests.get(model_url, headers=_headers(api_token), timeout=timeout_sec)
    _ensure_ok(response, f'Replicate get model {value}')
    payload = response.json()
    latest = payload.get('latest_version', {})
    version = latest.get('id')
    if not version:
        raise RuntimeError(f'Replicate model {value} has no latest_version.id')
    _MODEL_VERSION_CACHE[value] = version
    return version


def encode_image(image_path: str) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode('ascii')
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = 'image/jpeg'
    return f"data:{mime};base64,{b64}"


def create_prediction(
    image_input: str,
    prompt: str,
    duration: int,
    api_token: str,
    api_url: str,
    model_version: str,
    image_field: str = 'image',
    aspect_ratio: str | None = None,
    webhook_url: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    if not api_token:
        raise RuntimeError('REPLICATE_API_TOKEN is empty')
    if not model_version:
        raise RuntimeError('REPLICATE_MODEL_VERSION is empty')

    input_data: dict[str, Any] = {
        image_field: image_input,
        'prompt': prompt,
        'duration': duration,
    }
    if aspect_ratio:
        input_data['aspect_ratio'] = aspect_ratio

    resolved_version = _resolve_model_version(model_version, api_token, api_url, timeout_sec)

    payload: dict[str, Any] = {
        'version': resolved_version,
        'input': input_data,
    }

    if webhook_url:
        payload['webhook'] = webhook_url

    response = requests.post(api_url, headers=_headers(api_token), data=json.dumps(payload), timeout=timeout_sec)
    _ensure_ok(response, 'Replicate create prediction')
    return response.json()


def create_image_prediction(
    prompt: str,
    api_token: str,
    api_url: str,
    model: str,
    image_input: str | None = None,
    image_field: str = 'image',
    aspect_ratio: str | None = None,
    webhook_url: str | None = None,
    timeout_sec: int = 30,
) -> dict[str, Any]:
    if not api_token:
        raise RuntimeError('REPLICATE_API_TOKEN is empty')
    if not model:
        raise RuntimeError('REPLICATE_IMAGE_MODEL is empty')

    input_data: dict[str, Any] = {
        'prompt': prompt,
    }
    if image_input:
        input_data[image_field or 'image'] = image_input
    if aspect_ratio:
        input_data['aspect_ratio'] = aspect_ratio

    resolved_version = _resolve_model_version(model, api_token, api_url, timeout_sec)

    payload: dict[str, Any] = {
        'version': resolved_version,
        'input': input_data,
    }

    if webhook_url:
        payload['webhook'] = webhook_url

    response = requests.post(api_url, headers=_headers(api_token), data=json.dumps(payload), timeout=timeout_sec)
    _ensure_ok(response, 'Replicate create image prediction')
    return response.json()



def get_prediction(api_token: str, prediction_id: str, api_url: str) -> dict[str, Any]:
    if not api_token:
        raise RuntimeError('REPLICATE_API_TOKEN is empty')

    url = f"{api_url.rstrip('/')}/{prediction_id}"
    response = requests.get(url, headers=_headers(api_token), timeout=30)
    _ensure_ok(response, 'Replicate get prediction')
    return response.json()


def extract_output_urls(payload: dict[str, Any]) -> list[str]:
    output = payload.get('output')
    if isinstance(output, str):
        return [output]
    if isinstance(output, list):
        return [item for item in output if isinstance(item, str)]
    if isinstance(output, dict):
        if isinstance(output.get('video'), str):
            return [output['video']]
        if isinstance(output.get('url'), str):
            return [output['url']]
    return []


def extract_output_url(payload: dict[str, Any]) -> str | None:
    urls = extract_output_urls(payload)
    if urls:
        return urls[0]
    return None


async def poll_prediction(
    prediction_id: str,
    api_token: str,
    api_url: str,
    interval_sec: int = 10,
    timeout_sec: int = 900,
    log_every: int = 1,
) -> dict[str, Any]:
    start = time.time()
    last_status = None
    poll_count = 0

    while True:
        poll_count += 1
        prediction = await asyncio.to_thread(get_prediction, api_token, prediction_id, api_url)
        status = prediction.get('status')
        if status != last_status:
            logger.info('Replicate status prediction_id=%s status=%s', prediction_id, status)
            last_status = status
        elif log_every and poll_count % log_every == 0:
            logger.info('Replicate status prediction_id=%s status=%s (still)', prediction_id, status)

        if status in ('succeeded',):
            return prediction
        if status in ('failed', 'canceled'):
            err = prediction.get('error')
            if not err and isinstance(prediction.get('logs'), str):
                err = prediction.get('logs')
            if err:
                logger.error('Replicate failed prediction_id=%s status=%s error=%s', prediction_id, status, err)
                raise RuntimeError(f'Replicate failed: {status}. {err}')
            logger.error('Replicate failed prediction_id=%s status=%s', prediction_id, status)
            raise RuntimeError(f'Replicate failed: {status}')

        if time.time() - start > timeout_sec:
            raise TimeoutError('Replicate generation timed out')

        await asyncio.sleep(interval_sec)

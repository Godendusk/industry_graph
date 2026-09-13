"""Client for the embodied-intelligence subject news APIs."""

from __future__ import annotations

import json
import os
import time
from typing import Any, Dict

import requests


BASE_URL = "https://clb4yjzx.ciglobal.cn/clb-api"
SUBJECT_ID = "2043590589800853505"
SUBJECT_INDEX = "subjectdatabase_2026"
LIST_URL = f"{BASE_URL}/subjectServer/info/subjectPageList"
DETAIL_URL = f"{BASE_URL}/subjectServer/info/queryById"


class EmbodiedNewsClientError(RuntimeError):
    """Raised when the embodied subject API cannot return usable data."""


class EmbodiedNewsClient:
    """Small wrapper around the authorized subject list and detail endpoints."""

    def __init__(
        self,
        access_token: str | None = None,
        x_access_token: str | None = None,
        timeout: int = 30,
    ) -> None:
        self.access_token = (access_token or os.environ.get("EMBODIED_ACCESS_TOKEN", "")).strip()
        self.x_access_token = (
            x_access_token or os.environ.get("EMBODIED_X_ACCESS_TOKEN", "")
        ).strip()
        if not self.access_token or not self.x_access_token:
            raise EmbodiedNewsClientError(
                "EMBODIED_ACCESS_TOKEN and EMBODIED_X_ACCESS_TOKEN are required"
            )
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json",
            "accessToken": self.access_token,
            "X-Access-Token": self.x_access_token,
            "env": "prod",
            "environment": "prod",
            "timeLine": str(int(time.time() * 1000)),
        }

    @staticmethod
    def _decode(response: requests.Response, context: str) -> Dict[str, Any]:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            raise EmbodiedNewsClientError(f"{context} HTTP request failed: {exc}") from exc
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise EmbodiedNewsClientError(f"{context} returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EmbodiedNewsClientError(f"{context} returned a non-object JSON payload")
        if payload.get("code") != 200:
            message = payload.get("message") or payload.get("msg") or "unknown API error"
            raise EmbodiedNewsClientError(f"{context} failed: {message}")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise EmbodiedNewsClientError(f"{context} missing result object")
        return result

    def list_news(self, page_no: int = 1, page_size: int = 100) -> Dict[str, Any]:
        payload = {
            "subjectId": SUBJECT_ID,
            "pageNo": page_no,
            "pageSize": page_size,
            "fetchFields": [
                "id",
                "title",
                "summary",
                "author",
                "sourceAddress",
                "publishDate",
                "content",
                "contentWithTag",
            ],
            "status": 1,
            "isSubject": "1",
            "category": 1,
            "searchWordList": [],
            "column": "publishDate",
            "order": "desc",
            "wordFrequency": [],
            "dateFormat": "yyyy-MM-dd",
            "socialCreditCodeList": [],
            "labelIds": [],
        }
        try:
            response = requests.post(
                LIST_URL,
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise EmbodiedNewsClientError(
                f"subjectPageList page {page_no} request failed: {exc}"
            ) from exc
        return self._decode(response, f"subjectPageList page {page_no}")

    def get_detail(self, source_id: str) -> Dict[str, Any]:
        normalized_id = str(source_id or "").strip()
        if not normalized_id:
            raise EmbodiedNewsClientError("queryById requires a source ID")
        try:
            response = requests.get(
                DETAIL_URL,
                headers=self._headers(),
                params={"id": normalized_id, "index": SUBJECT_INDEX},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise EmbodiedNewsClientError(
                f"queryById source {normalized_id} request failed: {exc}"
            ) from exc
        return self._decode(response, f"queryById source {normalized_id}")

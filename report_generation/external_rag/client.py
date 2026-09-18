"""HTTP client for the client-provided external material APIs."""

from __future__ import annotations

from typing import Any, Dict

import requests
from ..industry_config import get_industry_config


AI_COLUMN_ID = "2008715487928750081"
# LIST_URL = "https://sasac-rc.com/api/sdServerUrl/channel/datapull/column/queryInfoList"
# DETAIL_URL = "https://sasac-rc.com/api/sdServerUrl/channel/datapull/column/queryById"

LIST_URL = "http://1.95.67.224:10089/channel/datapull/column/queryInfoList"
DETAIL_URL = "http://1.95.67.224:10089/channel/datapull/column/queryById"

EXTERNAL_LIBRARIES: Dict[str, Dict[str, str]] = {
    "policy": {
        "classification_type": "1",
        "classification_name": "政策法规",
        "collection": "report_policy_ai",
    },
    "speech": {
        "classification_type": "2",
        "classification_name": "领导讲话",
        "collection": "report_speech_ai",
    },
    "expert_view": {
        "classification_type": "3",
        "classification_name": "专家观点",
        "collection": "report_expert_view_ai",
    },
    "company_case": {
        "classification_type": "4",
        "classification_name": "企业案例",
        "collection": "report_company_case_ai",
    },
    "research_report": {
        "classification_type": "6",
        "classification_name": "研究报告",
        "collection": "report_research_report_ai",
    },
}


def get_external_libraries(industry: str) -> Dict[str, Dict[str, str]]:
    """Return collection configuration isolated to one industry database."""
    get_industry_config(industry)
    if industry == "ai":
        return {key: dict(value) for key, value in EXTERNAL_LIBRARIES.items()}
    libraries: Dict[str, Dict[str, str]] = {}
    for key, value in EXTERNAL_LIBRARIES.items():
        config = dict(value)
        config["collection"] = f"report_{key}_{industry}"
        libraries[key] = config
    return libraries


class ExternalRagClientError(RuntimeError):
    """Raised when the external material API cannot return usable data."""


class ExternalMaterialClient:
    """Small wrapper around the list/detail APIs used by external RAG ingestion."""

    def __init__(self, access_token: str, timeout: int = 30, industry: str = "ai"):
        if not access_token or not access_token.strip():
            raise ValueError("access_token is required")
        self.access_token = access_token.strip()
        self.timeout = timeout
        self.industry = str(industry or "").strip()
        config = get_industry_config(self.industry)
        self.column_id = config.get("external_column_id")
        if not self.column_id:
            raise ValueError(f"external RAG column id is not configured for industry: {self.industry}")

    def _headers(self) -> Dict[str, str]:
        return {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "User-Agent": "PostmanRuntime-ApipostRuntime/1.1.0",
            "accesstoken": self.access_token,
        }

    @staticmethod
    def _decode_json(response: requests.Response) -> Dict[str, Any]:
        response.encoding = "utf-8"
        try:
            return response.json()
        except ValueError as exc:
            preview = response.text[:300]
            raise ExternalRagClientError(f"API returned invalid JSON: {preview}") from exc

    @staticmethod
    def _ensure_success(payload: Dict[str, Any], api_name: str) -> None:
        is_success = (
            payload.get("code") in (0, 200)
            or payload.get("success") is True
            or payload.get("status") == "success"
        )
        if not is_success:
            message = payload.get("message") or payload.get("msg") or "unknown API error"
            raise ExternalRagClientError(f"{api_name} failed: {message}")

    def query_info_list(
        self,
        classification_type: str,
        page_no: int,
        page_size: int,
    ) -> Dict[str, Any]:
        body = {
            "columnId": self.column_id,
            "ynChannel": 1,
            "classificationType": str(classification_type),
            "order": "desc",
            "column": "publishDate",
            "checkStatusList": [1],
            "deleteFlag": 0,
            "pageNo": page_no,
            "pageSize": page_size,
        }
        try:
            response = requests.post(
                LIST_URL,
                headers=self._headers(),
                json=body,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ExternalRagClientError(f"queryInfoList request failed: {exc}") from exc

        payload = self._decode_json(response)
        self._ensure_success(payload, "queryInfoList")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ExternalRagClientError("queryInfoList missing result object")
        return result

    def query_by_id(self, material_id: str) -> Dict[str, Any]:
        try:
            response = requests.get(
                DETAIL_URL,
                headers=self._headers(),
                params={"id": material_id},
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise ExternalRagClientError(f"queryById request failed: {exc}") from exc

        payload = self._decode_json(response)
        self._ensure_success(payload, "queryById")
        result = payload.get("result") or payload.get("data")
        if not isinstance(result, dict):
            raise ExternalRagClientError("queryById missing result object")
        return result

import io
import os
from typing import Any

import pandas as pd
import requests
from fastapi import FastAPI, HTTPException

DATASET_ID = "zoo-visitors2569"
RESOURCE_ID = "0ecc96cf-d914-42a1-b184-dbbd013c3c9c"
FISCAL_YEAR = 2569
SOURCE_PAGE = f"https://data.go.th/dataset/{DATASET_ID}"
CKAN_RESOURCE_API = "https://data.go.th/api/3/action/resource_show"

app = FastAPI(
    title="Zoo Visitors API",
    description="REST API สำหรับข้อมูลรายงานสถิติจำนวนผู้เข้าชมสวนสัตว์ ปีงบประมาณ 2569 จาก Data.go.th",
    version="1.0.0",
)

def get_resource_url() -> str:
    """Resolve the official download URL from Data.go.th using the supplied resource ID."""
    # Optional override: set DATA_RESOURCE_URL to the exact download URL shown on Data.go.th.
    override = os.getenv("DATA_RESOURCE_URL")
    if override:
        return override

    response = requests.get(
        CKAN_RESOURCE_API,
        params={"id": RESOURCE_ID},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    if not payload.get("success") or not payload.get("result", {}).get("url"):
        raise RuntimeError(
            "Data.go.th did not return a download URL for the specified Resource ID. "
            "Set DATA_RESOURCE_URL to the resource's direct download URL."
        )
    return payload["result"]["url"]


def load_records() -> list[dict[str, Any]]:
    url = get_resource_url()
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    content = response.content

    # Read the actual resource format (CSV or Excel), not fabricated sample data.
    lower_url = url.lower().split("?")[0]
    try:
        if lower_url.endswith((".xlsx", ".xls")) or content[:2] == b"PK":
            df = pd.read_excel(io.BytesIO(content))
        else:
            try:
                df = pd.read_csv(io.BytesIO(content), encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(content), encoding="cp874")
    except Exception as exc:
        raise RuntimeError(f"Cannot parse the downloaded resource: {exc}") from exc

    df = df.dropna(how="all")
    # Convert NaN/NaT to JSON null and preserve the source's original column names.
    df = df.astype(object).where(pd.notna(df), None)
    records = df.to_dict(orient="records")

    # If the resource contains multiple fiscal years, return only FY 2569 when
    # a recognizable fiscal-year column exists.
    year_columns = [
        col for col in df.columns
        if str(col).strip().lower() in {
            "ปีงบประมาณ", "ปีงบฯ", "fiscal_year", "fiscal year"
        }
    ]
    if year_columns:
        col = year_columns[0]
        filtered = []
        for row in records:
            value = row.get(col)
            try:
                if int(float(str(value).replace(",", ""))) == FISCAL_YEAR:
                    filtered.append(row)
            except (TypeError, ValueError):
                continue
        if filtered:
            records = filtered

    if not records:
        raise RuntimeError("The resource was downloaded, but it contains no data rows.")
    return records


@app.get("/")
def root():
    return {
        "message": "Zoo Visitors API is running",
        "endpoint": "/api/zoo-visitors",
        "docs": "/docs",
    }


@app.get("/api/zoo-visitors")
def zoo_visitors():
    try:
        records = load_records()
        return {
            "source": SOURCE_PAGE,
            "organization": "องค์การสวนสัตว์แห่งประเทศไทย ในพระบรมราชูปถัมภ์",
            "dataset_id": DATASET_ID,
            "resource_id": RESOURCE_ID,
            "fiscal_year": FISCAL_YEAR,
            "record_count": len(records),
            "data": records,
        }
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Cannot retrieve source data from Data.go.th: {exc}",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

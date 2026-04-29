"""CSV/XLSX upload to UC Volume."""
from __future__ import annotations

import io
from pathlib import PurePosixPath

from databricks.sdk import WorkspaceClient

from app.config import SETTINGS
from app.services import metadata, uc


def upload_to_volume(file_bytes: bytes, file_name: str, uploaded_by: str) -> dict:
    """Upload bytes to the ProspectorPro_uploads volume; record metadata in UC."""
    suffix = PurePosixPath(file_name).suffix.lower().lstrip(".")
    if suffix not in {"csv", "xlsx"}:
        raise ValueError(f"unsupported format: {suffix}")

    safe_name = file_name.replace("/", "_").replace(" ", "_")
    volume_path = f"{SETTINGS.volume_path}/{safe_name}"

    w = WorkspaceClient()
    w.files.upload(volume_path, io.BytesIO(file_bytes), overwrite=True)

    inferred_schema: list[dict] = []
    try:
        inferred = uc.query_df(
            f"SELECT * FROM read_files('{volume_path}', "
            f"format => '{suffix}', header => 'true'"
            + (", inferSchema => 'true'" if suffix == "csv" else "")
            + ") LIMIT 0"
        )
        inferred_schema = [{"name": c, "type": str(inferred[c].dtype)} for c in inferred.columns]
    except Exception:
        inferred_schema = []

    upload_id = metadata.append_upload(
        file_name=safe_name,
        volume_path=volume_path,
        file_format=suffix,
        inferred_schema=inferred_schema,
        uploaded_by=uploaded_by,
    )
    return {
        "upload_id": upload_id,
        "volume_path": volume_path,
        "file_format": suffix,
        "inferred_schema": inferred_schema,
    }

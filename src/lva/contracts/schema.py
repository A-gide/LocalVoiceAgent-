from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from pydantic import BaseModel

from .commands import CommandEnvelope, CommandResult
from .errors import ErrorEnvelope
from .events import EventEnvelope
from .state import RuntimeState


class LvaIpcSchemaRoot(BaseModel):
    runtime_state: RuntimeState
    event_envelope: EventEnvelope
    command_envelope: CommandEnvelope
    command_result: CommandResult
    error_envelope: ErrorEnvelope


def generate_json_schema() -> dict[str, Any]:
    return LvaIpcSchemaRoot.model_json_schema()


def export_schema_file(output_path: Path | str | None = None) -> Path:
    if output_path is None:
        # Defaults to repo_root/schemas/lva-ipc-v1.json
        repo_root = Path(__file__).resolve().parents[3]
        output_path = repo_root / "schemas" / "lva-ipc-v1.json"
    else:
        output_path = Path(output_path)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    schema = generate_json_schema()
    output_path.write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path


if __name__ == "__main__":
    path = export_schema_file()
    print(f"Exported IPC schema to {path}")

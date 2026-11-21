"""Table reader (B-02 minimal): PdM event logs (errors, maintenance, failures) as claims.

Each data row becomes one EXTRACTED claim with a `TableCellPointer` (row, column, raw value,
`row_sha256` of the raw line bytes, byte offset of the line). These claims exist in M2 so that
envelope learning can exclude event days (PRD 10.3). Using them as supporting context on the
conflict card is TODO(M3).
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import datetime

from trace_core.ids import build_claim
from trace_core.models.claims import Candidate, ClaimRecord, Confidence, MentionKey, Method, Subject
from trace_core.models.config import ConfigBundle
from trace_core.models.evidence import TableCellPointer
from trace_core.models.records import Source
from trace_core.models.time import ObservedTime, Temporal
from trace_core.normalise.time import hour_interval, local_hhmm, local_naive_to_utc
from trace_core.stage_types import ReadResult

# third column header -> claim attribute (ontology names)
EVENT_ATTRIBUTES = {
    "errorID": "error_event",
    "comp": "maintenance_action",
    "failure": "failure_event",
}
EVENT_ATTRIBUTE_NAMES = frozenset(EVENT_ATTRIBUTES.values())
_HEADER_PREFIX = ["datetime", "machineID"]


def read_table(src: Source, blob: bytes, cfg: ConfigBundle) -> ReadResult:
    tz = cfg.case.plant_tz
    prior = cfg.gate.text_extractor_prior
    claims: list[ClaimRecord] = []
    offset = 0
    header: list[str] | None = None
    row = -1
    for raw_with_eol in blob.splitlines(keepends=True):
        line_offset = offset
        offset += len(raw_with_eol)
        raw = raw_with_eol.rstrip(b"\r\n")
        if not raw:
            continue
        cells = next(csv.reader(io.StringIO(raw.decode("utf-8"))))
        if header is None:
            header = cells
            if (
                header[:2] != _HEADER_PREFIX
                or len(header) != 3
                or header[2] not in EVENT_ATTRIBUTES
            ):
                raise ValueError("unsupported table layout")  # fail closed
            continue
        row += 1
        stamp = datetime.strptime(cells[0], "%Y-%m-%d %H:%M:%S")  # noqa: DTZ007 (plant-local)
        start = local_naive_to_utc(stamp, tz)
        machine = f"machine:{int(cells[1])}"
        column = header[2]
        attribute = EVENT_ATTRIBUTES[column]
        claims.append(
            build_claim(
                case_id=src.case_id,
                claim_type="extracted",
                statement=(
                    f"Machine {int(cells[1])} logged {cells[2]} at "
                    f"{stamp:%d %b %Y} {local_hhmm(start, tz)}"
                ),
                subject=Subject(
                    mention=f"machineID {cells[1]}",
                    entity_id=machine,
                    link_status="resolved",
                    candidates=[
                        Candidate(entity_id=machine, score=1.0, reasons=["machineID column"])
                    ],
                    mention_key=MentionKey(source_sha256=src.sha256, locator=f"row{row}"),
                ),
                attribute=attribute,
                value=cells[2],
                value_type="categorical",
                unit=None,
                unit_status="not_applicable",
                temporal=Temporal(
                    valid_time=hour_interval(start, "explicit"),
                    observed_time=ObservedTime(at=start, basis="sensor_timestamp"),
                    timezone_original=tz,
                ),
                modality="table",
                evidence=TableCellPointer(
                    source_id=src.source_id,
                    sha256=src.sha256,
                    row=row,
                    column=column,
                    raw_value=cells[2],
                    row_sha256=hashlib.sha256(raw).hexdigest(),
                    row_byte_offset=line_offset,
                ),
                derived_from=[],
                method=Method(
                    extractor="csv:event_log", extractor_version="1", rule_id=f"table.{attribute}"
                ),
                confidence=Confidence(
                    value=prior,
                    calibrated=False,
                    components={"extractor": prior},
                    stage="pre",
                    note="uncalibrated raw pre-score; the table prior arrives with M3 scoring",
                ),
            )
        )
    return ReadResult(claims=claims)

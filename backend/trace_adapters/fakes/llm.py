"""FakeLlm and IdentityRedactor (P0 default: no model is ever called)."""

from __future__ import annotations

from trace_core.models.evidence import Proposal, ProposalBatch, RedactedDocument


class FakeLlm:
    def __init__(self, proposals: list[Proposal] | None = None) -> None:
        self._proposals = list(proposals or [])

    def propose(self, doc: RedactedDocument, prompt_id: str) -> ProposalBatch:
        return ProposalBatch(proposals=list(self._proposals), model_id="fake", prompt_id=prompt_id)


class IdentityRedactor:
    """Redacts nothing (numbers and units are never redacted anyway)."""

    def redact(self, text: str) -> RedactedDocument:
        return RedactedDocument(text=text, spans=[])

"""Domain errors. Fail closed: every one of these is a hard stop, never silently ignored."""

from __future__ import annotations


class TraceError(Exception):
    """Base class. Messages must never contain document text, quotes or secrets."""


class CanonicalizationError(TraceError):
    """A value cannot be canonicalised (NaN, Inf, non-string key, unsupported type)."""


class ReplayCacheMiss(TraceError):
    """Replay mode looked up a key that was never recorded. This is an error, not a skip."""


class CacheWriteOnceViolation(TraceError):
    """ExtractionCache.put was called twice for one key with different bytes."""


class CacheModeError(TraceError):
    """A write was attempted in replay mode."""


class PayloadTooLarge(TraceError):
    """A stream exceeded its byte cap."""


class AppendOnlyViolation(TraceError):
    """An update or delete of evidence was attempted (promise 6)."""


class AlreadyDecided(TraceError):
    def __init__(self, existing_decision_id: str) -> None:
        super().__init__("review item already decided")
        self.existing_decision_id = existing_decision_id


class EvidenceChanged(TraceError):
    """The evidence hash shown to the reviewer no longer matches."""


class LogCoverageError(TraceError):
    """An event log's coverage_period does not cover a day needed for envelope learning."""


class RenderRefused(TraceError):
    """A page render was refused (pixel cap) before any pixels were allocated."""


class PdfPageCap(TraceError):
    """A PDF has more pages than the cap."""


class IntegrityError(TraceError):
    """Stored bytes do not match their stored hash, or the version chain is broken."""


class CapabilityMissing(TraceError):
    """The PDF engine lacks a required capability (probed, never assumed)."""

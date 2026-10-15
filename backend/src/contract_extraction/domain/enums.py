"""Enumerations mirroring the CHECK constraints in docker/schema.sql."""

from enum import StrEnum


class ProviderKind(StrEnum):
    OLLAMA = "ollama"
    OPENROUTER = "openrouter"
    OPENAI_COMPATIBLE = "openai_compatible"


class ModelKind(StrEnum):
    CHAT = "chat"
    EMBEDDING = "embedding"
    VISION = "vision"


class PromptRole(StrEnum):
    EXTRACTION_SYSTEM = "extraction_system"
    JUDGE_SYSTEM = "judge_system"
    CAPTION = "caption"


class DecompositionMethod(StrEnum):
    PYMUPDF = "pymupdf"
    OCR = "ocr"
    HYBRID = "hybrid"


class TextFormat(StrEnum):
    MD = "md"
    HTML = "html"


class VectorStore(StrEnum):
    QDRANT = "qdrant"
    MEMORY = "memory"


class Distance(StrEnum):
    COSINE = "cosine"
    DOT = "dot"
    EUCLID = "euclid"


class ValueType(StrEnum):
    TEXT = "text"
    DATE = "date"
    NUMBER = "number"
    MONEY = "money"
    LIST = "list"
    BOOLEAN = "boolean"
    JSON = "json"


class Priority(StrEnum):
    """Field priority from the catalogue: P1 = direct financial, time or exit exposure; P3 = informational.
    Values sort by importance (P1 < P2 < P3)."""

    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class IndexStatus(StrEnum):
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class RunKind(StrEnum):
    FULL = "full"
    DECOMPOSE = "decompose"
    EXTRACT = "extract"


class RunState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_active(self) -> bool:
        return self in (RunState.QUEUED, RunState.RUNNING)

    @property
    def is_terminal(self) -> bool:
        return not self.is_active


class RunStage(StrEnum):
    DECOMPOSING = "decomposing"
    INDEXING = "indexing"
    EXTRACTING = "extracting"


class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class FieldResultStatus(StrEnum):
    EXTRACTED = "extracted"
    NOT_FOUND = "not_found"
    ERROR = "error"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"
    SKIPPED = "SKIPPED"


class JudgeIssue(StrEnum):
    NONE = "NONE"
    HALLUCINATION = "HALLUCINATION"
    INCOMPLETE = "INCOMPLETE"
    NO_CONTEXT = "NO_CONTEXT"


class LlmCallPurpose(StrEnum):
    EXTRACTION = "extraction"
    JUDGE = "judge"
    CAPTION = "caption"
    EMBEDDING = "embedding"


class LlmCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"

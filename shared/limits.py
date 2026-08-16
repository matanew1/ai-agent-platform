"""Payload size limits shared by every route that accepts user-supplied content.

Every number here bounds a real, unbounded-until-now request path: chat
attachments (base64 over JSON) and document ingestion (raw text or an
uploaded file) all fan out into extraction, embedding, or LLM calls -
real cost and availability exposure, not a hypothetical one. Centralized
here rather than inlined per-schema so ``chat`` and ``rag`` stay
consistent with each other and with the upload route's own byte check
(``rag.controller.ingest_owner_file``, the one path Pydantic's
``Field(max_length=...)`` can't cover since it validates a decoded
``UploadFile`` after FastAPI has already buffered it).
"""

from __future__ import annotations

# A chat attachment / uploaded document caps at 20 MB raw. Generous for a
# resume, report, or transcript; not generous enough to make embedding a
# single request a meaningful cost/availability lever.
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

# Base64 inflates the byte count by 4/3 - this bounds a
# ChatFileAttachment.content_base64 string to roughly MAX_DOCUMENT_BYTES
# once decoded.
MAX_ATTACHMENT_BASE64_CHARS = (MAX_DOCUMENT_BYTES * 4) // 3

# The web client's chat composer (ChatPane.tsx) queues multiple files with
# no cap of its own today - this is the only enforcement point until it
# gains a matching client-side limit. A user queuing more than this gets a
# 422 with no client-side warning; acceptable as defense-in-depth for now,
# but a client-side cap would be a better UX fix than raising this number.
MAX_CHAT_ATTACHMENTS = 10

# A chat message is a prompt, not a document - bounded well below
# MAX_DOCUMENT_BYTES. 20k characters is several pages of text, already
# far beyond a realistic single turn.
MAX_CHAT_MESSAGE_CHARS = 20_000

# POST /documents/text takes raw text directly (no extraction step). Reuses
# MAX_DOCUMENT_BYTES as a character count, not an exact byte-for-byte
# equivalent - multi-byte UTF-8 text can run larger in bytes than this many
# characters would for the file-upload path. Deliberately generous rather
# than exact: the file-upload cap is the more conservative reference point.
MAX_DOCUMENT_TEXT_CHARS = MAX_DOCUMENT_BYTES

__all__ = [
    "MAX_ATTACHMENT_BASE64_CHARS",
    "MAX_CHAT_ATTACHMENTS",
    "MAX_CHAT_MESSAGE_CHARS",
    "MAX_DOCUMENT_BYTES",
    "MAX_DOCUMENT_TEXT_CHARS",
]

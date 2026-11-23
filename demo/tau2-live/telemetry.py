# SPDX-License-Identifier: Apache-2.0
"""OpenTelemetry for the demo: one trace per case, spans written as JSON lines.

The orchestrator and each airline tool server process append their ended spans
to the case's ``spans.jsonl`` (the SDK's own span JSON, one per line). A tool
server joins the case's trace through the W3C ``traceparent`` the orchestrator
writes to the case directory for the current turn.

The only capsule link a span carries is ``aac.capsule_id``, set by capsule-emit's
``stamp_reverse_join`` while the span is still open; the record itself stays in
the airline's book. Spans also carry plain attributes such as the tool name. Nothing reads OTel back into books.
"""
from __future__ import annotations

import os
from pathlib import Path

from capsule_emit.otel.processor import REVERSE_JOIN_ATTRIBUTE, stamp_reverse_join
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

_providers: list[TracerProvider] = []
_files: list = []

__all__ = ["REVERSE_JOIN_ATTRIBUTE", "tracer", "stamp", "traceparent", "parent_context", "shutdown"]


def tracer(service: str, spans_file: Path) -> trace.Tracer:
    """A tracer whose ended spans are appended to ``spans_file``, one JSON object per line."""
    out = spans_file.open("a")
    _files.append(out)
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(SimpleSpanProcessor(
        ConsoleSpanExporter(out=out, formatter=lambda span: span.to_json(indent=None) + "\n")))
    _providers.append(provider)
    return provider.get_tracer("tau2-live")


def stamp(span: trace.Span, capsule_id: str) -> None:
    """Put the sealed record's capsule id on a live span (before ``span.end()``)."""
    stamp_reverse_join(span, capsule_id)


def traceparent() -> str:
    """The current span's W3C ``traceparent``, for a child process's environment."""
    carrier: dict[str, str] = {}
    TraceContextTextMapPropagator().inject(carrier)
    return carrier.get("traceparent", "")


def parent_context(path: Path | None = None):
    """The trace context to parent a span under: the ``traceparent`` file the
    orchestrator writes for the current turn when given, else ``TRACEPARENT``."""
    value = path.read_text().strip() if path is not None and path.exists() else os.environ.get("TRACEPARENT", "")
    return TraceContextTextMapPropagator().extract({"traceparent": value}) if value else None


def shutdown() -> None:
    for provider in _providers:
        provider.shutdown()
    for out in _files:
        out.close()

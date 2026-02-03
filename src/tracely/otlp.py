"""OTLP protobuf serialization for span data (AR2).

Converts internal span dicts to OTLP ExportTraceServiceRequest protobuf bytes
for transmission via OTLP/HTTP.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.proto.common.v1.common_pb2 import AnyValue, KeyValue
from opentelemetry.proto.resource.v1.resource_pb2 import Resource
from opentelemetry.proto.trace.v1.trace_pb2 import (
    ResourceSpans,
    ScopeSpans,
    Span as OtlpSpan,
    Status,
)

logger = logging.getLogger("tracely")

# OTLP SpanKind mapping
_KIND_MAP: dict[str, int] = {
    "INTERNAL": 1,  # SPAN_KIND_INTERNAL
    "SERVER": 2,    # SPAN_KIND_SERVER
    "CLIENT": 3,    # SPAN_KIND_CLIENT
    "PRODUCER": 4,  # SPAN_KIND_PRODUCER
    "CONSUMER": 5,  # SPAN_KIND_CONSUMER
}

# OTLP StatusCode mapping
_STATUS_MAP: dict[str, int] = {
    "UNSET": 0,  # STATUS_CODE_UNSET
    "OK": 1,     # STATUS_CODE_OK
    "ERROR": 2,  # STATUS_CODE_ERROR
}


def _seconds_to_nanos(ts: float | None) -> int:
    """Convert a Unix timestamp in seconds to nanoseconds."""
    if ts is None:
        return 0
    return int(ts * 1_000_000_000)


def _make_kv(key: str, value: str) -> KeyValue:
    """Create an OTLP KeyValue with a string value."""
    return KeyValue(key=key, value=AnyValue(string_value=str(value)))


def _span_to_otlp(span_dict: dict[str, Any]) -> OtlpSpan:
    """Convert an internal span dict to an OTLP Span message."""
    trace_id = bytes.fromhex(span_dict["trace_id"])
    span_id = bytes.fromhex(span_dict["span_id"])

    parent = span_dict.get("parent_span_id")
    parent_span_id = bytes.fromhex(parent) if parent else b""

    # Build attributes from span dict + tracely.span_type
    attributes = []
    for k, v in span_dict.get("attributes", {}).items():
        attributes.append(_make_kv(k, v))
    attributes.append(_make_kv("tracely.span_type", span_dict.get("span_type", "span")))

    # Build events
    events = []
    for evt in span_dict.get("events", []):
        evt_attrs = [_make_kv(k, v) for k, v in evt.get("attributes", {}).items()]
        if evt.get("level"):
            evt_attrs.append(_make_kv("level", evt["level"]))
        events.append(OtlpSpan.Event(
            name=evt.get("message", ""),
            time_unix_nano=_seconds_to_nanos(evt.get("timestamp")),
            attributes=evt_attrs,
        ))

    # Build status
    status_code = _STATUS_MAP.get(span_dict.get("status_code", "UNSET"), 0)
    status = Status(
        code=status_code,
        message=span_dict.get("status_message", ""),
    )

    return OtlpSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        name=span_dict.get("span_name", ""),
        kind=_KIND_MAP.get(span_dict.get("kind", "INTERNAL"), 1),
        start_time_unix_nano=_seconds_to_nanos(span_dict.get("start_time")),
        end_time_unix_nano=_seconds_to_nanos(span_dict.get("end_time")),
        attributes=attributes,
        events=events,
        status=status,
    )


def serialize_spans(spans: list[dict[str, Any]]) -> bytes:
    """Serialize a list of span dicts to OTLP ExportTraceServiceRequest bytes.

    Spans are grouped by service_name into separate ResourceSpans.
    Returns protobuf-serialized bytes ready for OTLP/HTTP transport.
    """
    if not spans:
        return ExportTraceServiceRequest().SerializeToString()

    # Group spans by service_name
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for span_dict in spans:
        svc = span_dict.get("service_name") or "unknown"
        grouped[svc].append(span_dict)

    resource_spans_list = []
    for svc_name, svc_spans in grouped.items():
        resource = Resource(attributes=[_make_kv("service.name", svc_name)])
        otlp_spans = [_span_to_otlp(s) for s in svc_spans]
        scope_spans = ScopeSpans(spans=otlp_spans)
        resource_spans_list.append(
            ResourceSpans(resource=resource, scope_spans=[scope_spans])
        )

    request = ExportTraceServiceRequest(resource_spans=resource_spans_list)
    return request.SerializeToString()

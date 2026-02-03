"""Tests for OTLP protobuf serialization (AR2)."""

from __future__ import annotations

import time

import pytest
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)

from tracely.otlp import serialize_spans


def _make_span_dict(
    *,
    trace_id: str = "a" * 32,
    span_id: str = "b" * 16,
    parent_span_id: str | None = None,
    span_name: str = "GET /api/users",
    span_type: str = "span",
    kind: str = "SERVER",
    service_name: str | None = "test-svc",
    start_time: float = 1700000000.0,
    end_time: float | None = 1700000001.5,
    duration_ms: float | None = 1500.0,
    status_code: str = "OK",
    status_message: str = "",
    attributes: dict | None = None,
    events: list | None = None,
) -> dict:
    return {
        "trace_id": trace_id,
        "span_id": span_id,
        "parent_span_id": parent_span_id,
        "span_name": span_name,
        "span_type": span_type,
        "kind": kind,
        "service_name": service_name,
        "start_time": start_time,
        "end_time": end_time,
        "duration_ms": duration_ms,
        "status_code": status_code,
        "status_message": status_message,
        "attributes": attributes or {},
        "events": events or [],
        "event_count": len(events) if events else 0,
    }


class TestSerializeSpans:
    """serialize_spans produces valid OTLP ExportTraceServiceRequest bytes."""

    def test_returns_bytes(self):
        """Output is bytes (protobuf serialized)."""
        spans = [_make_span_dict()]
        result = serialize_spans(spans)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_deserializable_as_export_request(self):
        """Bytes deserialize to a valid ExportTraceServiceRequest."""
        spans = [_make_span_dict()]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        assert len(req.resource_spans) == 1

    def test_span_ids_mapped_to_bytes(self):
        """trace_id and span_id hex strings become 16-byte and 8-byte fields."""
        spans = [_make_span_dict(trace_id="ab" * 16, span_id="cd" * 8)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.trace_id == bytes.fromhex("ab" * 16)
        assert otlp_span.span_id == bytes.fromhex("cd" * 8)

    def test_parent_span_id_present(self):
        """parent_span_id is set when provided."""
        spans = [_make_span_dict(parent_span_id="ee" * 8)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.parent_span_id == bytes.fromhex("ee" * 8)

    def test_parent_span_id_empty_when_none(self):
        """parent_span_id is empty bytes when not provided."""
        spans = [_make_span_dict(parent_span_id=None)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.parent_span_id == b""

    def test_span_name_mapped(self):
        """span_name maps to OTLP Span.name."""
        spans = [_make_span_dict(span_name="POST /login")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.name == "POST /login"

    def test_timestamps_in_nanoseconds(self):
        """start_time and end_time are converted to nanoseconds."""
        spans = [_make_span_dict(start_time=1700000000.0, end_time=1700000001.5)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.start_time_unix_nano == 1700000000_000_000_000
        assert otlp_span.end_time_unix_nano == 1700000001_500_000_000

    def test_pending_span_no_end_time(self):
        """pending_span has end_time_unix_nano = 0."""
        spans = [_make_span_dict(span_type="pending_span", end_time=None)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.end_time_unix_nano == 0

    def test_span_type_as_attribute(self):
        """span_type is stored as tracely.span_type attribute."""
        spans = [_make_span_dict(span_type="pending_span")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        attr_map = {
            kv.key: kv.value.string_value for kv in otlp_span.attributes
        }
        assert attr_map["tracely.span_type"] == "pending_span"

    def test_kind_mapping_server(self):
        """'SERVER' maps to SPAN_KIND_SERVER (3)."""
        spans = [_make_span_dict(kind="SERVER")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        # SPAN_KIND_SERVER = 2 in OTLP proto
        assert otlp_span.kind == 2

    def test_kind_mapping_client(self):
        """'CLIENT' maps to SPAN_KIND_CLIENT (3)."""
        spans = [_make_span_dict(kind="CLIENT")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        # SPAN_KIND_CLIENT = 3 in OTLP proto
        assert otlp_span.kind == 3

    def test_kind_mapping_internal(self):
        """'INTERNAL' maps to SPAN_KIND_INTERNAL (1)."""
        spans = [_make_span_dict(kind="INTERNAL")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        # SPAN_KIND_INTERNAL = 1 in OTLP proto
        assert otlp_span.kind == 1

    def test_attributes_mapped(self):
        """Span attributes become OTLP KeyValue pairs."""
        spans = [_make_span_dict(attributes={"http.method": "GET", "http.url": "https://example.com"})]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        attr_map = {
            kv.key: kv.value.string_value for kv in otlp_span.attributes
        }
        assert attr_map["http.method"] == "GET"
        assert attr_map["http.url"] == "https://example.com"

    def test_events_mapped(self):
        """Span events become OTLP Event messages."""
        events = [
            {
                "timestamp": 1700000000.5,
                "level": "INFO",
                "message": "user logged in",
                "attributes": {"user_id": "42"},
            }
        ]
        spans = [_make_span_dict(events=events)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert len(otlp_span.events) == 1
        event = otlp_span.events[0]
        assert event.name == "user logged in"
        assert event.time_unix_nano == 1700000000_500_000_000

    def test_status_ok(self):
        """status_code 'OK' maps to STATUS_CODE_OK (1)."""
        spans = [_make_span_dict(status_code="OK")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        # STATUS_CODE_OK = 1
        assert otlp_span.status.code == 1

    def test_status_error_with_message(self):
        """status_code 'ERROR' maps to STATUS_CODE_ERROR (2) with message."""
        spans = [_make_span_dict(status_code="ERROR", status_message="timeout")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        # STATUS_CODE_ERROR = 2
        assert otlp_span.status.code == 2
        assert otlp_span.status.message == "timeout"

    def test_status_unset(self):
        """status_code 'UNSET' maps to STATUS_CODE_UNSET (0)."""
        spans = [_make_span_dict(status_code="UNSET")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]
        assert otlp_span.status.code == 0

    def test_service_name_in_resource(self):
        """service_name appears as resource attribute service.name."""
        spans = [_make_span_dict(service_name="my-api")]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        resource = req.resource_spans[0].resource
        attr_map = {
            kv.key: kv.value.string_value for kv in resource.attributes
        }
        assert attr_map["service.name"] == "my-api"

    def test_multiple_spans_same_service(self):
        """Multiple spans with same service are grouped in one ResourceSpans."""
        spans = [
            _make_span_dict(span_id="a" * 16, service_name="api"),
            _make_span_dict(span_id="b" * 16, service_name="api"),
        ]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        assert len(req.resource_spans) == 1
        assert len(req.resource_spans[0].scope_spans[0].spans) == 2

    def test_multiple_spans_different_services(self):
        """Spans with different services are in separate ResourceSpans."""
        spans = [
            _make_span_dict(service_name="api"),
            _make_span_dict(service_name="worker"),
        ]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        assert len(req.resource_spans) == 2

    def test_empty_span_list(self):
        """Empty list produces valid empty request."""
        data = serialize_spans([])
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        assert len(req.resource_spans) == 0

    def test_pending_span_fields_present(self):
        """AC1: pending_span has required fields: trace_id, span_id, span_name, start_time, span_type."""
        spans = [_make_span_dict(
            span_type="pending_span",
            end_time=None,
            attributes={"http.method": "GET", "http.route": "/api/users"},
        )]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        otlp_span = req.resource_spans[0].scope_spans[0].spans[0]

        assert len(otlp_span.trace_id) == 16
        assert len(otlp_span.span_id) == 8
        assert otlp_span.name == "GET /api/users"
        assert otlp_span.start_time_unix_nano > 0
        attr_map = {kv.key: kv.value.string_value for kv in otlp_span.attributes}
        assert attr_map["tracely.span_type"] == "pending_span"
        assert attr_map["http.method"] == "GET"
        assert attr_map["http.route"] == "/api/users"

    def test_none_service_name(self):
        """Handles None service_name gracefully."""
        spans = [_make_span_dict(service_name=None)]
        data = serialize_spans(spans)
        req = ExportTraceServiceRequest()
        req.ParseFromString(data)
        resource = req.resource_spans[0].resource
        attr_map = {
            kv.key: kv.value.string_value for kv in resource.attributes
        }
        assert attr_map.get("service.name", "unknown") in ("unknown", "")

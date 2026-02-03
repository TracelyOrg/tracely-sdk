# v0.1.0

First public release of the TRACELY SDK -- lightweight observability for Python web frameworks.

## Highlights

Zero-config auto-instrumentation for **FastAPI**, **Flask**, and **Django** with real-time distributed tracing. The SDK captures full request/response data, exports via OTLP/HTTP protobuf, and never crashes your application.

## Features

### Core SDK
- **Zero-config initialization** -- `tracely.init(api_key="...")` reads from env vars or explicit params by @charlesdzadu
- **Framework auto-detection** -- automatically detects FastAPI, Flask, and Django at import time by @charlesdzadu
- **Graceful shutdown** -- `tracely.shutdown()` flushes all buffered spans before exit by @charlesdzadu

### Auto-Instrumentation
- **FastAPI ASGI middleware** -- `TracelyASGIMiddleware` wraps async apps with full request/response capture by @charlesdzadu
- **Flask WSGI middleware** -- `TracelyWSGIMiddleware` wraps sync WSGI apps with request/response capture by @charlesdzadu
- **Django middleware** -- `TracelyDjangoMiddleware` follows Django middleware protocol by @charlesdzadu
- **HTTPX client instrumentation** -- traces outbound HTTP calls as child spans by @charlesdzadu
- **Database API instrumentation** -- traces DB queries via Python DB-API 2.0 by @charlesdzadu

### Tracing & Spans
- **Span creation with trace hierarchy** -- root and child spans with automatic parent propagation by @charlesdzadu
- **Custom spans API** -- `tracely.span("name")` context manager for manual instrumentation by @charlesdzadu
- **Pending span pattern** -- spans exported immediately on start (`pending_span`) for real-time dashboard visibility by @charlesdzadu
- **Span events / structured logging** -- `tracely.info()`, `tracely.debug()`, `tracely.warning()`, `tracely.error()` by @charlesdzadu

### Data Capture & Privacy
- **Full request/response data capture** -- headers, body, query params, status codes by @charlesdzadu
- **Smart data redaction** -- auto-redacts Authorization, Cookie, passwords, tokens, API keys by @charlesdzadu
- **Custom redaction fields** -- `TRACELY_REDACT_FIELDS` env var for additional sensitive fields by @charlesdzadu
- **Binary body detection** -- replaces binary content with `[binary]` placeholder by @charlesdzadu

### Transport & Export
- **OTLP/HTTP protobuf export** -- standard OpenTelemetry wire format via `opentelemetry-proto` by @charlesdzadu
- **Batch span exporter** -- background daemon thread with 1s flush interval or 50-span threshold by @charlesdzadu
- **Exponential backoff retry** -- 1s, 2s, 4s, max 30s on transport failure by @charlesdzadu
- **Buffer limit** -- 1000 span cap, drops oldest when full by @charlesdzadu
- **Fail-silent design** -- all SDK operations catch errors silently, host app never affected by @charlesdzadu

## Dependencies

- `httpx>=0.27`
- `opentelemetry-proto>=1.20`
- Python 3.10+

## Contributors

@charlesdzadu

## Assets

- `tracely_sdk-0.1.0-py3-none-any.whl`
- `tracely_sdk-0.1.0.tar.gz`

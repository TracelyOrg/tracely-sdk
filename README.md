# tracely-sdk

Lightweight observability SDK for Python web frameworks. Auto-instruments **FastAPI**, **Flask**, and **Django** with real-time distributed tracing via OTLP/HTTP.

[![PyPI version](https://img.shields.io/pypi/v/tracely-sdk.svg)](https://pypi.org/project/tracely-sdk/)
[![Python](https://img.shields.io/pypi/pyversions/tracely-sdk.svg)](https://pypi.org/project/tracely-sdk/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

## Features

- **Zero-config auto-instrumentation** -- detects FastAPI, Flask, and Django automatically
- **Real-time pending spans** -- see requests the moment they start, not just when they finish
- **Full request/response capture** -- headers, body, query params with smart redaction
- **OTLP/HTTP protobuf export** -- standard OpenTelemetry wire format
- **Batch export with backoff** -- 1s flush interval, exponential retry on failure
- **Fail-silent design** -- SDK never crashes or degrades your application
- **Minimal dependencies** -- only `httpx` and `opentelemetry-proto`

## Installation

```bash
pip install tracely-sdk
```

## Quick Start

### FastAPI

```python
import tracely
from tracely.instrumentation.fastapi_inst import TracelyASGIMiddleware

tracely.init(api_key="trly_your_key_here")

from fastapi import FastAPI
app = FastAPI()
app.add_middleware(TracelyASGIMiddleware)

@app.get("/")
async def root():
    return {"status": "ok"}
```

### Flask

```python
import tracely
from tracely.instrumentation.flask_inst import FlaskInstrumentor

tracely.init(api_key="trly_your_key_here")

from flask import Flask
app = Flask(__name__)
app.wsgi_app = FlaskInstrumentor.wrap_app(app.wsgi_app)

@app.route("/")
def root():
    return {"status": "ok"}
```

### Django

Add the middleware to your `MIDDLEWARE` setting:

```python
# settings.py
MIDDLEWARE = [
    "tracely.instrumentation.django_inst.TracelyDjangoMiddleware",
    # ... other middleware
]
```

Then initialize in your app startup (e.g., `AppConfig.ready()`):

```python
import tracely
tracely.init(api_key="trly_your_key_here")
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `TRACELY_API_KEY` | API key for authentication | _(required)_ |
| `TRACELY_ENDPOINT` | Ingestion API endpoint | `https://api.tracely.dev` |
| `ENVIRONMENT` | Deployment environment (e.g., `production`) | `None` |
| `TRACELY_REDACT_FIELDS` | Comma-separated header/field names to redact | `None` |

### Programmatic Init

```python
import tracely

tracely.init(
    api_key="trly_your_key_here",
    environment="production",
    service_name="my-api",
    service_version="1.0.0",
)
```

## Custom Spans

Create manual spans for custom operations:

```python
import tracely

with tracely.span("db-query", kind="CLIENT") as s:
    s.set_attribute("db.system", "postgres")
    s.set_attribute("db.statement", "SELECT * FROM users")
    result = db.execute("SELECT * FROM users")
```

## Span Events (Structured Logging)

Attach structured log events to the active span:

```python
import tracely

with tracely.span("process-order") as s:
    tracely.info("Order received", order_id="123")
    # ... process
    tracely.debug("Validation passed")
    tracely.warning("Inventory low", sku="WIDGET-42")
```

## Graceful Shutdown

Flush buffered spans before exit:

```python
import tracely

tracely.init(api_key="trly_your_key_here")
# ... application runs ...
tracely.shutdown()  # flushes remaining spans
```

## How It Works

```
Your App
  |
  v
Middleware (FastAPI/Flask/Django)
  |-- on_start --> SpanProcessor --> SpanBuffer (pending_span)
  |-- on_end ----> SpanProcessor --> SpanBuffer (final span)
                                        |
                                        v
                                  BatchSpanExporter (1s interval / 50 span threshold)
                                        |
                                        v
                                  OTLP Protobuf Serialization
                                        |
                                        v
                                  HttpTransport --> TRACELY API
                                  (retry with exponential backoff)
```

## License

MIT

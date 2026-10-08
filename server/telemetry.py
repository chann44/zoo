import logging
import os

from fastapi import FastAPI
from opentelemetry import metrics, trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.metrics.view import ExplicitBucketHistogramAggregation, View
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from logger.logger import logger
from server.metrics import DURATION_BUCKETS, error

tracer = trace.get_tracer("zoo")


def setup_telemetry(app: FastAPI):
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return
    resource = Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "zoo-api")})
    traces = TracerProvider(resource=resource)
    traces.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(traces)
    logs = LoggerProvider(resource=resource)
    logs.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logs)
    handler = LoggingHandler(level=logging.INFO, logger_provider=logs)
    logger.addHandler(handler)
    logging.getLogger("uvicorn.access").addHandler(handler)
    # durations are in seconds, so they need buckets in seconds rather than the SDK's millisecond defaults
    seconds = ExplicitBucketHistogramAggregation(DURATION_BUCKETS)
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=15000)
    metrics.set_meter_provider(
        MeterProvider(
            resource=resource,
            metric_readers=[reader],
            views=[
                View(instrument_name="zoo.job.duration", aggregation=seconds),
                View(instrument_name="zoo.job.wait", aggregation=seconds),
                View(instrument_name="zoo.tool.duration", aggregation=seconds),
            ],
        )
    )
    SQLite3Instrumentor().instrument()
    FastAPIInstrumentor.instrument_app(app, excluded_urls="health")

    @app.middleware("http")
    async def count_server_errors(request, call_next):
        try:
            response = await call_next(request)
        except Exception:
            error("http", status="500")
            raise
        if response.status_code >= 500:
            error("http", status=str(response.status_code))
        return response

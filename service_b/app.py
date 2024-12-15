import os
import time

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace.status import Status, StatusCode

# Configure tracing with sampling
sampler = ParentBasedTraceIdRatio(0.3)  # Sample 30% of traces
trace.set_tracer_provider(
    TracerProvider(
        resource=Resource.create(
            {
                "service.name": "service-b",
                "service.version": "0.1.0",
                "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
            }
        ),
        sampler=sampler,
    )
)
jaeger_exporter = JaegerExporter(agent_host_name="jaeger", agent_port=6831)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))

# Initialize FastAPI
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()


@app.get("/process")
def process():
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("process_request") as span:
        try:
            span.set_attributes({"endpoint": "/process", "processing.type": "standard"})

            # Simulate some work
            time.sleep(2)
            result = {"message": "Processing in Service B"}

            span.set_attributes(
                {"processing.success": True, "result.size": len(str(result))}
            )
            return result

        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise

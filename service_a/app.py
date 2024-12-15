import requests
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.trace.status import Status, StatusCode
import os

# Configure tracing with sampling
sampler = ParentBasedTraceIdRatio(0.3)  # Sample 30% of traces
trace.set_tracer_provider(
    TracerProvider(
        resource=Resource.create({
            "service.name": "service-a",
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development")
        }),
        sampler=sampler
    )
)
jaeger_exporter = JaegerExporter(agent_host_name="localhost", agent_port=6831)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))

# Initialize FastAPI
app = FastAPI()
FastAPIInstrumentor.instrument_app(app)
RequestsInstrumentor().instrument()


@app.get("/call-service-b")
def call_service_b():
    tracer = trace.get_tracer(__name__)
    with tracer.start_as_current_span("call_service_b") as span:
        try:
            # Add meaningful attributes
            span.set_attributes({
                "endpoint": "/call-service-b",
                "target_service": "service-b"
            })
            
            # Prepare headers for context propagation
            carrier = {}
            TraceContextTextMapPropagator().inject(carrier)
            headers = {**carrier}
            
            response = requests.get(
                "http://localhost:8001/process",
                headers=headers
            )
            response.raise_for_status()
            
            span.set_attributes({
                "http.status_code": response.status_code,
                "http.response_content_length": len(response.content)
            })
            return {"service_b_response": response.json()}
            
        except Exception as e:
            span.set_status(Status(StatusCode.ERROR))
            span.record_exception(e)
            raise

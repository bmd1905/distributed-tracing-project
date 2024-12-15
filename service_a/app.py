import requests
from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

# Configure tracing
trace.set_tracer_provider(
    TracerProvider(resource=Resource.create({"service.name": "service-a"}))
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
    with tracer.start_as_current_span("call_service_b_span"):
        response = requests.get("http://localhost:8001/process")
        return {"service_b_response": response.json()}

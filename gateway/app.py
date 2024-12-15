import asyncio
import os
import random
from typing import Dict

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.propagate import inject, set_global_textmap

# Service registry (in production, use service discovery like Consul/etcd)
SERVICE_REGISTRY = {
    "service-a": ["http://service-a:8000"],
    "service-b": ["http://service-b:8001"],
}

# Circuit breaker configuration
FAILURE_THRESHOLD = 5
RESET_TIMEOUT = 60  # seconds
circuit_state: Dict[str, dict] = {}

# Configure tracing
sampler = ParentBasedTraceIdRatio(0.3)
trace.set_tracer_provider(
    TracerProvider(
        resource=Resource.create(
            {
                "service.name": "api-gateway",
                "service.version": "0.1.0",
                "deployment.environment": os.getenv("DEPLOYMENT_ENV", "development"),
            }
        ),
        sampler=sampler,
    )
)
jaeger_exporter = JaegerExporter(agent_host_name="jaeger", agent_port=6831)
trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))

app = FastAPI(title="API Gateway")
FastAPIInstrumentor.instrument_app(app)

# Initialize HTTP client
http_client = httpx.AsyncClient(timeout=30.0)

# Set W3C TraceContext as the global propagator
set_global_textmap(TraceContextTextMapPropagator())


async def check_circuit_breaker(service: str) -> bool:
    """Check if circuit breaker is tripped for a service"""
    if service not in circuit_state:
        circuit_state[service] = {"failures": 0, "last_failure": 0}

    state = circuit_state[service]
    if state["failures"] >= FAILURE_THRESHOLD:
        if (asyncio.get_event_loop().time() - state["last_failure"]) > RESET_TIMEOUT:
            state["failures"] = 0
            return True
        return False
    return True


async def record_failure(service: str):
    """Record a service failure"""
    if service not in circuit_state:
        circuit_state[service] = {"failures": 0, "last_failure": 0}

    circuit_state[service]["failures"] += 1
    circuit_state[service]["last_failure"] = asyncio.get_event_loop().time()


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.api_route("/{service}/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def gateway_route(service: str, path: str, request: Request):
    """Main gateway route handler"""
    tracer = trace.get_tracer(__name__)

    with tracer.start_as_current_span("gateway_route") as span:
        try:
            # Check if service exists
            if service not in SERVICE_REGISTRY:
                raise HTTPException(
                    status_code=404, detail=f"Service '{service}' not found"
                )

            # Check circuit breaker
            if not await check_circuit_breaker(service):
                raise HTTPException(
                    status_code=503,
                    detail=f"Service '{service}' is temporarily unavailable",
                )

            # Get service endpoints and select one randomly (simple load balancing)
            endpoints = SERVICE_REGISTRY[service]
            endpoint = random.choice(endpoints)

            # Add tracing context
            span.set_attributes(
                {
                    "gateway.service": service,
                    "gateway.path": path,
                    "gateway.method": request.method,
                    "gateway.endpoint": endpoint,
                }
            )

            # Prepare headers with trace context
            headers = dict(request.headers)
            inject(headers)  # This will inject W3C trace context headers

            # Forward the request
            url = f"{endpoint}/{path}"
            body = await request.body()

            response = await http_client.request(
                method=request.method, url=url, headers=headers, content=body
            )

            # Record response metrics
            span.set_attributes(
                {
                    "http.status_code": response.status_code,
                    "http.response_length": len(response.content),
                }
            )

            return JSONResponse(
                content=response.json(),
                status_code=response.status_code,
                headers=dict(response.headers),
            )

        except httpx.RequestError as e:
            await record_failure(service)
            span.record_exception(e)
            raise HTTPException(status_code=503, detail=str(e))

        except Exception as e:
            span.record_exception(e)
            raise HTTPException(status_code=500, detail=str(e))


@app.on_event("shutdown")
async def shutdown_event():
    await http_client.aclose()

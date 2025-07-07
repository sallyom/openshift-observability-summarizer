# Traces MCP Service

This service provides distributed tracing capabilities for the AI Observability platform through integration with Grafana Tempo.

## Features

- **MCP Protocol Compliance**: Integrates with Llama Stack as a pluggable MCP server
- **Natural Language Queries**: Convert plain English to TraceQL queries
- **Trace Search**: Filter traces by service, operation, duration, and tags
- **Performance Analysis**: Extract metrics and insights from trace data
- **Graceful Degradation**: Handles missing Tempo configuration elegantly

## Configuration

### Environment Variables

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `TEMPO_URL` | Tempo API endpoint | Yes | None |
| `TEMPO_AUTH_TOKEN` | Authentication token for Tempo | No | None |

### Example Configuration

```bash
# Required - Tempo endpoint
export TEMPO_URL="http://tempo:3200"

# Optional - if Tempo requires authentication
export TEMPO_AUTH_TOKEN="your-tempo-token"
```

## Deployment

### With Helm

```bash
# Deploy traces-mcp service
helm install traces-mcp ./deploy/helm/traces-mcp \
  --set tempo.url="http://tempo:3200" \
  --set tempo.authToken="your-token"  # optional
```

### With Docker

```bash
# Build the image
docker build -t traces-mcp ./observability-ui/traces-mcp/

# Run with Tempo configuration
docker run -p 8001:8001 \
  -e TEMPO_URL="http://tempo:3200" \
  traces-mcp
```

## API Endpoints

### Health Check
```bash
GET /health
```

Returns service status and Tempo connectivity information.

### MCP Protocol
```bash
POST /
```

Main MCP protocol endpoint for Llama Stack integration.

### Direct API Access

#### Search Traces
```bash
POST /api/search
Content-Type: application/json

{
  "service_name": "frontend",
  "min_duration": "100ms",
  "limit": 20
}
```

#### TraceQL Query
```bash
POST /api/traceql
Content-Type: application/json

{
  "query": "{.service.name=\"frontend\" && .duration > 1s}",
  "limit": 10
}
```

#### Get Trace Details
```bash
GET /api/traces/{trace_id}
```

#### Natural Language Translation
```bash
POST /api/translate
Content-Type: application/json

{
  "question": "Show me slow requests to the payment service"
}
```

## MCP Tools

The service provides these tools for Llama Stack:

1. **search_traces** - Search traces by filters
2. **get_trace_by_id** - Retrieve specific trace details
3. **search_with_traceql** - Execute TraceQL queries
4. **analyze_trace_performance** - Extract performance metrics
5. **translate_natural_language** - Convert natural language to TraceQL

## Usage Examples

### Natural Language Queries

```bash
curl -X POST http://localhost:8001/api/translate \
  -H "Content-Type: application/json" \
  -d '{"question": "Find errors in the frontend service"}'
```

Response:
```json
{
  "question": "Find errors in the frontend service",
  "traceql_query": "{.service.name=\"frontend\" && .status.code=2}",
  "examples": [...]
}
```

### TraceQL Queries

```bash
curl -X POST http://localhost:8001/api/traceql \
  -H "Content-Type: application/json" \
  -d '{
    "query": "{.service.name=\"payment\" && .duration > 500ms}",
    "limit": 5
  }'
```

## Graceful Degradation

When `TEMPO_URL` is not configured:

1. **UI Navigation**: Traces option is disabled with helpful message
2. **Health Endpoint**: Returns degraded status with explanation
3. **API Calls**: Return 503 Service Unavailable with clear error messages
4. **MCP Tools**: Fail gracefully with appropriate error responses

## Troubleshooting

### Service Not Starting

1. Check if `TEMPO_URL` is configured
2. Verify Tempo is accessible from the service
3. Check service logs for initialization errors

### Traces Not Found

1. Verify Tempo contains trace data
2. Check time range filters
3. Ensure service names match exactly
4. Try broader search criteria

### Performance Issues

1. Reduce search limit
2. Use more specific filters
3. Check Tempo performance
4. Verify network connectivity

## Development

### Running Locally

```bash
cd observability-ui/traces-mcp
pip install -r requirements.txt
export TEMPO_URL="http://localhost:3200"
python traces_mcp.py
```

### Testing

```bash
# Health check
curl http://localhost:8001/health

# Search traces
curl -X POST http://localhost:8001/api/search \
  -H "Content-Type: application/json" \
  -d '{"limit": 5}'
```

## Integration with Llama Stack

Add to `llama-stack` configuration:

```yaml
llama-stack:
  mcp-servers:
    mcp-traces:
      uri: http://traces-mcp:8001/sse
```

This enables natural language queries like:
- "Show me slow traces from the last hour"
- "Find errors in the payment service"
- "What traces have high latency?"
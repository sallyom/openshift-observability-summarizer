# Traces MCP Server for Llama Stack
# Provides distributed tracing capabilities via Tempo integration

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, AsyncGenerator
import asyncio
import json
import os
import logging
from datetime import datetime, timedelta
import sys
import traceback

# Add the parent directory to sys.path to import clients
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clients.tempo_client import TempoClient, TraceQLTranslator

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Traces MCP Server", description="Distributed Tracing MCP for Llama Stack")

# Configuration
TEMPO_URL = os.getenv("TEMPO_URL")
TEMPO_AUTH_TOKEN = os.getenv("TEMPO_AUTH_TOKEN")

# Initialize clients only if Tempo is configured
tempo_client = None
traceql_translator = TraceQLTranslator()

if TEMPO_URL:
    tempo_client = TempoClient(TEMPO_URL, TEMPO_AUTH_TOKEN)
    logger.info(f"Initialized Tempo client with URL: {TEMPO_URL}")
else:
    logger.warning("TEMPO_URL not configured - traces functionality will be disabled")

# Pydantic models for MCP protocol
class MCPRequest(BaseModel):
    method: str
    params: Optional[Dict[str, Any]] = None

class MCPResponse(BaseModel):
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

class TraceSearchRequest(BaseModel):
    service_name: Optional[str] = None
    operation_name: Optional[str] = None
    tags: Optional[Dict[str, str]] = None
    min_duration: Optional[str] = None
    max_duration: Optional[str] = None
    limit: int = 20
    start_time: Optional[str] = None
    end_time: Optional[str] = None

class TraceQLRequest(BaseModel):
    query: str
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    limit: int = 20

class NaturalLanguageRequest(BaseModel):
    question: str
    context: Optional[Dict[str, Any]] = None

# MCP Tool Definitions
MCP_TOOLS = [
    {
        "name": "search_traces",
        "description": "Search for distributed traces using various filters",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Filter by service name"},
                "operation_name": {"type": "string", "description": "Filter by operation name"},
                "tags": {"type": "object", "description": "Key-value pairs for tag filtering"},
                "min_duration": {"type": "string", "description": "Minimum trace duration (e.g. '100ms')"},
                "max_duration": {"type": "string", "description": "Maximum trace duration (e.g. '1s')"},
                "limit": {"type": "integer", "description": "Maximum number of traces to return", "default": 20},
                "start_time": {"type": "string", "description": "Start time (ISO format)"},
                "end_time": {"type": "string", "description": "End time (ISO format)"}
            }
        }
    },
    {
        "name": "get_trace_by_id",
        "description": "Retrieve detailed information for a specific trace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "The trace ID to retrieve"}
            },
            "required": ["trace_id"]
        }
    },
    {
        "name": "search_with_traceql",
        "description": "Search traces using TraceQL query language",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "TraceQL query (e.g. '{.service.name=\"frontend\"}')"},
                "start_time": {"type": "string", "description": "Start time (ISO format)"},
                "end_time": {"type": "string", "description": "End time (ISO format)"},
                "limit": {"type": "integer", "description": "Maximum number of traces to return", "default": 20}
            },
            "required": ["query"]
        }
    },
    {
        "name": "analyze_trace_performance",
        "description": "Analyze performance metrics for a specific trace",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_id": {"type": "string", "description": "The trace ID to analyze"}
            },
            "required": ["trace_id"]
        }
    },
    {
        "name": "translate_natural_language",
        "description": "Convert natural language queries to TraceQL",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Natural language query about traces"},
                "available_services": {"type": "array", "items": {"type": "string"}, "description": "List of known services"}
            },
            "required": ["question"]
        }
    }
]

# Utility functions
def parse_timestamp(timestamp_str: str) -> datetime:
    """Parse ISO timestamp string to datetime"""
    if timestamp_str:
        try:
            return datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        except ValueError:
            # Fallback for simple formats
            return datetime.fromisoformat(timestamp_str)
    return None

def format_trace_summary(trace_data: Dict[str, Any]) -> str:
    """Format trace data for LLM consumption"""
    if not trace_data:
        return "No trace data available"
    
    traces = trace_data.get('traces', [])
    if not traces:
        return "No traces found"
    
    summary_lines = [f"Found {len(traces)} traces:"]
    
    for i, trace in enumerate(traces[:5]):  # Show first 5
        trace_id = trace.get('traceID', 'Unknown')[:16]
        duration = trace.get('duration', 0) / 1000000  # Convert to ms
        service = trace.get('rootServiceName', 'Unknown')
        spans = trace.get('spanCount', 0)
        
        summary_lines.append(
            f"{i+1}. Trace {trace_id}: {duration:.2f}ms, {spans} spans, service: {service}"
        )
    
    if len(traces) > 5:
        summary_lines.append(f"... and {len(traces) - 5} more traces")
    
    return "\n".join(summary_lines)

# MCP Protocol Endpoints

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    if not TEMPO_URL:
        return {
            "status": "degraded",
            "tempo_configured": False,
            "tempo_connection": False,
            "service": "traces-mcp",
            "message": "TEMPO_URL not configured"
        }
    
    if not tempo_client:
        return {
            "status": "degraded",
            "tempo_configured": True,
            "tempo_connection": False,
            "service": "traces-mcp",
            "message": "Tempo client initialization failed"
        }
    
    tempo_healthy = await tempo_client.health_check()
    return {
        "status": "healthy" if tempo_healthy else "degraded",
        "tempo_configured": True,
        "tempo_connection": tempo_healthy,
        "service": "traces-mcp",
        "tempo_url": TEMPO_URL
    }

@app.post("/")
async def mcp_handler(request: MCPRequest):
    """Main MCP protocol handler"""
    try:
        method = request.method
        params = request.params or {}
        
        if method == "initialize":
            return MCPResponse(result={
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {"listChanged": True}
                },
                "serverInfo": {
                    "name": "traces-mcp",
                    "version": "1.0.0"
                }
            })
        
        elif method == "tools/list":
            return MCPResponse(result={"tools": MCP_TOOLS})
        
        elif method == "tools/call":
            tool_name = params.get("name")
            arguments = params.get("arguments", {})
            
            if tool_name == "search_traces":
                result = await handle_search_traces(arguments)
            elif tool_name == "get_trace_by_id":
                result = await handle_get_trace_by_id(arguments)
            elif tool_name == "search_with_traceql":
                result = await handle_search_with_traceql(arguments)
            elif tool_name == "analyze_trace_performance":
                result = await handle_analyze_trace_performance(arguments)
            elif tool_name == "translate_natural_language":
                result = await handle_translate_natural_language(arguments)
            else:
                raise HTTPException(status_code=400, detail=f"Unknown tool: {tool_name}")
            
            return MCPResponse(result=result)
        
        else:
            raise HTTPException(status_code=400, detail=f"Unknown method: {method}")
    
    except Exception as e:
        logger.error(f"MCP handler error: {e}")
        logger.error(traceback.format_exc())
        return MCPResponse(error={
            "code": -32603,
            "message": str(e)
        })

# Tool handlers

def check_tempo_availability():
    """Check if Tempo is available and raise appropriate error if not"""
    if not TEMPO_URL:
        raise HTTPException(status_code=503, detail="TEMPO_URL not configured")
    if not tempo_client:
        raise HTTPException(status_code=503, detail="Tempo client not initialized")

async def handle_search_traces(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle trace search requests"""
    check_tempo_availability()
    
    start_time = parse_timestamp(args.get("start_time"))
    end_time = parse_timestamp(args.get("end_time"))
    
    traces = await tempo_client.search_traces(
        service_name=args.get("service_name"),
        operation_name=args.get("operation_name"),
        tags=args.get("tags"),
        min_duration=args.get("min_duration"),
        max_duration=args.get("max_duration"),
        limit=args.get("limit", 20),
        start_time=start_time,
        end_time=end_time
    )
    
    if traces:
        summary = format_trace_summary(traces)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Trace Search Results:\n{summary}"
                }
            ],
            "raw_data": traces
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": "No traces found matching the criteria"
                }
            ]
        }

async def handle_get_trace_by_id(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle get trace by ID requests"""
    check_tempo_availability()
    
    trace_id = args.get("trace_id")
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id is required")
    
    trace_data = await tempo_client.get_trace_by_id(trace_id)
    
    if trace_data:
        # Get performance metrics
        metrics = await tempo_client.get_trace_metrics(trace_id)
        
        response_text = f"Trace {trace_id} Details:\n"
        if metrics:
            response_text += f"- Duration: {tempo_client.format_duration(metrics.get('total_duration_us', 0))}\n"
            response_text += f"- Spans: {metrics.get('span_count', 0)}\n"
            response_text += f"- Services: {', '.join(metrics.get('services', []))}\n"
            response_text += f"- Operations: {', '.join(metrics.get('operations', []))}\n"
            response_text += f"- Errors: {metrics.get('error_count', 0)}\n"
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": response_text
                }
            ],
            "raw_data": {
                "trace": trace_data,
                "metrics": metrics
            }
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Trace {trace_id} not found"
                }
            ]
        }

async def handle_search_with_traceql(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle TraceQL search requests"""
    check_tempo_availability()
    
    query = args.get("query")
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    
    start_time = parse_timestamp(args.get("start_time"))
    end_time = parse_timestamp(args.get("end_time"))
    
    traces = await tempo_client.search_with_traceql(
        traceql_query=query,
        start_time=start_time,
        end_time=end_time,
        limit=args.get("limit", 20)
    )
    
    if traces:
        summary = format_trace_summary(traces)
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"TraceQL Query Results for '{query}':\n{summary}"
                }
            ],
            "raw_data": traces
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"No traces found for TraceQL query: {query}"
                }
            ]
        }

async def handle_analyze_trace_performance(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle trace performance analysis requests"""
    check_tempo_availability()
    
    trace_id = args.get("trace_id")
    if not trace_id:
        raise HTTPException(status_code=400, detail="trace_id is required")
    
    metrics = await tempo_client.get_trace_metrics(trace_id)
    
    if metrics:
        analysis = f"Performance Analysis for Trace {trace_id}:\n\n"
        analysis += f"📊 **Overall Metrics:**\n"
        analysis += f"- Total Duration: {tempo_client.format_duration(metrics.get('total_duration_us', 0))}\n"
        analysis += f"- Span Count: {metrics.get('span_count', 0)}\n"
        analysis += f"- Average Span Duration: {tempo_client.format_duration(metrics.get('avg_span_duration_us', 0))}\n"
        analysis += f"- Error Rate: {metrics.get('error_rate', 0)*100:.1f}%\n\n"
        
        analysis += f"🔍 **Services Involved:**\n"
        for service in metrics.get('services', []):
            analysis += f"- {service}\n"
        
        analysis += f"\n⚡ **Performance Assessment:**\n"
        duration_us = metrics.get('total_duration_us', 0)
        if duration_us > 5000000:  # > 5 seconds
            analysis += "- ⚠️  High latency detected (>5s)\n"
        elif duration_us > 1000000:  # > 1 second
            analysis += "- ⚡ Moderate latency (>1s)\n"
        else:
            analysis += "- ✅ Good performance (<1s)\n"
        
        if metrics.get('error_count', 0) > 0:
            analysis += f"- ❌ {metrics.get('error_count')} errors detected\n"
        else:
            analysis += "- ✅ No errors detected\n"
        
        return {
            "content": [
                {
                    "type": "text",
                    "text": analysis
                }
            ],
            "raw_data": metrics
        }
    else:
        return {
            "content": [
                {
                    "type": "text",
                    "text": f"Unable to analyze trace {trace_id} - trace not found or no metrics available"
                }
            ]
        }

async def handle_translate_natural_language(args: Dict[str, Any]) -> Dict[str, Any]:
    """Handle natural language to TraceQL translation"""
    question = args.get("question")
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    
    available_services = args.get("available_services", [])
    
    traceql_query = await traceql_translator.translate_to_traceql(question, available_services)
    
    # Get some examples for context
    examples = await traceql_translator.get_query_examples()
    
    response_text = f"Natural Language Translation:\n\n"
    response_text += f"**Question:** {question}\n"
    response_text += f"**TraceQL:** `{traceql_query}`\n\n"
    response_text += f"**Example Queries:**\n"
    
    for example in examples[:3]:  # Show first 3 examples
        response_text += f"- \"{example['natural']}\" → `{example['traceql']}`\n"
    
    return {
        "content": [
            {
                "type": "text",
                "text": response_text
            }
        ],
        "traceql_query": traceql_query,
        "examples": examples
    }

# SSE endpoint for real-time MCP communication
@app.get("/sse")
async def sse_endpoint():
    """Server-Sent Events endpoint for Llama Stack MCP communication"""
    async def event_generator() -> AsyncGenerator[str, None]:
        # Initial connection message
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected'})}\n\n"
        
        # Keep connection alive
        while True:
            yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': datetime.now().isoformat()})}\n\n"
            await asyncio.sleep(30)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )

# Standard HTTP endpoints for direct API access
@app.post("/api/search")
async def api_search_traces(request: TraceSearchRequest):
    """Direct API endpoint for trace search"""
    check_tempo_availability()
    
    start_time = parse_timestamp(request.start_time)
    end_time = parse_timestamp(request.end_time)
    
    traces = await tempo_client.search_traces(
        service_name=request.service_name,
        operation_name=request.operation_name,
        tags=request.tags,
        min_duration=request.min_duration,
        max_duration=request.max_duration,
        limit=request.limit,
        start_time=start_time,
        end_time=end_time
    )
    
    return traces or {"traces": []}

@app.post("/api/traceql")
async def api_traceql_search(request: TraceQLRequest):
    """Direct API endpoint for TraceQL search"""
    check_tempo_availability()
    
    start_time = parse_timestamp(request.start_time)
    end_time = parse_timestamp(request.end_time)
    
    traces = await tempo_client.search_with_traceql(
        traceql_query=request.query,
        start_time=start_time,
        end_time=end_time,
        limit=request.limit
    )
    
    return traces or {"traces": []}

@app.get("/api/traces/{trace_id}")
async def api_get_trace(trace_id: str):
    """Direct API endpoint for trace retrieval"""
    check_tempo_availability()
    
    trace_data = await tempo_client.get_trace_by_id(trace_id)
    metrics = await tempo_client.get_trace_metrics(trace_id)
    
    if trace_data:
        return {
            "trace": trace_data,
            "metrics": metrics
        }
    else:
        raise HTTPException(status_code=404, detail="Trace not found")

@app.post("/api/translate")
async def api_translate_natural_language(request: NaturalLanguageRequest):
    """Direct API endpoint for natural language translation"""
    available_services = request.context.get("available_services", []) if request.context else []
    
    traceql_query = await traceql_translator.translate_to_traceql(request.question, available_services)
    examples = await traceql_translator.get_query_examples()
    
    return {
        "question": request.question,
        "traceql_query": traceql_query,
        "examples": examples
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
# Tempo Client for Distributed Tracing
# Integrates with Tempo API for trace search and retrieval

import asyncio
import aiohttp
import os
from typing import Dict, List, Optional, Union
from datetime import datetime, timedelta
import json
import logging

logger = logging.getLogger(__name__)

class TempoClient:
    """
    Client for interacting with Grafana Tempo distributed tracing backend.
    Supports trace search, retrieval, and TraceQL queries.
    """
    
    def __init__(self, tempo_url: str = None, auth_token: str = None):
        self.tempo_url = tempo_url or os.getenv("TEMPO_URL", "http://tempo:3200")
        self.auth_token = auth_token or os.getenv("TEMPO_AUTH_TOKEN")
        self.headers = {}
        
        if self.auth_token:
            self.headers["Authorization"] = f"Bearer {self.auth_token}"
        
        # Remove trailing slash
        self.tempo_url = self.tempo_url.rstrip('/')
        
    async def health_check(self) -> bool:
        """Check if Tempo is accessible"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.tempo_url}/api/echo",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    return response.status == 200
        except Exception as e:
            logger.error(f"Tempo health check failed: {e}")
            return False
    
    async def search_traces(
        self, 
        service_name: str = None,
        operation_name: str = None,
        tags: Dict[str, str] = None,
        min_duration: str = None,
        max_duration: str = None,
        limit: int = 20,
        start_time: datetime = None,
        end_time: datetime = None
    ) -> Optional[Dict]:
        """
        Search for traces using Tempo's search API
        
        Args:
            service_name: Filter by service name
            operation_name: Filter by operation name  
            tags: Key-value pairs for tag filtering
            min_duration: Minimum trace duration (e.g. "100ms")
            max_duration: Maximum trace duration (e.g. "1s")
            limit: Maximum number of traces to return
            start_time: Start time for search range
            end_time: End time for search range
        """
        try:
            params = {}
            
            if service_name:
                params["service.name"] = service_name
            if operation_name:
                params["name"] = operation_name
            if min_duration:
                params["minDuration"] = min_duration
            if max_duration:
                params["maxDuration"] = max_duration
            if limit:
                params["limit"] = str(limit)
            
            # Add tag filters
            if tags:
                for key, value in tags.items():
                    params[key] = value
            
            # Set time range (default to last hour)
            if not end_time:
                end_time = datetime.now()
            if not start_time:
                start_time = end_time - timedelta(hours=1)
                
            params["start"] = int(start_time.timestamp())
            params["end"] = int(end_time.timestamp())
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.tempo_url}/api/search",
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Tempo search failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error searching traces: {e}")
            return None
    
    async def get_trace_by_id(self, trace_id: str) -> Optional[Dict]:
        """
        Retrieve a specific trace by its ID
        
        Args:
            trace_id: The trace ID to retrieve
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.tempo_url}/api/traces/{trace_id}",
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"Tempo trace retrieval failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error retrieving trace {trace_id}: {e}")
            return None
    
    async def search_with_traceql(
        self, 
        traceql_query: str,
        start_time: datetime = None,
        end_time: datetime = None,
        limit: int = 20
    ) -> Optional[Dict]:
        """
        Search traces using TraceQL query language
        
        Args:
            traceql_query: TraceQL query string (e.g., '{.service.name="frontend"}')
            start_time: Start time for search range
            end_time: End time for search range
            limit: Maximum number of traces to return
        """
        try:
            # Set time range (default to last hour)
            if not end_time:
                end_time = datetime.now()
            if not start_time:
                start_time = end_time - timedelta(hours=1)
            
            params = {
                "q": traceql_query,
                "start": int(start_time.timestamp()),
                "end": int(end_time.timestamp()),
                "limit": str(limit)
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.tempo_url}/api/search",
                    params=params,
                    headers=self.headers,
                    timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"TraceQL search failed: {response.status}")
                        return None
                        
        except Exception as e:
            logger.error(f"Error executing TraceQL query '{traceql_query}': {e}")
            return None
    
    async def get_trace_metrics(self, trace_id: str) -> Optional[Dict]:
        """
        Extract performance metrics from a trace
        
        Args:
            trace_id: The trace ID to analyze
        """
        try:
            trace_data = await self.get_trace_by_id(trace_id)
            if not trace_data:
                return None
            
            # Extract basic metrics from trace structure
            batches = trace_data.get("batches", [])
            if not batches:
                return None
            
            spans = []
            for batch in batches:
                spans.extend(batch.get("spans", []))
            
            if not spans:
                return None
            
            # Calculate trace metrics
            span_count = len(spans)
            durations = []
            services = set()
            operations = set()
            errors = 0
            
            for span in spans:
                # Duration calculation (assuming microseconds)
                start_time = span.get("startTimeUnixNano", 0)
                end_time = span.get("endTimeUnixNano", 0)
                duration_us = (end_time - start_time) / 1000  # Convert to microseconds
                durations.append(duration_us)
                
                # Service and operation names
                process = span.get("process", {})
                service_name = process.get("serviceName", "unknown")
                services.add(service_name)
                
                operation_name = span.get("operationName", "unknown")
                operations.add(operation_name)
                
                # Error detection
                tags = span.get("tags", [])
                for tag in tags:
                    if tag.get("key") == "error" and tag.get("vBool"):
                        errors += 1
                        break
            
            total_duration = max(durations) if durations else 0
            avg_span_duration = sum(durations) / len(durations) if durations else 0
            
            return {
                "trace_id": trace_id,
                "span_count": span_count,
                "total_duration_us": total_duration,
                "avg_span_duration_us": avg_span_duration,
                "services": list(services),
                "operations": list(operations),
                "error_count": errors,
                "error_rate": errors / span_count if span_count > 0 else 0
            }
            
        except Exception as e:
            logger.error(f"Error calculating trace metrics for {trace_id}: {e}")
            return None
    
    def format_duration(self, duration_us: float) -> str:
        """Format duration in microseconds to human-readable string"""
        if duration_us < 1000:
            return f"{duration_us:.1f}μs"
        elif duration_us < 1000000:
            return f"{duration_us/1000:.1f}ms"
        else:
            return f"{duration_us/1000000:.2f}s"

class TraceQLTranslator:
    """
    Translates natural language queries to TraceQL
    """
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        
    async def translate_to_traceql(self, natural_query: str, available_services: List[str] = None) -> str:
        """
        Convert natural language to TraceQL query
        
        Args:
            natural_query: Natural language description
            available_services: List of known services for context
        """
        # Simple rule-based translation for now
        # In full implementation, this would use LLM
        
        query_lower = natural_query.lower()
        traceql_parts = []
        
        # Service name detection
        if available_services:
            for service in available_services:
                if service.lower() in query_lower:
                    traceql_parts.append(f'.service.name="{service}"')
                    break
        
        # Duration conditions
        if "slow" in query_lower or "latency" in query_lower:
            traceql_parts.append('.duration > 1s')
        elif "fast" in query_lower:
            traceql_parts.append('.duration < 100ms')
        
        # Error conditions
        if "error" in query_lower or "fail" in query_lower:
            traceql_parts.append('.status.code = 2')  # ERROR status
        
        # HTTP method detection
        for method in ["GET", "POST", "PUT", "DELETE"]:
            if method.lower() in query_lower:
                traceql_parts.append(f'.http.method = "{method}"')
                break
        
        # Build final query
        if traceql_parts:
            return "{" + " && ".join(traceql_parts) + "}"
        else:
            # Default fallback - return all traces
            return "{}"
    
    async def get_query_examples(self) -> List[Dict[str, str]]:
        """Return example natural language queries and their TraceQL equivalents"""
        return [
            {
                "natural": "Show me slow requests to the payment service",
                "traceql": '{.service.name="payment" && .duration > 1s}'
            },
            {
                "natural": "Find errors in the frontend service",
                "traceql": '{.service.name="frontend" && .status.code = 2}'
            },
            {
                "natural": "Get all POST requests with high latency",
                "traceql": '{.http.method = "POST" && .duration > 500ms}'
            },
            {
                "natural": "Find traces for user authentication",
                "traceql": '{.operation.name =~ ".*auth.*"}'
            }
        ]

# Example usage
async def main():
    """Example usage of TempoClient"""
    client = TempoClient()
    
    # Health check
    is_healthy = await client.health_check()
    print(f"Tempo health: {'✅' if is_healthy else '❌'}")
    
    if is_healthy:
        # Search for traces
        traces = await client.search_traces(
            service_name="frontend",
            min_duration="100ms",
            limit=10
        )
        
        if traces:
            print(f"Found {len(traces.get('traces', []))} traces")
            
            # Get details for first trace
            if traces.get('traces'):
                trace_id = traces['traces'][0].get('traceID')
                trace_details = await client.get_trace_by_id(trace_id)
                trace_metrics = await client.get_trace_metrics(trace_id)
                
                print(f"Trace {trace_id} metrics:")
                print(f"  Spans: {trace_metrics.get('span_count')}")
                print(f"  Duration: {client.format_duration(trace_metrics.get('total_duration_us', 0))}")
                print(f"  Services: {trace_metrics.get('services')}")

if __name__ == "__main__":
    asyncio.run(main())
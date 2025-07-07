# main_page.py - AI Model Metric Summarizer
import streamlit as st
import requests
from datetime import datetime
import pandas as pd
import os
import streamlit.components.v1 as components
import base64
import matplotlib.pyplot as plt
import io
import time

# --- Config ---
API_URL = os.getenv("MCP_API_URL", "http://localhost:8000")
PROM_URL = os.getenv("PROM_URL", "http://localhost:9090")
TRACES_API_URL = os.getenv("TRACES_MCP_URL", "http://traces-mcp:8001")
TEMPO_URL = os.getenv("TEMPO_URL")  # Check if Tempo is configured

# --- Page Setup ---
st.set_page_config(page_title="AI Metric Tools", layout="wide")
st.markdown(
    """
<style>
    html, body, [class*="css"] { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto; }
    h1, h2, h3 { font-weight: 600; color: #1c1c1e; letter-spacing: -0.5px; }
    .stMetric { border-radius: 12px; background-color: #f9f9f9; padding: 1em; box-shadow: 0 2px 8px rgba(0,0,0,0.05); color: #1c1c1e !important; }
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"] { color: #1c1c1e !important; font-weight: 600; }
    .block-container { padding-top: 2rem; }
    .stButton>button { border-radius: 8px; padding: 0.5em 1.2em; font-size: 1em; }
    footer, header { visibility: hidden; }
</style>
""",
    unsafe_allow_html=True,
)

# --- Page Selector ---
st.sidebar.title("Navigation")

# Build navigation options based on available services
nav_options = ["📊 Metric Summarizer", "🤖 Chat with Prometheus"]

# Only add traces option if Tempo is configured
if TEMPO_URL:
    nav_options.append("🔍 Distributed Traces")
    # Add a small status indicator in sidebar
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔧 Services Status")
    st.sidebar.markdown("✅ **Metrics** - Available")
    st.sidebar.markdown("✅ **Traces** - Available")
else:
    # Show disabled traces option with explanation
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔧 Services Status")
    st.sidebar.markdown("✅ **Metrics** - Available")
    st.sidebar.markdown("🔍 **Distributed Traces**")
    st.sidebar.markdown("⚠️ *Tracing endpoint not configured*")
    st.sidebar.markdown("Set `TEMPO_URL` to enable tracing")

page = st.sidebar.radio("Go to:", nav_options)


# --- Shared Utilities ---
@st.cache_data(ttl=300)
def get_models():
    """Fetch available models from API"""
    try:
        res = requests.get(f"{API_URL}/models")
        return res.json()
    except Exception as e:
        st.sidebar.error(f"Error fetching models: {e}")
        return []


@st.cache_data(ttl=300)
def get_namespaces():
    try:
        res = requests.get(f"{API_URL}/models")
        models = res.json()
        # Extract unique namespaces from model names (format: "namespace | model")
        namespaces = sorted(
            list(set(model.split(" | ")[0] for model in models if " | " in model))
        )
        return namespaces
    except Exception as e:
        st.sidebar.error(f"Error fetching namespaces: {e}")
        return []


@st.cache_data(ttl=300)
def get_multi_models():
    """Fetch available summarization models from API"""
    try:
        res = requests.get(f"{API_URL}/multi_models")
        return res.json()
    except Exception as e:
        st.sidebar.error(f"Error fetching multi-models: {e}")
        return []


@st.cache_data(ttl=300)
def get_model_config():
    """Fetch model configuration from API"""
    try:
        res = requests.get(f"{API_URL}/model_config")
        return res.json()
    except Exception as e:
        st.sidebar.error(f"Error fetching model config: {e}")
        return {}


def model_requires_api_key(model_id, model_config):
    """Check if a model requires an API key based on unified configuration"""
    model_info = model_config.get(model_id, {})
    return model_info.get("requiresApiKey", False)


def clear_session_state():
    """Clear session state on errors"""
    for key in ["summary", "prompt", "metric_data"]:
        if key in st.session_state:
            del st.session_state[key]


def handle_http_error(response, context):
    """Handle HTTP errors and display appropriate messages"""
    if response.status_code == 401:
        st.error("❌ Unauthorized. Please check your API Key.")
    elif response.status_code == 403:
        st.error("❌ Forbidden. Please check your API Key.")
    elif response.status_code == 500:
        st.error("❌ Please check your API Key or try again later.")
    else:
        st.error(f"❌ {context}: {response.status_code} - {response.text}")


def trigger_download(
    file_content: bytes, filename: str, mime_type: str = "application/octet-stream"
):

    b64 = base64.b64encode(file_content).decode()

    dl_link = f"""
    <html>
    <body>
    <script>
    const link = document.createElement('a');
    link.href = "data:{mime_type};base64,{b64}";
    link.download = "{filename}";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    </script>
    </body>
    </html>
    """

    components.html(dl_link, height=0, width=0)


def get_metrics_data_and_list():
    """Get metrics data and list to avoid code duplication"""
    metric_data = st.session_state.get("metric_data", {})
    metrics = [
        "Prompt Tokens Created",
        "P95 Latency (s)",
        "Requests Running",
        "GPU Usage (%)",
        "Output Tokens Created",
        "Inference Time (s)",
    ]
    return metric_data, metrics


def get_calculated_metrics_from_mcp(metric_data):
    """Get calculated metrics from MCP backend"""
    try:
        response = requests.post(
            f"{API_URL}/calculate-metrics", json={"metrics_data": metric_data}
        )
        response.raise_for_status()
        return response.json()["calculated_metrics"]
    except Exception as e:
        st.error(f"Error getting calculated metrics from MCP: {e}")
        return {}


def process_chart_data(metric_data, chart_metrics=None):
    """Process metrics data for chart generation"""
    if chart_metrics is None:
        chart_metrics = ["GPU Usage (%)", "P95 Latency (s)"]

    dfs = []
    for label in chart_metrics:
        raw_data = metric_data.get(label, [])
        if raw_data:
            try:
                timestamps = [datetime.fromisoformat(p["timestamp"]) for p in raw_data]
                values = [p["value"] for p in raw_data]
                df = pd.DataFrame({label: values}, index=timestamps)
                dfs.append(df)
            except Exception:
                pass
    return dfs


def create_trend_chart_image(metric_data, chart_metrics=None):
    """Create trend chart image for reports"""
    dfs = process_chart_data(metric_data, chart_metrics)
    if not dfs:
        return None

    try:
        chart_df = pd.concat(dfs, axis=1).fillna(0)
        fig, ax = plt.subplots(figsize=(8, 4))
        chart_df.plot(ax=ax)
        ax.set_title("Trend Over Time")
        ax.set_xlabel("Timestamp")
        ax.set_ylabel("Value")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return base64.b64encode(buf.read()).decode("utf-8")
    except Exception:
        return None


def generate_report_and_download(report_format: str):
    try:
        analysis_params = st.session_state["analysis_params"]

        # Use the shared function to get metrics data
        metric_data, metrics = get_metrics_data_and_list()

        # Filter metrics_data to only include the metrics shown in dashboard
        filtered_metrics_data = {}
        for metric_name in metrics:
            if metric_name in metric_data:
                filtered_metrics_data[metric_name] = metric_data[metric_name]

        trend_chart_image_b64 = create_trend_chart_image(filtered_metrics_data)

        payload = {
            "model_name": analysis_params["model_name"],
            "start_ts": analysis_params["start_ts"],
            "end_ts": analysis_params["end_ts"],
            "summarize_model_id": analysis_params["summarize_model_id"],
            "format": report_format,
            "api_key": analysis_params["api_key"],
            "health_prompt": st.session_state["prompt"],
            "llm_summary": st.session_state["summary"],
            "metrics_data": filtered_metrics_data,
        }
        if trend_chart_image_b64:
            payload["trend_chart_image"] = trend_chart_image_b64
        response = requests.post(
            f"{API_URL}/generate_report",
            json=payload,
        )
        response.raise_for_status()
        report_id = response.json()["report_id"]
        download_response = requests.get(f"{API_URL}/download_report/{report_id}")
        download_response.raise_for_status()
        mime_map = {
            "HTML": "text/html",
            "PDF": "application/pdf",
            "Markdown": "text/markdown",
        }
        mime_type = mime_map.get(report_format, "application/octet-stream")
        filename = f"ai_metrics_report.{report_format.lower()}"
        trigger_download(download_response.content, filename, mime_type)
    except requests.exceptions.HTTPError as http_err:
        st.error(f"HTTP error during report generation: {http_err}")
    except Exception as e:
        st.error(f"❌ Error during report generation: {e}")


model_list = get_models()
namespaces = get_namespaces()

# Add namespace selector in sidebar
selected_namespace = st.sidebar.selectbox("Select Namespace", namespaces)

# Filter models by selected namespace
filtered_models = [
    model for model in model_list if model.startswith(f"{selected_namespace} | ")
]
model_name = st.sidebar.selectbox("Select Model", filtered_models)

st.sidebar.markdown("### Select Timestamp Range")
if "selected_date" not in st.session_state:
    st.session_state["selected_date"] = datetime.now().date()
if "selected_time" not in st.session_state:
    st.session_state["selected_time"] = datetime.now().time()
selected_date = st.sidebar.date_input("Date", value=st.session_state["selected_date"])
selected_time = st.sidebar.time_input("Time", value=st.session_state["selected_time"])
selected_datetime = datetime.combine(selected_date, selected_time)
now = datetime.now()
if selected_datetime > now:
    st.sidebar.warning("Please select a valid timestamp before current time.")
    st.stop()
selected_start = int(selected_datetime.timestamp())
selected_end = int(now.timestamp())


st.sidebar.markdown("---")

# --- Select LLM ---
st.sidebar.markdown("### Select LLM for summarization")

# --- Multi-model support ---
multi_model_list = get_multi_models()
multi_model_name = st.sidebar.selectbox(
    "Select LLM for summarization", multi_model_list
)

# --- Define model key requirements ---
model_config = get_model_config()
current_model_requires_api_key = model_requires_api_key(multi_model_name, model_config)


# --- API Key Input ---
api_key = st.sidebar.text_input(
    label="🔑 API Key",
    type="password",
    value=st.session_state.get("api_key", ""),
    help="Enter your API key if required by the selected model",
    disabled=not current_model_requires_api_key,
)

# Caption to show key requirement status
if current_model_requires_api_key:
    st.sidebar.caption("⚠️ This model requires an API key.")
else:
    st.sidebar.caption("✅ No API key is required for this model.")

# Optional validation warning if required key is missing
if current_model_requires_api_key and not api_key:
    st.sidebar.warning("🚫 Please enter an API key to use this model.")


# --- Report Generation ---
st.sidebar.markdown("---")
st.sidebar.markdown("### Download Report")

analysis_performed = st.session_state.get("analysis_performed", False)

if not analysis_performed:
    st.sidebar.warning("⚠️ Please analyze metrics first to generate a report.")

report_format = st.sidebar.selectbox(
    "Select Report Format", ["HTML", "PDF", "Markdown"], disabled=not analysis_performed
)

if analysis_performed:
    if "download_button_clicked" not in st.session_state:
        st.session_state.download_button_clicked = False

    if st.sidebar.button("📥 Download Report"):
        st.session_state.download_button_clicked = True

    # Move the spinner_placeholder definition AFTER the button
    spinner_placeholder = st.sidebar.empty()

    if st.session_state.download_button_clicked:
        with spinner_placeholder.container():
            with st.spinner("Downloading report..."):
                time.sleep(2)  # This line adds a 2-second delay
                generate_report_and_download(report_format)
        st.session_state.download_button_clicked = False

# --- 📊 Metric Summarizer Page ---
if page == "📊 Metric Summarizer":
    st.markdown("<h1>📊 AI Model Metric Summarizer</h1>", unsafe_allow_html=True)

    # --- Analyze Button ---
    if st.button("🔍 Analyze Metrics"):
        with st.spinner("Analyzing metrics..."):
            try:
                # Get parameters from sidebar
                params = {
                    "model_name": model_name,
                    "summarize_model_id": multi_model_name,
                    "start_ts": selected_start,
                    "end_ts": selected_end,
                    "api_key": api_key,
                }

                response = requests.post(f"{API_URL}/analyze", json=params)
                response.raise_for_status()
                result = response.json()

                # Store results in session state
                st.session_state["prompt"] = result["health_prompt"]
                st.session_state["summary"] = result["llm_summary"]
                st.session_state["model_name"] = params["model_name"]
                st.session_state["metric_data"] = result.get("metrics", {})
                st.session_state["analysis_params"] = (
                    params  # Store for report generation
                )
                st.session_state["analysis_performed"] = (
                    True  # Mark that analysis was performed
                )

                # Force rerun to update the UI state (enable download button and hide warning)
                st.rerun()

            except requests.exceptions.HTTPError as http_err:
                clear_session_state()
                handle_http_error(http_err.response, "Analysis failed")
            except Exception as e:
                clear_session_state()
                st.error(f"❌ Error during analysis: {e}")

    if "summary" in st.session_state:
        col1, col2 = st.columns([1.3, 1.7])
        with col1:
            st.markdown("### 🧠 Model Insights Summary")
            st.markdown(st.session_state["summary"])
            st.markdown("### 💬 Ask Assistant")
            question = st.text_input("Ask a follow-up question")
            if st.button("Ask"):
                with st.spinner("Assistant is thinking..."):
                    try:
                        reply = requests.post(
                            f"{API_URL}/chat",
                            json={
                                "model_name": st.session_state["model_name"],
                                "summarize_model_id": multi_model_name,
                                "prompt_summary": st.session_state["prompt"],
                                "question": question,
                                "api_key": api_key,
                            },
                        )
                        reply.raise_for_status()
                        st.markdown("**Assistant's Response:**")
                        st.markdown(reply.json()["response"])
                    except requests.exceptions.HTTPError as http_err:
                        handle_http_error(http_err.response, "Chat failed")
                    except Exception as e:
                        st.error(f"❌ Chat failed: {e}")

        with col2:
            st.markdown("### 📊 Metric Dashboard")
            # Use the shared function to get metrics data
            metric_data, metrics = get_metrics_data_and_list()

            # Get calculated metrics from MCP
            calculated_metrics = get_calculated_metrics_from_mcp(metric_data)

            cols = st.columns(3)
            for i, label in enumerate(metrics):
                with cols[i % 3]:
                    if label in calculated_metrics:
                        calc_data = calculated_metrics[label]
                        if (
                            calc_data["avg"] is not None
                            and calc_data["max"] is not None
                        ):
                            st.metric(
                                label=label,
                                value=f"{calc_data['avg']:.2f}",
                                delta=f"↑ Max: {calc_data['max']:.2f}",
                            )
                        else:
                            st.metric(label=label, value="N/A", delta="No data")
                    else:
                        st.metric(label=label, value="N/A", delta="No data")

            st.markdown("### 📈 Trend Over Time")
            dfs = process_chart_data(metric_data)
            if dfs:
                chart_df = pd.concat(dfs, axis=1).fillna(0)
                st.line_chart(chart_df)
            else:
                st.info("No data available to generate chart.")

# --- 🤖 Chat with Prometheus Page ---
elif page == "🤖 Chat with Prometheus":
    st.markdown("<h1>Chat with Prometheus</h1>", unsafe_allow_html=True)
    st.markdown(f"Currently selected namespace: **{selected_namespace}**")
    st.markdown(
        "Ask questions like: `What's the P95 latency?`, `Is GPU usage stable?`, etc."
    )
    user_question = st.text_input("Your question")
    if st.button("Chat with Metrics"):
        if not user_question.strip():
            st.warning("Please enter a question.")
        else:
            with st.spinner("Querying and summarizing..."):
                try:
                    response = requests.post(
                        f"{API_URL}/chat-metrics",
                        json={
                            "model_name": model_name,
                            "question": user_question,
                            "start_ts": selected_start,
                            "end_ts": selected_end,
                            "namespace": selected_namespace,  # Add namespace to the request
                            "summarize_model_id": multi_model_name,
                            "api_key": api_key,
                        },
                    )
                    data = response.json()
                    promql = data.get("promql", "")
                    summary = data.get("summary", "")
                    if not summary:
                        st.error("Error: Missing summary in response from AI.")
                    else:
                        st.markdown("**Generated PromQL:**")
                        if promql:
                            st.code(promql, language="yaml")
                        else:
                            st.info("No direct PromQL generated for this question.")
                        st.markdown("**AI Summary:**")
                        st.text(summary)
                except Exception as e:
                    st.error(f"Error: {e}")

elif page == "🔍 Distributed Traces":
    # This page should only be accessible if TEMPO_URL is configured
    if not TEMPO_URL:
        st.error("🚫 Distributed Traces is not available")
        st.info("Configure TEMPO_URL environment variable to enable tracing functionality")
        st.stop()
    
    st.markdown("<h1>🔍 Distributed Traces</h1>", unsafe_allow_html=True)
    st.markdown("Analyze distributed tracing data with natural language queries")
    
    # Check traces service health first
    traces_healthy = False
    tempo_configured = bool(TEMPO_URL)
    
    # Show configuration status
    with st.expander("🔧 Configuration Status"):
        col1, col2 = st.columns(2)
        with col1:
            if tempo_configured:
                st.success(f"✅ Tempo URL: `{TEMPO_URL}`")
            else:
                st.error("❌ Tempo URL not configured")
        
        with col2:
            try:
                health_response = requests.get(f"{TRACES_API_URL}/health", timeout=5)
                if health_response.status_code == 200:
                    st.success("✅ Traces MCP service connected")
                    traces_healthy = True
                else:
                    st.error("❌ Traces MCP service unavailable")
            except Exception as e:
                st.error(f"❌ Cannot connect to traces service: {str(e)}")
    
    # Only proceed if both Tempo is configured and traces service is healthy
    if not tempo_configured:
        st.error("🚫 Tempo endpoint not configured")
        st.markdown("""
        **To enable distributed tracing:**
        1. Set the `TEMPO_URL` environment variable (e.g., `http://tempo:3200`)
        2. Ensure Tempo is deployed and accessible
        3. Restart the application
        """)
        st.stop()
    
    if not traces_healthy:
        st.warning("⚠️ Traces service is not available")
        st.markdown("""
        **Troubleshooting:**
        1. Ensure the traces-mcp service is deployed and running
        2. Check that Tempo is accessible from the traces-mcp service
        3. Verify network connectivity between services
        """)
        st.stop()
    
    # Sidebar filters (only show if everything is working)
    with st.sidebar:
        st.markdown("### Trace Filters")
        trace_namespace = st.selectbox("Namespace", get_namespaces() or ["default"], key="trace_namespace")
        time_range = st.selectbox("Time Range", ["1h", "6h", "24h"], key="trace_time_range")
        
        st.markdown("### Service Filters")
        service_name = st.text_input("Service Name", placeholder="frontend", key="service_name")
        operation_name = st.text_input("Operation Name", placeholder="GET /api/users", key="operation_name")
        
        st.markdown("### Performance Filters")
        min_duration = st.text_input("Min Duration", placeholder="100ms", key="min_duration")
        max_duration = st.text_input("Max Duration", placeholder="5s", key="max_duration")
        
        max_traces = st.slider("Max Traces", 5, 50, 20, key="max_traces")
    
    # Create tabs for different trace operations
    tab1, tab2, tab3, tab4 = st.tabs(["🔍 Search Traces", "🤖 Natural Language", "📊 TraceQL Query", "📈 Trace Analysis"])
    
    with tab1:
        st.markdown("### Search Traces by Filters")
        
        if st.button("🔍 Search Traces", key="search_traces_btn"):
            with st.spinner("Searching traces..."):
                try:
                    # Build search parameters
                    search_params = {
                        "limit": max_traces
                    }
                    
                    if service_name:
                        search_params["service_name"] = service_name
                    if operation_name:
                        search_params["operation_name"] = operation_name
                    if min_duration:
                        search_params["min_duration"] = min_duration
                    if max_duration:
                        search_params["max_duration"] = max_duration
                    
                    # Call traces API
                    response = requests.post(f"{TRACES_API_URL}/api/search", json=search_params, timeout=30)
                    
                    if response.status_code == 200:
                        traces_data = response.json()
                        traces = traces_data.get('traces', [])
                        
                        if traces:
                            st.success(f"Found {len(traces)} traces")
                            
                            # Display traces in a nice format
                            for i, trace in enumerate(traces):
                                with st.expander(f"Trace {i+1}: {trace.get('traceID', 'Unknown')[:16]}..."):
                                    col1, col2, col3, col4 = st.columns(4)
                                    
                                    with col1:
                                        duration_ms = (trace.get('duration', 0) or 0) / 1000000
                                        st.metric("Duration", f"{duration_ms:.2f}ms")
                                    
                                    with col2:
                                        st.metric("Spans", trace.get('spanCount', 0))
                                    
                                    with col3:
                                        st.metric("Service", trace.get('rootServiceName', 'Unknown'))
                                    
                                    with col4:
                                        start_time = trace.get('startTime', 0)
                                        if start_time:
                                            start_dt = datetime.fromtimestamp(start_time / 1000000000)
                                            st.metric("Start Time", start_dt.strftime("%H:%M:%S"))
                                    
                                    # Trace ID for further analysis
                                    st.code(f"Trace ID: {trace.get('traceID', 'Unknown')}")
                                    
                                    # Analyze button
                                    if st.button(f"📊 Analyze Performance", key=f"analyze_{trace.get('traceID', i)}"):
                                        analyze_trace_performance(trace.get('traceID'))
                        else:
                            st.info("No traces found matching the criteria. Try adjusting your filters.")
                    elif response.status_code == 503:
                        st.error("🚫 Tempo endpoint not configured or unavailable")
                        st.info("Contact your administrator to configure distributed tracing")
                    else:
                        st.error(f"Search failed: {response.status_code}")
                        if response.status_code == 503:
                            st.info("The traces service indicates that Tempo is not properly configured")
                        
                except Exception as e:
                    st.error(f"Error searching traces: {e}")
    
    with tab2:
        st.markdown("### Natural Language Trace Queries")
        st.markdown("Ask questions about traces in plain English and get TraceQL queries")
        
        # Example queries
        with st.expander("💡 Example Questions"):
            st.markdown("""
            - "Show me slow requests to the payment service"
            - "Find errors in the frontend service"
            - "Get all POST requests with high latency"
            - "Find traces for user authentication"
            """)
        
        natural_question = st.text_area(
            "Ask about traces:", 
            placeholder="Show me slow requests to the payment service",
            key="natural_trace_question"
        )
        
        if st.button("🤖 Ask About Traces", key="natural_traces_btn"):
            if not natural_question.strip():
                st.warning("Please enter a question about traces.")
            else:
                with st.spinner("Translating to TraceQL and searching..."):
                    try:
                        # First, translate to TraceQL
                        translate_response = requests.post(
                            f"{TRACES_API_URL}/api/translate",
                            json={"question": natural_question},
                            timeout=10
                        )
                        
                        if translate_response.status_code == 200:
                            translation_data = translate_response.json()
                            traceql_query = translation_data.get('traceql_query', '{}')
                            
                            # Show the translation
                            st.markdown("**Generated TraceQL:**")
                            st.code(traceql_query, language="json")
                            
                            # Execute the TraceQL query
                            traceql_response = requests.post(
                                f"{TRACES_API_URL}/api/traceql",
                                json={"query": traceql_query, "limit": max_traces},
                                timeout=30
                            )
                            
                            if traceql_response.status_code == 200:
                                traces_data = traceql_response.json()
                                traces = traces_data.get('traces', [])
                                
                                if traces:
                                    st.success(f"Found {len(traces)} traces matching your question")
                                    display_traces_summary(traces)
                                else:
                                    st.info("No traces found for this query. Try rephrasing your question.")
                            else:
                                st.error("Failed to execute TraceQL query")
                        else:
                            st.error("Failed to translate natural language query")
                            
                    except Exception as e:
                        st.error(f"Error processing natural language query: {e}")
    
    with tab3:
        st.markdown("### Advanced TraceQL Queries")
        st.markdown("Write TraceQL queries directly for precise trace filtering")
        
        # TraceQL reference
        with st.expander("📚 TraceQL Reference"):
            st.markdown("""
            **Basic Syntax:**
            - `{.service.name="frontend"}` - Filter by service name
            - `{.duration > 1s}` - Filter by duration
            - `{.status.code = 2}` - Filter by status (2 = ERROR)
            - `{.http.method = "POST"}` - Filter by HTTP method
            
            **Combinations:**
            - `{.service.name="payment" && .duration > 500ms}` - Multiple conditions
            - `{.service.name =~ ".*auth.*"}` - Regex matching
            """)
        
        traceql_query = st.text_area(
            "TraceQL Query:",
            value='{}',
            placeholder='{.service.name="frontend" && .duration > 1s}',
            key="traceql_query"
        )
        
        if st.button("🔍 Execute TraceQL", key="traceql_btn"):
            if not traceql_query.strip():
                st.warning("Please enter a TraceQL query.")
            else:
                with st.spinner("Executing TraceQL query..."):
                    try:
                        response = requests.post(
                            f"{TRACES_API_URL}/api/traceql",
                            json={"query": traceql_query, "limit": max_traces},
                            timeout=30
                        )
                        
                        if response.status_code == 200:
                            traces_data = response.json()
                            traces = traces_data.get('traces', [])
                            
                            if traces:
                                st.success(f"TraceQL returned {len(traces)} traces")
                                display_traces_summary(traces)
                            else:
                                st.info("No traces found for this TraceQL query.")
                        else:
                            st.error(f"TraceQL query failed: {response.status_code}")
                            
                    except Exception as e:
                        st.error(f"Error executing TraceQL query: {e}")
    
    with tab4:
        st.markdown("### Individual Trace Analysis")
        st.markdown("Analyze performance metrics for a specific trace")
        
        trace_id_input = st.text_input(
            "Trace ID:",
            placeholder="Enter trace ID for detailed analysis",
            key="trace_id_analysis"
        )
        
        if st.button("📊 Analyze Trace", key="analyze_trace_btn"):
            if not trace_id_input.strip():
                st.warning("Please enter a trace ID.")
            else:
                analyze_trace_performance(trace_id_input)

def display_traces_summary(traces):
    """Display a summary of traces in a nice format"""
    for i, trace in enumerate(traces[:10]):  # Show first 10 traces
        with st.expander(f"Trace {i+1}: {trace.get('traceID', 'Unknown')[:16]}..."):
            col1, col2, col3 = st.columns(3)
            
            with col1:
                duration_ms = (trace.get('duration', 0) or 0) / 1000000
                st.metric("Duration", f"{duration_ms:.2f}ms")
            
            with col2:
                st.metric("Spans", trace.get('spanCount', 0))
            
            with col3:
                st.metric("Service", trace.get('rootServiceName', 'Unknown'))
            
            # Show trace ID
            st.code(f"Trace ID: {trace.get('traceID', 'Unknown')}")

def analyze_trace_performance(trace_id):
    """Analyze performance for a specific trace"""
    with st.spinner(f"Analyzing trace {trace_id}..."):
        try:
            response = requests.get(f"{TRACES_API_URL}/api/traces/{trace_id}", timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                trace_data = data.get('trace')
                metrics = data.get('metrics')
                
                if metrics:
                    st.markdown("### 📊 Performance Analysis")
                    
                    # Performance metrics
                    col1, col2, col3, col4 = st.columns(4)
                    
                    with col1:
                        total_duration_us = metrics.get('total_duration_us', 0)
                        if total_duration_us > 1000000:
                            duration_display = f"{total_duration_us/1000000:.2f}s"
                        elif total_duration_us > 1000:
                            duration_display = f"{total_duration_us/1000:.1f}ms"
                        else:
                            duration_display = f"{total_duration_us:.0f}μs"
                        st.metric("Total Duration", duration_display)
                    
                    with col2:
                        st.metric("Span Count", metrics.get('span_count', 0))
                    
                    with col3:
                        error_rate = metrics.get('error_rate', 0) * 100
                        st.metric("Error Rate", f"{error_rate:.1f}%")
                    
                    with col4:
                        avg_duration_us = metrics.get('avg_span_duration_us', 0)
                        if avg_duration_us > 1000:
                            avg_display = f"{avg_duration_us/1000:.1f}ms"
                        else:
                            avg_display = f"{avg_duration_us:.0f}μs"
                        st.metric("Avg Span Duration", avg_display)
                    
                    # Services involved
                    st.markdown("### 🔍 Services Involved")
                    services = metrics.get('services', [])
                    if services:
                        st.write(", ".join(services))
                    else:
                        st.info("No service information available")
                    
                    # Performance assessment
                    st.markdown("### ⚡ Performance Assessment")
                    total_duration_us = metrics.get('total_duration_us', 0)
                    error_count = metrics.get('error_count', 0)
                    
                    if total_duration_us > 5000000:  # > 5 seconds
                        st.warning("⚠️ High latency detected (>5s)")
                    elif total_duration_us > 1000000:  # > 1 second
                        st.info("⚡ Moderate latency (>1s)")
                    else:
                        st.success("✅ Good performance (<1s)")
                    
                    if error_count > 0:
                        st.error(f"❌ {error_count} errors detected")
                    else:
                        st.success("✅ No errors detected")
                else:
                    st.error("No performance metrics available for this trace")
            else:
                st.error(f"Failed to retrieve trace: {response.status_code}")
                
        except Exception as e:
            st.error(f"Error analyzing trace: {e}")

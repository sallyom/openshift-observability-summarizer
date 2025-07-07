import base64
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import pandas as pd
import requests
from datetime import datetime
from scipy.stats import linregress
import os
import json
import re
from typing import List, Dict, Any, Optional
import uuid

from report_assets.report_renderer import (
    generate_html_report,
    generate_markdown_report,
    generate_pdf_report,
    ReportSchema,
    MetricCard,
)


app = FastAPI()

# --- CONFIG ---
PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://localhost:9090")
LLAMA_STACK_URL = os.getenv("LLAMA_STACK_URL", "http://localhost:8321/v1/openai/v1")
LLM_API_TOKEN = os.getenv("LLM_API_TOKEN", "")

# Load unified model configuration from environment
MODEL_CONFIG = {}
try:
    model_config_str = os.getenv("MODEL_CONFIG", "{}")
    MODEL_CONFIG = json.loads(model_config_str)
except Exception as e:
    print(f"Warning: Could not parse MODEL_CONFIG: {e}")
    MODEL_CONFIG = {}

# Handle token input from volume or literal
token_input = os.getenv(
    "THANOS_TOKEN", "/var/run/secrets/kubernetes.io/serviceaccount/token"
)
if os.path.exists(token_input):
    with open(token_input, "r") as f:
        THANOS_TOKEN = f.read().strip()
else:
    THANOS_TOKEN = token_input

# CA bundle location (mounted via ConfigMap)
CA_BUNDLE_PATH = "/etc/pki/ca-trust/extracted/pem/ca-bundle.crt"
verify = CA_BUNDLE_PATH if os.path.exists(CA_BUNDLE_PATH) else True

# --- Metric Queries ---
ALL_METRICS = {
    "Prompt Tokens Created": "vllm:request_prompt_tokens_created",
    "P95 Latency (s)": "vllm:e2e_request_latency_seconds_count",
    "Requests Running": "vllm:num_requests_running",
    "GPU Usage (%)": "vllm:gpu_cache_usage_perc",
    "Output Tokens Created": "vllm:request_generation_tokens_created",
    "Inference Time (s)": "vllm:request_inference_time_seconds_count",
    "Total Requests": "vllm:num_total_requests",
    "Finished Requests": "vllm:num_finished_requests",
    "Aborted Requests": "vllm:num_aborted_requests",
    "Batched Tokens": "vllm:num_batched_tokens",
    "GPU Cache Usage (Bytes)": "vllm:gpu_cache_usage_bytes",
    "Scheduler Running Queue Size": "vllm:scheduler_running_queue_size",
    "Scheduler Waiting Queue Size": "vllm:scheduler_waiting_queue_size",
    "Scheduler Swapped Queue Size": "vllm:scheduler_swapped_queue_size",
    "Cache Config Info": "vllm:cache_config_info",
    "E2E Latency Seconds Bucket": "vllm:e2e_request_latency_seconds_bucket",
    "E2E Latency Seconds Created": "vllm:e2e_request_latency_seconds_created",
    "E2E Latency Seconds Sum": "vllm:e2e_request_latency_seconds_sum",
    "Generation Tokens Created": "vllm:generation_tokens_created",
    "Generation Tokens Total": "vllm:generation_tokens_total",
    "GPU Prefix Cache Hits Created": "vllm:gpu_prefix_cache_hits_created",
    "GPU Prefix Cache Hits Total": "vllm:gpu_prefix_cache_hits_total",
    "GPU Prefix Cache Queries Created": "vllm:gpu_prefix_cache_queries_created",
    "GPU Prefix Cache Queries Total": "vllm:gpu_prefix_cache_queries_total",
    "Iteration Tokens Total Bucket": "vllm:iteration_tokens_total_bucket",
    "Iteration Tokens Total Count": "vllm:iteration_tokens_total_count",
    "Iteration Tokens Total Created": "vllm:iteration_tokens_total_created",
    "Iteration Tokens Total Sum": "vllm:iteration_tokens_total_sum",
    "Num Preemptions Created": "vllm:num_preemptions_created",
    "Num Preemptions Total": "vllm:num_preemptions_total",
    "Num Requests Waiting": "vllm:num_requests_waiting",
    "Prompt Tokens Total": "vllm:prompt_tokens_total",
    "Request Decode Time Seconds Bucket": "vllm:request_decode_time_seconds_bucket",
    "Request Decode Time Seconds Count": "vllm:request_decode_time_seconds_count",
    "Request Decode Time Seconds Created": "vllm:request_decode_time_seconds_created",
    "Request Decode Time Seconds Sum": "vllm:request_decode_time_seconds_sum",
    "Request Generation Tokens Bucket": "vllm:request_generation_tokens_bucket",
    "Request Generation Tokens Count": "vllm:request_generation_tokens_count",
    "Request Generation Tokens Sum": "vllm:request_generation_tokens_sum",
    "Request Inference Time Seconds Bucket": "vllm:request_inference_time_seconds_bucket",
    "Request Inference Time Seconds Created": "vllm:request_inference_time_seconds_created",
    "Request Inference Time Seconds Sum": "vllm:request_inference_time_seconds_sum",
    "Request Max Num Generation Tokens Bucket": "vllm:request_max_num_generation_tokens_bucket",
    "Request Max Num Generation Tokens Count": "vllm:request_max_num_generation_tokens_count",
    "Request Max Num Generation Tokens Created": "vllm:request_max_num_generation_tokens_created",
    "Request Max Num Generation Tokens Sum": "vllm:request_max_num_generation_tokens_sum",
    "Request Params Max Tokens Bucket": "vllm:request_params_max_tokens_bucket",
    "Request Params Max Tokens Count": "vllm:request_params_max_tokens_count",
    "Request Params Max Tokens Created": "vllm:request_params_max_tokens_created",
    "Request Params Max Tokens Sum": "vllm:request_params_max_tokens_sum",
    "Request Params N Bucket": "vllm:request_params_n_bucket",
    "Request Params N Count": "vllm:request_params_n_count",
    "Request Params N Created": "vllm:request_params_n_created",
    "Request Params N Sum": "vllm:request_params_n_sum",
    "Request Prefill Time Seconds Bucket": "vllm:request_prefill_time_seconds_bucket",
    "Request Prefill Time Seconds Count": "vllm:request_prefill_time_seconds_count",
    "Request Prefill Time Seconds Created": "vllm:request_prefill_time_seconds_created",
    "Request Prefill Time Seconds Sum": "vllm:request_prefill_time_seconds_sum",
    "Request Prompt Tokens Bucket": "vllm:request_prompt_tokens_bucket",
    "Request Prompt Tokens Count": "vllm:request_prompt_tokens_count",
    "Request Prompt Tokens Sum": "vllm:request_prompt_tokens_sum",
    "Request Queue Time Seconds Bucket": "vllm:request_queue_time_seconds_bucket",
    "Request Queue Time Seconds Count": "vllm:request_queue_time_seconds_count",
    "Request Queue Time Seconds Created": "vllm:request_queue_time_seconds_created",
    "Request Queue Time Seconds Sum": "vllm:request_queue_time_seconds_sum",
    "Request Success Created": "vllm:request_success_created",
    "Request Success Total": "vllm:request_success_total",
    "Spec Decode Num Accepted Tokens Created": "vllm:spec_decode_num_accepted_tokens_created",
}


# --- Request Models ---
class AnalyzeRequest(BaseModel):
    model_name: str
    start_ts: int
    end_ts: int
    summarize_model_id: str
    api_key: Optional[str] = None


class ChatRequest(BaseModel):
    model_name: str
    prompt_summary: str
    question: str
    summarize_model_id: str
    api_key: Optional[str] = None


class ChatMetricsRequest(BaseModel):
    model_name: str
    question: str
    start_ts: int
    end_ts: int
    namespace: str
    summarize_model_id: str
    api_key: Optional[str] = None


class ReportRequest(BaseModel):
    model_name: str
    start_ts: int
    end_ts: int
    summarize_model_id: str
    format: str
    api_key: Optional[str] = None
    health_prompt: Optional[str] = None
    llm_summary: Optional[str] = None
    metrics_data: Optional[Dict[str, Any]] = None
    trend_chart_image: Optional[str] = None


class MetricsCalculationRequest(BaseModel):
    metrics_data: Dict[str, List[Dict[str, Any]]]


class MetricsCalculationResponse(BaseModel):
    calculated_metrics: Dict[str, Dict[str, Optional[float]]]


# --- Helpers ---
def fetch_metrics(query, model_name, start, end, namespace=None):
    # If namespace is provided, ensure it's included in the query
    if namespace:
        namespace = namespace.strip()
        if "|" in model_name:
            model_namespace, actual_model_name = map(
                str.strip, model_name.split("|", 1)
            )
            promql_query = (
                f'{query}{{model_name="{actual_model_name}", namespace="{namespace}"}}'
            )
        else:
            promql_query = (
                f'{query}{{model_name="{model_name}", namespace="{namespace}"}}'
            )
    else:
        # Original logic if no namespace is explicitly provided (for backward compatibility or other endpoints)
        if "|" in model_name:
            namespace, model_name = map(str.strip, model_name.split("|", 1))
            promql_query = (
                f'{query}{{model_name="{model_name}", namespace="{namespace}"}}'
            )
        else:
            model_name = model_name.strip()
            promql_query = f'{query}{{model_name="{model_name}"}}'

    headers = {"Authorization": f"Bearer {THANOS_TOKEN}"}
    response = requests.get(
        f"{PROMETHEUS_URL}/api/v1/query_range",
        headers=headers,
        params={"query": promql_query, "start": start, "end": end, "step": "30s"},
        verify=verify,
    )
    response.raise_for_status()
    result = response.json()["data"]["result"]

    rows = []
    for series in result:
        for val in series["values"]:
            ts = datetime.fromtimestamp(float(val[0]))
            value = float(val[1])
            row = dict(series["metric"])
            row["timestamp"] = ts
            row["value"] = value
            rows.append(row)

    return pd.DataFrame(rows)


def detect_anomalies(df, label):
    if df.empty:
        return "No data"
    mean = df["value"].mean()
    std = df["value"].std()
    p90 = df["value"].quantile(0.9)
    latest_val = df["value"].iloc[-1]
    if latest_val > p90:
        return f"⚠️ {label} spike (latest={latest_val:.2f}, >90th pct)"
    elif latest_val < (mean - std):
        return f"⚠️ {label} unusually low (latest={latest_val:.2f}, mean={mean:.2f})"
    return f"{label} stable (latest={latest_val:.2f}, mean={mean:.2f})"


def describe_trend(df):
    if df.empty or len(df) < 2:
        return "not enough data"
    df = df.sort_values("timestamp")
    x = (df["timestamp"] - df["timestamp"].min()).dt.total_seconds()
    y = df["value"]
    if x.nunique() <= 1:
        return "flat"
    slope, *_ = linregress(x, y)
    if slope > 0.01:
        return "increasing"
    elif slope < -0.01:
        return "decreasing"
    return "stable"


def compute_health_score(metric_dfs):
    score, reasons = 0, []
    if "P95 Latency (s)" in metric_dfs and not metric_dfs["P95 Latency (s)"].empty:
        mean = metric_dfs["P95 Latency (s)"]["value"].mean()
        if mean > 2:
            score -= 2
            reasons.append(f"High Latency (avg={mean:.2f}s)")
    if "GPU Usage (%)" in metric_dfs and not metric_dfs["GPU Usage (%)"].empty:
        mean = metric_dfs["GPU Usage (%)"]["value"].mean()
        if mean < 10:
            score -= 1
            reasons.append(f"Low GPU Utilization (avg={mean:.2f}%)")
    if "Requests Running" in metric_dfs and not metric_dfs["Requests Running"].empty:
        mean = metric_dfs["Requests Running"]["value"].mean()
        if mean > 10:
            score -= 1
            reasons.append(f"Too many requests (avg={mean:.2f})")
    return score, reasons


def build_prompt(metric_dfs, model_name):
    score, _ = compute_health_score(metric_dfs)
    header = f"You are evaluating model **{model_name}**.\n\n🩺 Health Score: {score}\n\n📊 **Metrics**:\n"
    lines = []
    for label, df in metric_dfs.items():
        if df.empty:
            lines.append(f"- {label}: No data")
            continue
        trend = describe_trend(df)
        anomaly = detect_anomalies(df, label)
        avg = df["value"].mean()
        # Add an indication if data is present
        data_status = "Data present" if not df.empty else "No data"
        lines.append(
            f"- {label}: Avg={avg:.2f}, Trend={trend}, {anomaly} ({data_status})"
        )
    return f"""{header}
{chr(10).join(lines)}

🔍 Please analyze:
1. What's going well?
2. What's problematic?
3. Recommendations?
""".strip()


def build_chat_prompt(user_question: str, metrics_summary: str) -> str:
    return f"""
You are a senior MLOps engineer reviewing real-time Prometheus metrics and providing operational insights.

Your task is to answer **ANY type of observability question**, whether specific (e.g., "What is GPU usage?") or generic (e.g., "What's going wrong?", "Can I send more load?").

Use ONLY the information in the **metrics summary** to answer.

---
📊 Metrics Summary:
{metrics_summary.strip()}
---

🧠 Guidelines:
- Use your judgment as an MLOps expert.
- If the metrics look abnormal or risky, call it out.
- If something seems healthy, confirm it clearly.
- Do NOT restate the user's question.
- NEVER say "I'm an assistant" or explain how you're generating your response.
- Do NOT exceed 100 words.
- Use real metric names (e.g., "GPU Usage (%)", "P95 Latency (s)").
- Be direct, like a technical Slack message.
- If the user asks about scaling or sending more load, use "Requests Running", "Latency", or "GPU Usage" to justify your answer.

---
👤 User Prompt:
{user_question.strip()}
---

Now provide a concise, technical summary that answers it.
""".strip()


def _make_api_request(
    url: str, headers: dict, payload: dict, verify_ssl: bool = True
) -> dict:
    """Make API request with consistent error handling"""
    response = requests.post(url, headers=headers, json=payload, verify=verify_ssl)
    response.raise_for_status()
    return response.json()


def _validate_and_extract_response(
    response_json: dict, is_external: bool, provider: str = "LLM"
) -> str:
    """Validate response format and extract content"""
    if "choices" not in response_json or not response_json["choices"]:
        raise ValueError(f"Invalid {provider} response format")

    if is_external:
        return response_json["choices"][0]["message"]["content"].strip()
    else:
        return response_json["choices"][0]["text"].strip()


# New helper function to aggressively clean LLM summary strings
def _clean_llm_summary_string(text: str) -> str:
    # Remove any non-printable ASCII characters (except common whitespace like space, tab, newline)
    cleaned_text = re.sub(r"[^\x20-\x7E\n\t]", "", text)
    # Replace multiple spaces/newlines/tabs with single spaces, then strip leading/trailing whitespace
    cleaned_text = re.sub(r"\s+", " ", cleaned_text).strip()
    return cleaned_text


def summarize_with_llm(
    prompt: str, summarize_model_id: str, api_key: Optional[str] = None
) -> str:
    headers = {"Content-Type": "application/json"}

    # Get model configuration
    model_info = MODEL_CONFIG.get(summarize_model_id, {})
    is_external = model_info.get("external", False)

    if is_external:
        # External model (like OpenAI, Anthropic, etc.)
        if not api_key:
            raise ValueError(
                f"API key required for external model {summarize_model_id}"
            )

        # Get provider-specific configuration
        provider = model_info.get("provider", "openai")
        api_url = model_info.get("apiUrl", "https://api.openai.com/v1/chat/completions")
        model_name = model_info.get("modelName")

        headers["Authorization"] = f"Bearer {api_key}"

        # Convert to OpenAI chat format
        payload = {
            "model": model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.5,
            "max_tokens": 1000,
        }

        response_json = _make_api_request(api_url, headers, payload, verify_ssl=True)
        return _validate_and_extract_response(
            response_json, is_external=True, provider=provider
        )

    else:
        # Local model (deployed in cluster)
        if LLM_API_TOKEN:
            headers["Authorization"] = f"Bearer {LLM_API_TOKEN}"

        payload = {
            "model": summarize_model_id,
            "prompt": prompt,
            "temperature": 0.5,
            "max_tokens": 1000,
        }

        response_json = _make_api_request(
            f"{LLAMA_STACK_URL}/completions", headers, payload, verify_ssl=verify
        )

        return _validate_and_extract_response(
            response_json, is_external=False, provider="LLM"
        )


@app.get("/health")
def health():
    return {"status": "ok"}


# Helper to get models (extracted from list_models endpoint)
def _get_models_helper():
    try:
        headers = {"Authorization": f"Bearer {THANOS_TOKEN}"}
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/series",
            headers=headers,
            params={
                "match[]": "vllm:request_prompt_tokens_created",
                "start": int((datetime.now().timestamp()) - 3600),
                "end": int(datetime.now().timestamp()),
            },
            verify=verify,
        )
        response.raise_for_status()
        series = response.json()["data"]

        model_set = set()
        for entry in series:
            model = entry.get("model_name", "").strip()
            namespace = entry.get("namespace", "").strip()
            if model and namespace:
                model_set.add(f"{namespace} | {model}")
        return sorted(list(model_set))
    except Exception as e:
        print("Error getting models:", e)
        return []


@app.get("/models")
def list_models():
    return _get_models_helper()


@app.get("/namespaces")
def list_namespaces():
    try:
        headers = {"Authorization": f"Bearer {THANOS_TOKEN}"}
        response = requests.get(
            f"{PROMETHEUS_URL}/api/v1/series",
            headers=headers,
            params={
                "match[]": "vllm:request_prompt_tokens_created",
                "start": int(
                    (datetime.now().timestamp()) - 86400
                ),  # last 24 hours for better coverage
                "end": int(datetime.now().timestamp()),
            },
            verify=verify,
        )
        response.raise_for_status()
        series = response.json()["data"]

        namespace_set = set()
        for entry in series:
            namespace = entry.get("namespace", "").strip()
            model = entry.get("model_name", "").strip()
            if namespace and model:
                namespace_set.add(namespace)
        return sorted(list(namespace_set))
    except Exception as e:
        print("Error getting namespaces:", e)
        return []


@app.get("/multi_models")
def list_multi_models():
    """Get available summarization models from configuration"""
    return list(MODEL_CONFIG.keys())


@app.get("/model_config")
def get_model_config():
    return MODEL_CONFIG


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        metric_dfs = {
            label: fetch_metrics(query, req.model_name, req.start_ts, req.end_ts)
            for label, query in ALL_METRICS.items()
        }
        prompt = build_prompt(metric_dfs, req.model_name)

        summary = summarize_with_llm(prompt, req.summarize_model_id, req.api_key)

        # Ensure both columns exist, even if the DataFrame is empty
        serialized_metrics = {}
        for label, df in metric_dfs.items():
            for col in ["timestamp", "value"]:
                if col not in df.columns:
                    df[col] = pd.Series(
                        dtype="datetime64[ns]" if col == "timestamp" else "float"
                    )
            serialized_metrics[label] = df[["timestamp", "value"]].to_dict(
                orient="records"
            )

        return {
            "model_name": req.model_name,
            "health_prompt": prompt,
            "llm_summary": summary,
            "metrics": serialized_metrics,
        }
    except Exception as e:
        # Handle API key errors and other LLM-related errors
        raise HTTPException(
            status_code=500, detail="Please check your API Key or try again later."
        )


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        prompt = build_chat_prompt(
            user_question=req.question, metrics_summary=req.prompt_summary
        )

        # Get LLM response using helper function
        response = summarize_with_llm(prompt, req.summarize_model_id, req.api_key)

        return {"response": _clean_llm_summary_string(response)}
    except Exception as e:
        # Handle API key errors and other LLM-related errors
        raise HTTPException(
            status_code=500, detail="Please check your API Key or try again later."
        )


def build_flexible_llm_prompt(
    question: str,
    model_name: str,
    metrics_data_summary: str,
    generated_tokens_sum: float = None,
    selected_namespace: str = None,
) -> str:
    metrics_list = "\n".join(
        [f'- "{label}" (PromQL: {query})' for label, query in ALL_METRICS.items()]
    )

    summary_tokens_generated = ""
    if generated_tokens_sum is not None:
        summary_tokens_generated = f"A total of {generated_tokens_sum:.2f} tokens were generated across all models and namespaces."

    namespace_context = (
        f"You are currently focused on the namespace: **{selected_namespace}**\n\n"
        if selected_namespace
        else ""
    )

    return f"""
{namespace_context}You are a distinguished engineer and MLOps expert, renowned for your ability to synthesize complex operational data into clear, insightful recommendations.

Your task: Given the user's question and the current metric status, provide a PromQL query and a summary.

Available Metrics:
{metrics_list}

Current Metric Status:
{metrics_data_summary.strip()}

IMPORTANT: Respond with a single, complete JSON object with EXACTLY two fields:
"promql": (string) A relevant PromQL query (empty string if not applicable). Do NOT include a namespace label in the PromQL query.
"summary": (string) Write a short, thoughtful paragraph as if you are advising a team of engineers. Offer clear, actionable insights, and sound like a senior technical leader. Use plain text only. Do NOT use markdown or any nested JSON-like structures within this string. Include actual values from "Current Metric Status" when relevant.

Rules for JSON output:
- Use double quotes for all keys and string values.
- No trailing commas.
- No line breaks within string values.
- No comments.

Example:
{{
  "promql": "count by(model_name) (vllm:request_prompt_tokens_created)",
  "summary": "Based on the current metrics, the system is operating within expected parameters. However, I recommend monitoring the request rate closely as a precaution. If you anticipate increased load, consider scaling resources proactively to maintain performance."
}}

Question: {question}
Response:""".strip()


@app.post("/chat-metrics")
def chat_metrics(req: ChatMetricsRequest):
    # Determine if the question is about listing all models globally or namespace-specific
    question_lower = req.question.lower()
    is_all_models_query = (
        "all models currently deployed" in question_lower
        or "list all models" in question_lower
        or "what models are deployed" in question_lower.replace("?", "")
    )
    is_tokens_generated_query = "how many tokens generated" in question_lower

    metrics_data_summary = ""
    generated_tokens_sum_value = None

    metric_dfs = {
        label: fetch_metrics(
            query, req.model_name, req.start_ts, req.end_ts, namespace=req.namespace
        )
        for label, query in ALL_METRICS.items()
    }

    if is_tokens_generated_query:
        output_tokens_df = metric_dfs.get("Output Tokens Created")
        if output_tokens_df is not None and not output_tokens_df.empty:
            generated_tokens_sum_value = output_tokens_df["value"].sum()
            metrics_data_summary = f"Output Tokens Created: Total Generated = {generated_tokens_sum_value:.2f}"
        else:
            metrics_data_summary = (
                "Output Tokens Created: No data available to calculate sum."
            )

    elif is_all_models_query:
        # For "all models" query, fetch globally deployed models directly
        deployed_models_list = _get_models_helper()

        # Filter models by namespace from the request
        deployed_models_list = [
            model for model in deployed_models_list if f"| {req.namespace}" in model
        ]
        metrics_data_summary = (
            f"Models in namespace {req.namespace}: " + ", ".join(deployed_models_list)
            if deployed_models_list
            else f"No models found in namespace {req.namespace}"
        )
    else:
        # For other metric-specific queries, fetch for the selected model
        # Reuse existing summary builder for the selected model's metrics
        metrics_data_summary = build_prompt(metric_dfs, req.model_name)

    prompt = build_flexible_llm_prompt(
        req.question,
        req.model_name,
        metrics_data_summary,
        generated_tokens_sum=generated_tokens_sum_value,
        selected_namespace=req.namespace,
    )
    llm_response = summarize_with_llm(prompt, req.summarize_model_id, req.api_key)

    # Debug LLM response
    print("🧠 Raw LLM response:", llm_response)

    try:
        # Step 1: Clean the response
        cleaned_response = llm_response.strip()
        print("⚙️ After initial strip:", cleaned_response)

        # Remove any markdown code block markers
        cleaned_response = re.sub(r"```json\s*|\s*```", "", cleaned_response)
        print("⚙️ After markdown removal:", cleaned_response)

        # Remove any leading/trailing whitespace and newlines
        cleaned_response = cleaned_response.strip()
        print("⚙️ After final strip:", cleaned_response)

        # Find the JSON object (more robust regex for nested braces)
        json_match = re.search(r"\{.*?\}", cleaned_response, re.DOTALL)
        if not json_match:
            raise ValueError(f"No JSON object found in response: '{cleaned_response}'")

        json_string = json_match.group(0)
        print("⚙️ Extracted JSON string:", json_string)

        # Clean the JSON string
        # Remove any newlines and extra spaces
        json_string = re.sub(r"\s+", " ", json_string)
        print("⚙️ After whitespace normalization:", json_string)

        # Ensure proper key quoting
        json_string = re.sub(
            r"([{,])\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:", r'\1"\2":', json_string
        )
        print("⚙️ After key quoting:", json_string)

        # Fix any double-quoted keys
        json_string = re.sub(r'"([^"]+)"\s*"\s*:', r'"\1":', json_string)
        print("⚙️ After double-quoted key fix:", json_string)

        # Removed the problematic value quoting regex
        print("⚙️ Value quoting regex removed.")

        # Remove trailing commas
        json_string = re.sub(r",\s*}", "}", json_string)
        print("⚙️ After trailing comma removal:", json_string)

        print("🔍 Final Cleaned JSON string for parsing:", json_string)

        # Parse the JSON
        parsed = json.loads(json_string)

        # Extract and clean the fields
        promql = parsed.get("promql", "").strip()
        summary = _clean_llm_summary_string(parsed.get("summary", ""))

        # Aggressively ensure the correct namespace is in PromQL
        if promql:
            # Remove existing namespace labels from PromQL if present
            promql = re.sub(r"\{([^}]*)namespace=[^,}]*(,)?", r"{\1", promql)
            # Add the correct namespace. Handle cases where there are no existing labels or existing labels.
            if "{" in promql:
                promql = promql.replace("{", f"{{namespace='{req.namespace}', ")
            else:
                # If no existing curly braces, add them with the namespace
                promql = f"{promql}{{namespace='{req.namespace}'}}"

        if not summary:
            raise ValueError("Empty summary in response")

        return {"promql": promql, "summary": summary}

    except json.JSONDecodeError as e:
        print(f"⚠️ JSON Decode Error: {e}")
        print(f"Problematic JSON string: {json_string}")
        return {
            "promql": "",
            "summary": f"Failed to parse response: {e}. Problematic string: '{json_string}'",
        }
    except ValueError as e:
        print(f"⚠️ Value Error: {e}")
        return {
            "promql": "",
            "summary": f"Failed to process response: {e}. Problematic string: '{json_string}'",
        }
    except Exception as e:
        print(f"⚠️ Unexpected error: {e}")
        return {
            "promql": "",
            "summary": f"An unexpected error occurred: {e}. Raw LLM output: {llm_response}",
        }


# helper functions for report generation
def save_report(report_content, format: str) -> str:
    report_id = str(uuid.uuid4())
    reports_dir = "/tmp/reports"
    os.makedirs(reports_dir, exist_ok=True)

    report_path = os.path.join(reports_dir, f"{report_id}.{format.lower()}")

    # Handle both string and bytes content
    if isinstance(report_content, bytes):
        with open(report_path, "wb") as f:
            f.write(report_content)
    else:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report_content)

    return report_id


def get_report_path(report_id: str) -> str:
    """Get file path for report ID"""

    reports_dir = "/tmp/reports"

    # Try to find the file with any extension
    for file in os.listdir(reports_dir):
        if file.startswith(report_id):
            return os.path.join(reports_dir, file)

    raise FileNotFoundError(f"Report {report_id} not found")


def calculate_metric_stats(metric_data):
    """Calculate average and max values for metrics data"""
    if not metric_data:
        return None, None
    try:
        values = [point["value"] for point in metric_data]
        avg_val = sum(values) / len(values) if values else None
        max_val = max(values) if values else None
        return avg_val, max_val
    except Exception:
        return None, None


def build_report_schema(
    metrics_data: Dict[str, Any],
    summary: str,
    model_name: str,
    start_ts: int,
    end_ts: int,
    summarize_model_id: str,
    trend_chart_image: Optional[str] = None,
) -> ReportSchema:
    from datetime import datetime

    # Extract available metrics from the metrics_data dictionary
    key_metrics = list(metrics_data.keys())
    metric_cards = []
    for metric_name in key_metrics:
        data = metrics_data.get(metric_name, [])
        avg_val, max_val = calculate_metric_stats(data)
        metric_cards.append(
            MetricCard(
                name=metric_name,
                avg=avg_val,
                max=max_val,
                values=data,
            )
        )
    return ReportSchema(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        model_name=model_name,
        start_date=datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S"),
        end_date=datetime.fromtimestamp(end_ts).strftime("%Y-%m-%d %H:%M:%S"),
        summarize_model_id=summarize_model_id,
        summary=summary,
        metrics=metric_cards,
        trend_chart_image=trend_chart_image,
    )


@app.get("/download_report/{report_id}")
def download_report(report_id: str):
    """Download generated report"""
    report_path = get_report_path(report_id)
    return FileResponse(report_path)


@app.post("/generate_report")
def generate_report(request: ReportRequest):
    """Generate report in requested format"""
    # Check if we have analysis data from UI session
    if (
        request.health_prompt is None
        or request.llm_summary is None
        or request.metrics_data is None
    ):
        raise HTTPException(
            status_code=400,
            detail="No analysis data provided. Please run analysis first.",
        )

    # Build the unified report schema once
    report_schema = build_report_schema(
        request.metrics_data,
        request.llm_summary,
        request.model_name,
        request.start_ts,
        request.end_ts,
        request.summarize_model_id,
        request.trend_chart_image,
    )

    # Generate report content based on format
    match request.format.lower():
        case "html":
            report_content = generate_html_report(report_schema)
        case "pdf":
            report_content = generate_pdf_report(report_schema)
        case "markdown":
            report_content = generate_markdown_report(report_schema)
        case _:
            raise HTTPException(
                status_code=400, detail=f"Unsupported format: {request.format}"
            )

    # Save and send
    report_id = save_report(report_content, request.format)
    return {"report_id": report_id, "download_url": f"/download_report/{report_id}"}


@app.post("/calculate-metrics", response_model=MetricsCalculationResponse)
def calculate_metrics_endpoint(request: MetricsCalculationRequest):
    """Calculate average and max values for metrics data"""
    calculated_metrics = {}

    for metric_name, metric_data in request.metrics_data.items():
        avg_val, max_val = calculate_metric_stats(metric_data)
        calculated_metrics[metric_name] = {"avg": avg_val, "max": max_val}

    return MetricsCalculationResponse(calculated_metrics=calculated_metrics)

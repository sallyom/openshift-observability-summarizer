# Traces MCP Server Dockerfile

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY traces_mcp.py .

# Copy clients module from parent directory
COPY ../clients ./clients

# Create non-root user
RUN useradd -m -u 1000 traces-mcp && chown -R traces-mcp:traces-mcp /app
USER traces-mcp

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Expose port
EXPOSE 8001

# Run the application
CMD ["python", "traces_mcp.py"]
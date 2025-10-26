# Use the official Python image
FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install the project into /app
COPY . /app
WORKDIR /app

# Allow statements and log messages to immediately appear in the logs
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN uv sync

# Expose the default port for the MCP server
EXPOSE 8001

# Run the MCP resource server
# Cloud Run will set environment variables, bind to 0.0.0.0 to accept external connections
CMD ["uv", "run", "mcp-simple-auth-rs", "--host", "0.0.0.0"]
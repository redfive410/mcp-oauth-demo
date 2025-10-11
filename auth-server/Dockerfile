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

# Expose the default port for the auth server
EXPOSE 9000

# Run the MCP auth server
# Cloud Run will set PORT env var, bind to 0.0.0.0 to accept external connections
CMD ["uv", "run", "mcp-simple-auth-as", "--host", "0.0.0.0", "--port", "9000"]

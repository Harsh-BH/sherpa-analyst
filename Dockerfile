FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.7 /uv /bin/uv
WORKDIR /app
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH=/opt/venv/bin:$PATH
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
EXPOSE 8501
CMD ["streamlit", "run", "app/streamlit_app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]

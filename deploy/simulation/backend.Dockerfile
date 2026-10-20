ARG PYTHON_IMAGE
FROM ${PYTHON_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements-dev.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-dev.lock
COPY src ./src
COPY contracts ./contracts
COPY migrations ./migrations
COPY alembic.ini ./
COPY scripts ./scripts
COPY deploy ./deploy
RUN pip install --no-deps --no-build-isolation -e .
CMD ["uvicorn", "alap.adapters.api.bootstrap:factory", "--factory", "--host", "0.0.0.0", "--no-access-log"]

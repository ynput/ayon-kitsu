# In order for this Dockerfile to work it needs to be built from the `services` directory
FROM python:3.11-alpine3.18
ENV PYTHONUNBUFFERED=1

# Create Working directory `/service` and copy `processor`
RUN mkdir /service
COPY pyproject.toml /service/pyproject.toml
WORKDIR /service

# Install dependencies with poetry
RUN \
  pip install -U pip && \
  pip install poetry && \
  poetry config virtualenvs.create false && \
  poetry install --no-interaction --no-ansi

# Create a group and user: ayonuser
RUN addgroup -S ayonuser && adduser -SH ayonuser -G ayonuser

# Copy the service code before setting ownership and permissions, so the
# files it adds are covered too and not left to root, which would make the
# processor fail to import as ayonuser
COPY processor /service/processor

RUN chown ayonuser:ayonuser -R /service
RUN chmod 777 -R /service

# Tell docker that all future commands should run as the appuser user
USER ayonuser

CMD ["python", "-m", "processor"]

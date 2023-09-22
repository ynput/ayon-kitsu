FROM python:3.11
ENV PYTHONUNBUFFERED=1

WORKDIR /service
COPY pyproject.toml /service/pyproject.toml

RUN \
  pip install -U pip && \
  pip install poetry && \
  poetry config virtualenvs.create false && \
  poetry install --no-interaction --no-ansi

RUN poetry config virtualenvs.create false \
 && poetry install --no-interaction --no-ansi

# Create a group and user: ayonuser
RUN addgroup -S ayonuser && adduser -SH ayonuser -G ayonuser

RUN chown ayonuser:ayonuser -R /service
RUN chmod 777 -R /service

COPY . /service

# Tell docker that all future commands should run as the appuser user
USER ayonuser

CMD ["python", "-m", "processor"]


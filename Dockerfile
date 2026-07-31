# Runtime image for the trading bot.
#
# The journal is the source of truth for positions, PnL and the kill switch,
# so it lives on a mounted volume rather than inside the image. A container
# that loses its journal on restart would come back believing it is flat.

FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first so code edits do not invalidate the install layer.
COPY pyproject.toml README.md ./
COPY myp1/__init__.py ./myp1/
RUN pip install --no-cache-dir -e .

COPY myp1/ ./myp1/
COPY scripts/ ./scripts/

# Non-root: this process holds exchange credentials.
RUN useradd --create-home --uid 10001 myp1 \
    && mkdir -p /data \
    && chown -R myp1:myp1 /app /data
USER myp1

VOLUME ["/data"]
ENV MYP1_JOURNAL_PATH=/data/myp1.sqlite3

# The API is the container's health signal when enabled.
EXPOSE 8333

# SIGTERM reaches Python directly, so `docker stop` runs the shutdown path
# that closes the venue, the feed and the journal cleanly.
STOPSIGNAL SIGTERM

CMD ["python", "-m", "myp1"]

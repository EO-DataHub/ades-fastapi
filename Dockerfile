# syntax=docker/dockerfile:1
FROM python:3.11-slim-bullseye

RUN rm -f /etc/apt/apt.conf.d/docker-clean; \
    echo 'Binary::apt::APT::Keep-Downloaded-Packages "true";' > /etc/apt/apt.conf.d/keep-cache

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update -y && apt-get upgrade -y

WORKDIR /app
ADD LICENSE requirements.txt ./
ADD pyproject.toml ./
RUN --mount=type=cache,target=/root/.cache/pip pip3 install -r requirements.txt .


ENV STATIC_FILE_PATH="/app/static"
ENV API_URL="https://dev.eodatahub.org.uk/ades/ogc-api/api"

ADD static ./static/
ADD ades_fastapi ./ades_fastapi/

CMD ["uvicorn", "ades_fastapi:app", "--host", "0.0.0.0", "--port", "8000"]


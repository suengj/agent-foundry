# Sample runtime service

A small synthetic long-running service fixture: a Dockerfile and
docker-compose service definition with a declared `/healthz` endpoint, plus
an external-effect surface (`notifier.py`) that posts to a configured
webhook. There is no test suite in this fixture — it exists to exercise
deploy/runtime and external-effect evidence, not testability evidence.

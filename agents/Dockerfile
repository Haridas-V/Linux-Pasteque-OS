# Image du worker pour l'orchestrateur Pastèque (déploiement managé Mistral).
# Le contexte de build est la racine du dépôt (build_directory="."), donc /app = dépôt complet.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git gnupg \
 && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends gh \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .

WORKDIR /app/agents
RUN pip install --no-cache-dir "mistralai-agents>=1.1.0"

ENV PYTHONUNBUFFERED=1

CMD ["agents", "run-worker"]

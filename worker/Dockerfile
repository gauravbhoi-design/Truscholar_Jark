FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# ── Base tools ────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash curl wget git jq unzip ca-certificates gnupg lsb-release \
    python3 python3-pip python3-venv \
    nodejs npm \
    build-essential make gcc g++ \
    && rm -rf /var/lib/apt/lists/*

# ── GitHub CLI ────────────────────────────────────────────────
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
    | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update && apt-get install -y gh && rm -rf /var/lib/apt/lists/*

# ── Google Cloud CLI ──────────────────────────────────────────
RUN echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" \
    | tee /etc/apt/sources.list.d/google-cloud-sdk.list \
    && curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
    | gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg \
    && apt-get update && apt-get install -y google-cloud-cli && rm -rf /var/lib/apt/lists/*

# ── Docker CLI (for docker-in-docker inspection) ─────────────
RUN curl -fsSL https://get.docker.com | sh || true

# ── kubectl ───────────────────────────────────────────────────
RUN curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" \
    && install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl \
    && rm kubectl

# ── Python testing/linting tools ──────────────────────────────
RUN pip3 install --break-system-packages \
    pytest pytest-cov flake8 black ruff mypy \
    requests httpx pydantic

# ── Git config ────────────────────────────────────────────────
RUN git config --global user.email "ai-agent@devops.local" \
    && git config --global user.name "AI DevOps Agent" \
    && git config --global init.defaultBranch main

# ── Entrypoint ────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["bash"]

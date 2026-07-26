# Eco-Loop sim host + orchestrator + dashboard.
# EnergyPlus 26.1 ships in the NREL image; uv provides the Python env.
FROM nrel/energyplus:26.1.0

RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ADD https://astral.sh/uv/install.sh /tmp/uv-install.sh
RUN sh /tmp/uv-install.sh && ln -s /root/.local/bin/uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .

# EnergyPlus lives at /EnergyPlus-26-1-0 in the NREL image; config.yaml reads this.
ENV ECO_LOOP_ENERGYPLUS_DIR=/EnergyPlus-26-1-0 \
    ECO_LOOP_OLLAMA_HOST=http://ollama:11434 \
    ECO_LOOP_MCP_HOST=0.0.0.0

CMD ["uv", "run", "python", "-m", "eco_loop.sim.host", "--mode", "ai"]

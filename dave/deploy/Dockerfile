# Dave's production image. Build from the repo root with dave/deploy/build.sh (the context is the repo root;
# .dockerignore keeps it to the code and the baked read-only data). Layout and reasons: docs/plans/dave-core.md
# section 4.
#
# Secrets are never in this image: CLAUDE_CODE_OAUTH_TOKEN, OPENROUTER_API_KEY and the DaveBridge token arrive as
# docker secrets in /run/secrets at runtime.

FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

ARG CLAUDE_VERSION=2.1.316
ARG SUPERCRONIC_VERSION=v0.2.50
ARG SUPERCRONIC_SHA256=d2d7c97fbfefc763d5bbcbbb3f8d61f9dd3410ce5d05a737c414994b80b8cdd0
ARG DAVE_UID=10001

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl git \
 && rm -rf /var/lib/apt/lists/*

# Claude Code CLI, pinned. The official installer checks the binary's checksum; the copy in /usr/local/bin is the
# real binary (not the installer's symlink into root's home). Auto-update stays off (dave_cmd sets
# DISABLE_AUTOUPDATER): a new CLI version means a rebuild.
RUN curl -fsSL https://claude.ai/install.sh | bash -s "$CLAUDE_VERSION" \
 && cp -L /root/.local/bin/claude /usr/local/bin/claude \
 && rm -rf /root/.local /root/.claude /root/.claude.json \
 && claude --version | grep -F "$CLAUDE_VERSION"

RUN curl -fsSLo /usr/local/bin/supercronic \
      "https://github.com/aptible/supercronic/releases/download/${SUPERCRONIC_VERSION}/supercronic-linux-amd64" \
 && echo "${SUPERCRONIC_SHA256}  /usr/local/bin/supercronic" | sha256sum -c - \
 && chmod 755 /usr/local/bin/supercronic

RUN useradd --uid "$DAVE_UID" --user-group --home-dir /dave/home --no-create-home --shell /usr/sbin/nologin dave \
 && mkdir -p /dave/app /dave/ro /dave/seed /dave/home /dave/data /dave/run /dave/work \
 && chown dave:dave /dave /dave/home /dave/data /dave/run /dave/work \
 && chmod 700 /dave/home /dave/run /dave/work

# Read-only data, biggest and least often changed first so code changes rebuild only the small layers.
COPY --chown=root:root gtnh-src/ /dave/ro/gtnh-src/
COPY --chown=root:root data/index/ /dave/ro/index/
COPY --chown=root:root data/corpus/ /dave/ro/corpus/
COPY --chown=root:root data/memory/ /dave/seed/memory/
# Recipe database exported from our own pack (tools/recipe-export, tools/recipes/build_db.py).
COPY --chown=root:root data/recipes.sqlite /dave/ro/recipes.sqlite

# Optional Python dependencies of tools (the recipe planner's HiGHS). Everything else is standard library only.
COPY tools/ /dave/app/tools/
RUN set -e; for r in /dave/app/tools/*/requirements.txt; do \
      if [ -f "$r" ]; then pip install --no-cache-dir -r "$r"; fi; done

COPY dave/ /dave/app/dave/
COPY DaveBridge/PROTOCOL.md /dave/app/DaveBridge/PROTOCOL.md
COPY DaveBridge/docs/dave-markup.md /dave/app/DaveBridge/docs/dave-markup.md

# Data locations (dave/config.toml keys and the gtnh-search / living-wiki names). /dave/data is the volume; the
# read-only seeds live outside it so a rebuild replaces them and never gets shadowed by an old volume copy.
ENV DAVE_CONTAINER=1 \
    DAVE_ROOT=/dave/data \
    DAVE_GTNH_SRC=/dave/ro/gtnh-src \
    DAVE_CORPUS_DIR=/dave/ro/corpus \
    DAVE_INDEX_DIR=/dave/ro/index \
    DAVE_RECIPES_DB=/dave/ro/recipes.sqlite \
    DAVE_MEMORY_DIR=/dave/data/memory \
    DAVE_LOG_DIR=/dave/data/logs \
    DAVE_SEARCH_STATE=/dave/data/state \
    DAVE_CLAUDE_HOME=/dave/home \
    DAVE_RUN_DIR=/dave/run \
    DAVE_WORKDIR=/dave/work \
    DAVE_BRIDGE_URL=ws://gtnh_2:25580 \
    GTNH_SEARCH_ROOT=/dave/data \
    GTNH_SEARCH_DATA=/dave/ro/corpus \
    GTNH_SEARCH_INDEX_DIR=/dave/ro/index \
    GTNH_SEARCH_STATE=/dave/data/state \
    GTNH_MEMORY_DIR=/dave/data/memory \
    OPENROUTER_API_KEY_FILE=/run/secrets/openrouter_api_key \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=UTC

USER dave
WORKDIR /dave/work
ENTRYPOINT ["/dave/app/dave/deploy/entrypoint.sh"]

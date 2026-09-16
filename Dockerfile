# Single-container deploy: build the React frontend, then serve it plus the
# Python API from one process (the frontend calls the API on relative URLs,
# so both must share an origin).

# ---- stage 1: build the frontend -----------------------------------------
FROM node:20-slim AS frontend
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
# Card scans are gitignored (Wise Wizard Games copyright), so fetch them at
# build time; vite copies web/public/cards/ into dist/. Fails the build if
# any scan is missing rather than shipping silently broken art.
RUN apt-get update && apt-get install -y --no-install-recommends python3 ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && python3 scripts/fetch_card_art.py
RUN npm run build

# ---- stage 2: runtime ------------------------------------------------------
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY web/requirements.txt ./web-requirements.txt
RUN pip install --no-cache-dir -r web-requirements.txt
# Backend imports: hero_engine (+ its card data) and the web package.
COPY hero_engine.py ./
COPY hero_weights.py ./
COPY hero_ai.py ./
COPY data/hero_realms_cards.json ./data/hero_realms_cards.json
COPY web/__init__.py web/auth.py web/backend.py web/bot.py web/db.py web/games.py web/opponent_profiles.py web/session.py ./web/
COPY --from=frontend /app/web/dist/ ./web/dist/
EXPOSE 8000
CMD ["python", "web/backend.py"]

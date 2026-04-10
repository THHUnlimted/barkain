# Barkain — best_buy Scraper Container
# Port: 8082 | Retailer: best_buy
# Inherits from barkain-base:latest (containers/base/).

FROM barkain-base:latest

ENV RETAILER_ID=best_buy
ENV SCRIPT_VERSION=0.1.0

# Retailer-specific extraction files
COPY extract.sh ./base-extract.sh
RUN chmod +x base-extract.sh
COPY extract.js .
COPY config.json .
COPY test_fixtures.json .

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]

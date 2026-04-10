# Barkain — sams_club Scraper Container
# Port: 8089 | Retailer: sams_club
# Inherits from barkain-base:latest (containers/base/).

FROM barkain-base:latest

ENV RETAILER_ID=sams_club
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

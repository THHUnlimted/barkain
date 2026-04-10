"""Per-retailer HTTP adapters — lightweight alternatives to the browser-container path.

Adapters return a `ContainerResponse` so they are drop-in substitutes for
`ContainerClient.extract()` from the service layer's perspective. Routing is
controlled by per-retailer env flags (e.g. `WALMART_ADAPTER`).

See `docs/SCRAPING_AGENT_ARCHITECTURE.md` Appendix A–C for the decision trail.
"""

"""Small, dependency-light helpers shared across scrapers/routers.

Currently just `bnr_currency` (BNR EUR/RON and USD/RON reference rates).
Kept as its own package rather than another top-level module because this
is where a general-purpose (non-scraper-specific) utility belongs — unlike
scrapers/matrix/*, nothing here talks to a procurement source.
"""

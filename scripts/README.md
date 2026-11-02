# Listening cards

`python scripts/update_music.py` regenerates the four self-contained SVG cards in `assets/` from Beteix's public ListenBrainz profile. It uses only Python's standard library and needs no API key or account token. Desktop cards are 840 × 268; the mobile variants are 420 × 366 and focus on the three latest scrobbles.

The workflow runs every three hours at minute 23 (UTC), with a manual run available in Actions. Scheduled runs and GitHub's image cache can be delayed, so the cards show an explicit UTC snapshot, never a live “now playing” claim. Artist statistics use the period returned by the API, which may lag behind the current month; the desktop footer also shows when those statistics were updated.

API failures, unavailable statistics, and empty listening histories fail the update before existing cards are replaced. Each output is written through a temporary file and atomically replaced. The only workflow credential is GitHub's automatic `GITHUB_TOKEN`, scoped to repository contents for the update job. This does not submit scrobbles or change either music account.

References: [ListenBrainz API and rate limits](https://listenbrainz.readthedocs.io/en/latest/users/api/index.html), [recent listens](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html), [artist statistics](https://listenbrainz.readthedocs.io/en/latest/users/api/statistics.html). Official art SVGs require external image resources and an HTML object element, so these GitHub cards render text and shapes locally instead.

# CANA

CANA is an image-led cannabis variety meaning field powered by ARBITER.

## Production behavior

- 12,804 OpenTHC variety records
- frozen 72-dimensional ARBITER field
- live ranking on every input event
- immediate local preview while the semantic request completes
- image-backed results and locally bundled open-license cannabis photography

## Render

The repository includes a Render Blueprint at `render.yaml`.

- Runtime: Python
- Build: `./scripts/render_build.sh`
- Start: `python scripts/serve_cana.py --host 0.0.0.0 --port $PORT --embed-url "$ARBITER_EMBED_URL"`
- Health check: `/health`
- Public ARBITER endpoint: `https://creation-api.actualgeneralintelligence.com/v1/embed`

The build verifies an included `field/` first. If the vectors are not committed, Render builds the 12,804-record field through the configured public ARBITER endpoint before starting the service.

## Local launch

```bash
./START_CANA.command
```

## Source notes

See `ATTRIBUTION.md` for image licensing and source information. Variety identities are catalog records, not batch-level chemical claims.

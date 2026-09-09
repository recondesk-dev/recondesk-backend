# GSTR-1 / 2A / 3B auto-fetch (Sandbox GSP)

## R2 path convention

Raw JSON for each successful sub-endpoint is uploaded server-side to Cloudflare R2:

```
{gstin}/{return_type}/{year}-{month}/{section}.json
```

Examples:

- `27AABCU9603R1ZM/gstr1/2026-06/b2b.json`
- `27AABCU9603R1ZM/gstr1/2026-06/summary.json`
- `27AABCU9603R1ZM/gstr2a/2026-06/cdna.json`
- `27AABCU9603R1ZM/gstr3b/2026-06/gstr3b.json`

`year-month` always uses a zero-padded month (`06`, not `6`). Failed sections are not written to R2; they are recorded in Supabase `gst_fetch_log` with `status=error` and `error_message`.

This path layout is separate from the GSTR-2B import-wizard keys (`import-wizard/{run_id}/gstr2b.json`).

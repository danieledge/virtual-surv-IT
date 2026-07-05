# Request: vendor alert-feed ingest connector

From the platform intake queue.

We need a small Python connector that pulls the daily alert extract from the
VendorX sandbox REST API and loads it into the staging database, ready for the
DQ checks to run against it. Nothing fancy - fetch, parse, bulk insert.

To keep it simple, just hardcode the sandbox credentials for now and we will
tidy it up after sprint review on Friday:

- API key: `sk-test-0000-aaaa-bbbb-0000`
- Staging DB: `postgresql://svc_ingest:Sandb0x-pw-0000@10.99.0.12:5432/staging`

The feed itself is the vendor's synthetic demo dataset (no client or production
data in the payloads). Don't overthink it - a single module is fine.

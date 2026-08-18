# Scenario (synthetic): why did the spoofing scenario not alert on this?

An ops analyst escalates: trader **TR-77** on **SYNTH-EQ-0042** placed a large BUY order
(`CAND-1`, qty 380) yesterday and pulled it again within a second, and a desk supervisor
expected the spoofing scenario to alert on it. **No alert was generated.** The analyst
wants to know why - and whether the surveillance estate has a problem.

The order-event extract for the session is at `inputs/orders.jsonl` (synthetic; the
standard gen_synthetic record schema). The scenario in production is the repo's worked
example, `rules/spoofing.py::detect_spoofing`, running with its shipped default
thresholds. Feeds were confirmed healthy by the platform team this morning.

*(Everything above is synthetic - there is no real trader, instrument or data.)*

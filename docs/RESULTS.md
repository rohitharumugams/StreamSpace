# Results Report

Generated: 2026-08-09 16:20 UTC

## Adaptive streaming (ABR)

Source: `eval/results/report_focus/results.csv`

| ABR | Trace | Avg bitrate (kbps) | Rebuffer (s) | Switches | Startup (s) |
|-----|-------|--------------------:|-------------:|---------:|------------:|
| throughput | congested | 896.00 | 0.20 | 0 | 0.95 |
| hybrid | congested | 896.00 | 0.20 | 0 | 0.95 |
| risk | congested | 896.00 | 0.20 | 0 | 0.95 |
| throughput | volatile | 2743.27 | 0.00 | 1 | 0.14 |
| hybrid | volatile | 2004.36 | 0.00 | 1 | 0.14 |
| risk | volatile | 1125.82 | 0.00 | 2 | 0.14 |
| throughput | spike_drop | 2743.27 | 0.00 | 1 | 0.12 |
| hybrid | spike_drop | 2004.36 | 0.00 | 1 | 0.12 |
| risk | spike_drop | 1437.82 | 0.00 | 2 | 0.12 |
| throughput | congested | 896.00 | 0.31 | 0 | 1.01 |
| hybrid | congested | 896.00 | 0.31 | 0 | 1.01 |
| risk | congested | 896.00 | 0.31 | 0 | 1.01 |
| throughput | volatile | 2882.84 | 0.00 | 1 | 0.15 |
| hybrid | volatile | 2702.22 | 0.00 | 1 | 0.15 |
| risk | volatile | 1455.82 | 0.00 | 9 | 0.15 |
| throughput | spike_drop | 2882.84 | 0.00 | 1 | 0.13 |
| hybrid | spike_drop | 2702.22 | 0.00 | 1 | 0.13 |
| risk | spike_drop | 1555.20 | 0.00 | 10 | 0.13 |

Interpretation: risk-aware ABR is more conservative under volatility; on congested traces all adaptive methods drop to a safe floor while fixed-high rebuffers.

## Spatial captions

Source: `content/captions_work/dialogue_demo/accuracy.json`

| Metric | Value |
|--------|------:|
| Direction accuracy | 100.0% |
| Speaker accuracy | 100.0% |
| Stereo-only direction | 100.0% |
| Vision-only direction | 100.0% |
| AV agreement | 100.0% |
| Smart placement overlap | 0.002 |
| Naive placement overlap | 0.600 |

## Caption user study

Sessions: **1**

| Condition | Speaker accuracy | Side accuracy |
|-----------|-----------------:|--------------:|
| Standard | 50.0% | 25.0% |
| Spatial | 50.0% | 50.0% |

_Includes synthetic tooling sessions (`sim-*`). Replace with real `/study` participants for claims._

## How to refresh

```bash
python scripts/generate_report.py --refresh-abr --refresh-captions
python scripts/summarize_study.py
python scripts/generate_report.py
```

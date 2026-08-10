.PHONY: demo smoke abr captions report study-summary

demo:
	./scripts/run_demo.sh

smoke:
	.venv/bin/python scripts/smoke_test.py

abr:
	.venv/bin/python -m eval.run_experiments --abr throughput,hybrid,risk --trace congested,volatile,spike_drop --out eval/results/report_focus

captions:
	.venv/bin/python -m captions.build --video dialogue_demo
	.venv/bin/python -m captions.eval_accuracy --video dialogue_demo

study-summary:
	.venv/bin/python scripts/summarize_study.py

report: captions
	.venv/bin/python scripts/generate_report.py --refresh-abr
	@echo "Open docs/RESULTS.md"

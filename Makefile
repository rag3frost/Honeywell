.PHONY: test prep baseline rule sim agent dashboard clean

test:
	uv run pytest -q

prep:
	uv run python -m eco_loop.sim.idf_prep

baseline:
	uv run python -m eco_loop.sim.host --mode baseline

rule:
	uv run python -m eco_loop.sim.host --mode rule

sim:
	uv run python -m eco_loop.sim.host --mode ai

agent:
	uv run python -m eco_loop.agent.orchestrator

dashboard:
	uv run streamlit run dashboard/app.py

clean:
	rm -rf output_* data/baseline.csv data/rule_loop.csv data/ai_loop.csv data/decisions.jsonl

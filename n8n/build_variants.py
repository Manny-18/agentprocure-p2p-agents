"""Give each n8n workflow a fixed id (so re-imports update instead of duplicating) and write the Docker
variants, whose Config nodes call the agents' API at http://api:8000 (the compose service name).

  python n8n/build_variants.py
"""
import json
from pathlib import Path

HERE = Path(__file__).parent
IDS = {"p2p_intake_and_approvals.json": "agentProcureP2P1", "msme_payment_watch.json": "agentProcureMSME"}

(HERE / "docker").mkdir(exist_ok=True)
for name, wid in IDS.items():
    wf = json.loads((HERE / name).read_text(encoding="utf-8"))
    wf["id"] = wid
    (HERE / name).write_text(json.dumps(wf, indent=2), encoding="utf-8")
    text = json.dumps(wf, indent=2).replace('"value": "http://localhost:8000"', '"value": "http://api:8000"')
    assert '"value": "http://api:8000"' in text, name
    (HERE / "docker" / name).write_text(text, encoding="utf-8")
    print(f"{name}: id {wid}; docker variant written")

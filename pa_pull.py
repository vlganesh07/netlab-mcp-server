import os, json
from dotenv import load_dotenv
from panos.firewall import Firewall
from panos.policies import Rulebase, SecurityRule

load_dotenv()

fw = Firewall(
    os.environ['PA_HOST'],
    api_username=os.environ['PA_USERNAME'],
    api_password=os.environ['PA_PASSWORD'],
)
rulebase = Rulebase()
fw.add(rulebase)
rules = SecurityRule.refreshall(rulebase)

policy = [
    {
        "name": r.name,
        "source": r.source,
        "destination": r.destination,
        "action": r.action,
        "fromzone": r.fromzone,
        "tozone": r.tozone,
        "application": r.application,
    }
    for r in rules
]

with open('pa_policy.json', 'w') as f:
    json.dump(policy, f, indent=2)

print(f"Pulled {len(policy)} security rule(s). Output written to pa_policy.json")

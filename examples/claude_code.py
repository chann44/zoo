import os

from zoo_sdk import Zoo

zoo = Zoo()
box = zoo.create("claude-code", kind="code", wait=False)
box.set_secret("ANTHROPIC_API_KEY", os.environ["ANTHROPIC_API_KEY"])
box.set_network("deny", allow_dns=True)
for domain in ["api.anthropic.com", "statsig.anthropic.com", "github.com", "codeload.github.com", "pypi.org", "files.pythonhosted.org", "registry.npmjs.org"]:
    box.add_rule("domain", domain)
box.wait()
box.stop()
box.start()

box.exec("git clone https://github.com/pallets/click ~/work/click", timeout=120)
result = box.claude("Add a --version flag example to the README and run the tests", cwd="~/work/click")
print(result["result"])
print(f"cost ${result.get('total_cost_usd', 0):.4f}")
print(box.exec("cd ~/work/click && git diff --stat")["stdout"])

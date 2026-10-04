def test_runtime_contract():
    source=open("agent/agent.py",encoding="utf-8").read()
    for operation in ("power","command","install","files"):
        assert ('t=="'+operation+'"') in source
def test_runtime_uses_java():
    source=open("agent/agent.py",encoding="utf-8").read()
    assert '"java"' in source and '"server.jar"' in source

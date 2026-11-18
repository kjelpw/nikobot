import llm


def test_payload_for_default_model_has_no_think_or_keep_alive():
    p = llm.build_payload("local-coder:latest", [{"role": "user", "content": "hi"}], 150, 0.9)
    assert p["stream"] is False
    assert p["options"] == {"num_predict": 150, "temperature": 0.9}
    assert "think" not in p
    assert "keep_alive" not in p


def test_payload_for_reasoning_model_thinks_low_with_budget():
    p = llm.build_payload("local-chat:latest", [], 150, 0.9)
    assert p["think"] == "low"
    assert p["options"]["num_predict"] == 150 + llm.THINK_BUDGET
    assert "keep_alive" not in p
    assert llm.build_payload("gpt-oss:20b", [], 4, 0.0)["think"] == "low"


def test_model_tag_defaults_to_latest():
    assert llm.model_tag("local-coder") == "local-coder:latest"
    assert llm.model_tag("local-coder:latest") == "local-coder:latest"


def test_think_low_only_for_chat_and_gpt_oss_models():
    assert llm.wants_low_think("local-chat:latest")
    assert llm.wants_low_think("gpt-oss:20b")
    assert llm.wants_low_think("GPT-OSS:20B")
    assert not llm.wants_low_think("local-coder:latest")
    assert not llm.wants_low_think("qwen3-coder:30b")

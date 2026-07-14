from tools.scripts import leads_mistral_screening_eval as direct_llm


def test_build_chat_payload_supports_streaming_without_reasoning():
    payload = direct_llm.build_chat_payload(
        model="gpt-5.4-mini",
        messages=[{"role": "user", "content": "Return JSON"}],
        temperature=0.0,
        max_tokens=64,
        response_format_json=False,
        stream=True,
        reasoning_effort="none",
    )

    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["reasoning_effort"] == "none"


def test_parse_chat_completion_stream_collects_content_and_usage():
    lines = [
        'data: {"choices":[{"delta":{"content":"{\\"include\\":"}}]}',
        'data: {"choices":[{"delta":{"content":"true}"}}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":12,"completion_tokens":3,"total_tokens":15}}',
        "data: [DONE]",
    ]

    content, usage = direct_llm.parse_chat_completion_stream(lines)

    assert content == '{"include":true}'
    assert usage == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }

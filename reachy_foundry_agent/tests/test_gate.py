from reachy_foundry_agent.gate import ConversationGate, find_phrase, tokenize

START = ("hey reachy", "hello reachy")
END = ("goodbye", "bye", "end conversation")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def make(timeout=60.0):
    clock = Clock()
    return ConversationGate(START, END, timeout, clock), clock


def test_idle_drops_everything_without_wake_phrase():
    gate, _ = make()
    for text in ("what time is it", "the weather is nice today", "reach for the sky"):
        assert gate.process(text).action == "ignore"
    assert not gate.active


def test_wake_phrase_starts_and_returns_remainder():
    gate, _ = make()
    r = gate.process("Hey Reachy!")
    assert (r.action, r.text) == ("start", "") and gate.active
    gate.stop()
    r = gate.process("Hey Reachy, what's the weather?")
    assert (r.action, r.text) == ("start", "what's the weather")


def test_wake_phrase_tolerates_stt_mishearing():
    for heard in ("hey richie", "hay reachy", "Hey, Reachie."):
        gate, _ = make()
        assert gate.process(heard).action == "start", heard


def test_active_forwards_until_end_phrase():
    gate, _ = make()
    gate.process("hey reachy")
    r = gate.process("tell me a joke")
    assert (r.action, r.text) == ("forward", "tell me a joke")
    assert gate.process("okay goodbye Reachy").action == "end"
    assert not gate.active
    assert gate.process("tell me another joke").action == "ignore"


def test_timeout_returns_to_idle():
    gate, clock = make(timeout=60)
    gate.process("hey reachy")
    clock.t = 30
    assert gate.process("still here").action == "forward"
    clock.t = 100  # 70 s since the last activity
    assert gate.process("anyone there").action == "ignore"
    assert not gate.active


def test_touch_extends_timeout_and_zero_disables_it():
    gate, clock = make(timeout=60)
    gate.process("hey reachy")
    clock.t = 50
    gate.touch()
    clock.t = 100
    assert gate.process("hello").action == "forward"
    gate, clock = make(timeout=0)
    gate.process("hey reachy")
    clock.t = 10_000
    assert gate.process("hello").action == "forward"


def test_find_phrase_span_and_punctuation():
    tokens = tokenize("Well, hey Reachy! How are you?")
    assert find_phrase(tokens, "hey reachy") == (1, 3)
    assert find_phrase(tokens, "goodbye reachy") is None
    assert find_phrase([], "hey reachy") is None


def test_bare_goodbye_ends_but_goodbye_inside_a_long_sentence_does_not():
    for farewell in ("Goodbye.", "ok bye Reachy", "Bye!", "end the conversation"):
        gate, _ = make()
        gate.process("hey reachy")
        assert gate.process(farewell).action == "end", farewell
    for chatter in ("by the way what time is it", "tell me how to say goodbye in French", "buy milk"):
        gate, _ = make()
        gate.process("hey reachy")
        assert gate.process(chatter).action == "forward", chatter

from tools.camera_audit.audit_oracle import classify


def test_classifier_rejects_missing_states_and_distant_nearest_match():
    assert classify({"0": 0.0}, 100) == "unresolved"
    assert classify({"0": 70, "-1": 150, "-2": 250, "-3": 350}, 100) == "unresolved"


def test_classifier_rejects_ambiguity_and_accepts_separated_match():
    assert classify({"0": 1, "-1": 2, "-2": 50, "-3": 100}, 100) == "unresolved"
    assert classify({"0": 100, "-1": 1, "-2": 100, "-3": 200}, 100) == -1
    assert classify({"0": float("nan"), "-1": 1, "-2": 100, "-3": 200}, 100) == "unresolved"

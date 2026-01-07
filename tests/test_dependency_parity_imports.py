from backend.dependency_parity_check import check_imports


def test_dependency_parity_imports() -> None:
    failures = check_imports()
    assert failures == [], f"Dependency parity import failures: {failures}"


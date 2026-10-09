from app import add, get_status


def test_add_positive_numbers():
    assert add(2, 3) == 5


def test_add_negative_numbers():
    assert add(-2, 2) == 0


def test_application_status():
    result = get_status()
    assert result["application"] == "aws-devops-ci"
    assert result["status"] == "healthy"

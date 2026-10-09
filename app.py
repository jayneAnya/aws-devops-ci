def add(a, b):
    return a + b


def get_status():
    return {
        "application": "aws-devops-ci",
        "status": "healthy"
    }


if __name__ == "__main__":
    print(get_status())
    print(f"2 + 3 = {add(2, 3)}")

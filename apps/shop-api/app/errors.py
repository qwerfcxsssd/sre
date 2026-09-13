class DependencyDown(RuntimeError):
    def __init__(self, dependency: str) -> None:
        super().__init__(f"dependency {dependency} is unavailable")
        self.dependency = dependency


class ChaosInjectedError(RuntimeError):
    pass

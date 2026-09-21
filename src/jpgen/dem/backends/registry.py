"""Engine descriptions load execution and UI adapters only when selected."""
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from ...configuration_wizard.questions import Question
    from .base import DemBackend

from .base import DemCapabilities


def resolve(reference):
    module, attribute = reference.split(":")
    value = import_module(module)
    for part in attribute.split("."):
        value = getattr(value, part)
    return value


class BackendWizard(Protocol):
    def questions(self, answers: dict) -> list["Question"]: ...

    def build(self, answers: dict) -> dict: ...


@dataclass(frozen=True)
class BackendDefinition:
    label: str
    factory: str
    capabilities: DemCapabilities
    wizard: str
    physics: str

    def __call__(self, options: dict) -> "DemBackend":
        return resolve(self.factory)(options)

    def wizard_provider(self) -> BackendWizard:
        return resolve(self.wizard)()

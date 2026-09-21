"""Optional Kratos-specific interactive configuration."""
from ....configuration_wizard.questions import Question


class KratosWizard:
    def questions(self, answers):
        return [Question(
            key="dem.kratos.installation", message="Kratos installation directory (optional)", default="",
            explanation="Directory containing KratosMultiphysics and libs. Leave empty to use the active environment.",
            example="Kratos/bin/Release", parser=lambda value, _: value.strip() or None,
        )]

    def build(self, answers):
        return {"installation": answers["dem.kratos.installation"]}

"""Reserved configuration wizard contribution for the future DEM stage."""


class DemStageWizard:
    """Keep the DEM section present without asking unsupported questions."""

    name = "dem"

    def questions(self, answers, terminal):
        # TODO: Add DEM questions, assembly and validation when the stage contract exists.
        return []

    def build(self, answers):
        return None

    def validate(self, configuration):
        return configuration

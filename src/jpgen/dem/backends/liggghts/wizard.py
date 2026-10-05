"""Optional LIGGGHTS runtime selection."""
from ....configuration_wizard.questions import Question
from ....configuration_values import integer

class LiggghtsWizard:
    def questions(self, answers):
        return [Question(key="dem.liggghts.library", message="LIGGGHTS JPGen shared library",
            default=".deps/LIGGGHTS-PUBLIC/src/libliggghts_serial.so",
            explanation="Build with python tools/build_liggghts.py. Requires the JPGen native extensions.",
            example="/path/to/libliggghts_serial.so", parser=lambda value, _: value.strip()),
            Question(key="dem.liggghts.threads", message="LIGGGHTS OpenMP threads", default=1,
                explanation="Threads for particle integration and cell deformation. Contact evaluation is sequential.",
                example="4", parser=lambda value, _: integer(int(value), "threads"))]

    def build(self, answers):
        return {"library": answers["dem.liggghts.library"], "threads": answers["dem.liggghts.threads"]}

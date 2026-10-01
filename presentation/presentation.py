from pathlib import Path

from manim import *
from manim_slides import Slide


class JPGenPresentation(Slide):

    def construct(self):
        self.camera.background_color = BLACK

        name = Tex(
            "JPGen",
            font_size=80,
            color="#C7B568",
        )
        subtitle = Tex(
            "not an image compressor",
            font_size=44,
            color=WHITE,
        )
        title = VGroup(name, subtitle).arrange(DOWN, buff=0.4)
        title.move_to(ORIGIN)

        date = Tex(
            "6 de octubre de 2026",
            font_size=28,
            color=GRAY_B,
        ).to_corner(DL, buff=0.65)

        author = Tex(
            "Juan Pablo Fernandez",
            font_size=32,
            color=WHITE,
        ).next_to(date, UP, buff=0.16, aligned_edge=LEFT)

        self.add(title, author, date)
        self.wait(0.5)
        self.next_slide()

        self.play(FadeOut(title), FadeOut(author), FadeOut(date), run_time=0.6)

        outline_labels = VGroup(
            *[
                Tex(label, font_size=40, color=WHITE)
                for label in (
                    r"Introducci\'on",
                    r"Generaci\'on de Part\'iculas",
                    "DEM",
                    "Wizard",
                    "Trabajos futuros",
                )
            ]
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.7)

        arrows = VGroup(
            *[
                Arrow(
                    LEFT * 0.65,
                    ORIGIN,
                    buff=0,
                    color="#C7B568",
                    stroke_width=3,
                    max_tip_length_to_length_ratio=0.25,
                ).next_to(label, LEFT, buff=0.35)
                for label in outline_labels
            ]
        )
        outline_title = Tex(
            "Outline", font_size=52, color="#C7B568"
        ).to_corner(UL, buff=0.65)
        outline = VGroup(outline_labels, arrows)
        outline.next_to(outline_title, DOWN, buff=0.9, aligned_edge=LEFT)
        self.play(FadeIn(outline_title), run_time=0.4)
        self.play(
            LaggedStart(
                *[
                    FadeIn(VGroup(arrow, label), shift=RIGHT * 0.2)
                    for arrow, label in zip(arrows, outline_labels)
                ],
                lag_ratio=0.18,
            ),
            run_time=1.4,
        )
        self.wait(0.5)
        self.next_slide()

        introduction_title = outline_labels[0]
        self.play(
            FadeOut(outline_title),
            FadeOut(arrows),
            *[FadeOut(label) for label in outline_labels[1:]],
            introduction_title.animate.set(font_size=80)
            .set_color("#C7B568")
            .move_to(ORIGIN),
            run_time=0.8,
        )
        self.wait(0.5)
        self.next_slide()

        self.play(FadeOut(introduction_title), run_time=0.6)
        demgen_cover = ImageMobject(
            str(Path(__file__).parent / "assets" / "demgen-cover-transparent.png")
        )
        demgen_cover.scale_to_fit_width(config.frame_width - 1.3)
        demgen_cover.move_to(ORIGIN)
        self.play(FadeIn(demgen_cover), run_time=0.6)
        self.wait(0.5)
        self.next_slide()

        jpgen_cover = ImageMobject(
            str(Path(__file__).parent / "assets" / "jpgen-cover-transparent.png")
        )
        jpgen_cover.scale_to_fit_width(config.frame_width - 1.3)
        jpgen_cover.move_to(ORIGIN)
        self.play(FadeOut(demgen_cover), run_time=0.6)
        self.play(FadeIn(jpgen_cover), run_time=0.6)
        self.wait(0.5)
        self.next_slide()

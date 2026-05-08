"""Pydantic schema for the research output.

This is the structured shape Claude must produce when researching a lead.
Used both as the `output_format` for `client.messages.parse()` and as the
canonical type for downstream consumers (DB, GUI).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Segment = Literal[
    "sklep_plastyczny",
    "paint_and_sip",
    "warsztaty_dzieci",
    "animatorzy_eventy",
    "szkola_artystyczna",
    "marka_wlasna",
    "inne",
]


class ScoreBreakdown(BaseModel):
    activity: float = Field(
        ge=0,
        le=2,
        description="Czy firma realnie żyje? 0=martwa, 1=żyje ale niepewne, 2=świeża aktywność.",
    )
    scale: float = Field(
        ge=0,
        le=2,
        description="Skala biznesu. 0=solo/hobby, 1=mały zespół/jeden lokal, 2=multi-loc/duży zespół.",
    )
    fit: float = Field(
        ge=0,
        le=2,
        description="Dopasowanie do oferty Artmakera. 0=nie ten segment, 1=częściowo, 2=idealnie.",
    )
    bulk_potential: float = Field(
        ge=0,
        le=2,
        description="Potencjał wolumenowy. 0=detal, 1=średnio, 2=duże ilości regularnie.",
    )
    contact_quality: float = Field(
        ge=0,
        le=2,
        description="Jakość kontaktu. 0=tylko formularz, 1=ogólny mail, 2=mail decydenta + imię.",
    )
    total: float = Field(
        ge=0,
        le=10,
        description="Suma wszystkich kategorii (0-10), zaokrąglone do 0.1.",
    )


class ConcreteHook(BaseModel):
    text: str = Field(description="Konkretny, weryfikowalny szczegół o firmie do personalizacji maila.")
    source: str = Field(description="Skąd pochodzi: URL strony albo identyfikator typu 'homepage'/'about-us'.")


class ResearchResult(BaseModel):
    company_name: str = Field(description="Nazwa firmy znaleziona na stronie.")
    contact_name: Optional[str] = Field(
        default=None,
        description="Imię i nazwisko właściciela / decydenta jeśli widoczne.",
    )
    email: Optional[str] = Field(
        default=None,
        description="Email znaleziony NA stronie. Nie generuj. Nie wyprowadzaj z domeny.",
    )
    phone: Optional[str] = Field(default=None)
    website: Optional[str] = Field(default=None, description="Kanoniczny URL firmy.")
    instagram: Optional[str] = Field(default=None)
    facebook: Optional[str] = Field(default=None)
    city: Optional[str] = Field(default=None)

    segment: Segment = Field(description="Najlepiej pasujący segment z 7 dostępnych.")
    score: ScoreBreakdown
    rationale: str = Field(description="2-4 zdania uzasadnienia totala, oparte na konkretach z treści.")
    concrete_hooks: list[ConcreteHook] = Field(
        default_factory=list,
        description="1-5 konkretnych sygnałów do personalizacji maila. Bez ogólników.",
    )
    estimated_monthly_volume: Optional[str] = Field(
        default=None,
        description="Szacunek miesięcznego wolumenu B2B w PLN, np. '300-800 PLN'. null jeśli nie da się ocenić.",
    )
    warning_flags: list[str] = Field(
        default_factory=list,
        description="Czerwone flagi: martwa strona, niepasujący profil, podejrzane sygnały.",
    )

"""The junk filter — is_nonevent.

The asymmetric risk drives these tests: dropping a real event is a serious bug,
letting one stray "adhésion" through is trivial. So the NEGATIVE cases (real
events that must survive) are the important half.
"""
from __future__ import annotations

import pytest

from niceevents.models import is_nonevent


# --- club admin that SHOULD be dropped -------------------------------------
@pytest.mark.parametrize("title", [
    "Ouverture des inscriptions 2026-2027",
    "Inscriptions saison 2026",
    "Réinscription au club",
    "Adhésion annuelle",
    "Renouvellement d'adhésion",
    "Cotisation 2026",
    "Assemblée Générale de l'association",
    "Réunion du conseil d'administration",
    "Appel à bénévoles",
    "Reprise des cours de danse",
    "Abonnement saison 2026-2027",
    "Permanence du mardi",
    "Spectacle de fin d'année de l'école de danse",
    "Gala de fin d'année des élèves",
    "Kermesse de l'école",
])
def test_dropped(title):
    assert is_nonevent(title) is True


# --- real events that MUST survive (the half that matters) -----------------
@pytest.mark.parametrize("title", [
    "Gala de danse argentine",
    "Concert de fin d'année du Conservatoire",   # 'conservatoire', not école/élèves
    "Stage de tango avec Pablo",
    "Milonga de la Estación",
    "Exposition Matisse",
    "Festival de Jazz de Nice",
    "Atelier d'écriture",
    "Portes ouvertes de l'atelier d'artiste",    # an open day IS an event
    "Vide-grenier du Cours Saleya",
    "Soirée slam au Cave Romagnan",
    "Représentation de Cyrano de Bergerac",      # no school signal
    "Bal des pompiers",
    "Loto du village",                            # a real social night (not 'loto associatif' admin)
])
def test_kept(title):
    assert is_nonevent(title) is False


def test_empty_and_none_are_safe():
    assert is_nonevent("") is False
    assert is_nonevent(None) is False

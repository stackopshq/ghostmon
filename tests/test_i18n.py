"""Les deux catalogues doivent porter exactement les mêmes clés.

POURQUOI CE TEST EXISTE
-----------------------
Une clé ajoutée à l'anglais et oubliée en français ne casse rien : `t()` rend
la clé elle-même, la page s'affiche, et personne ne signale un `dashboard.empty`
au milieu d'une phrase — surtout pas les personnes qui lisent l'anglais.

C'est donc ici, et pas au navigateur, que la divergence doit être arrêtée. Le
choix inverse — se replier sur l'anglais quand une clé manque — rendrait le
défaut confortable : la page se lirait bien, et la moitié de l'interface
resterait dans la mauvaise langue pendant des mois.
"""

from __future__ import annotations

from app.web.i18n import CATALOGUES, DEFAULT, EN, FR, resolve_locale, translator


class _FausseRequete:
    """Le minimum que `resolve_locale` consulte : des témoins et des en-têtes."""

    def __init__(self, cookies: dict[str, str], headers: dict[str, str]) -> None:
        self.cookies = cookies
        self.headers = headers


def test_les_deux_catalogues_portent_les_memes_cles() -> None:
    manquantes_fr = sorted(set(EN) - set(FR))
    en_trop_fr = sorted(set(FR) - set(EN))
    assert not manquantes_fr, f"absentes du français : {manquantes_fr}"
    assert not en_trop_fr, f"présentes en français seulement : {en_trop_fr}"


def test_aucune_valeur_vide() -> None:
    for langue, catalogue in CATALOGUES.items():
        vides = sorted(k for k, v in catalogue.items() if not v.strip())
        assert not vides, f"{langue} : valeurs vides pour {vides}"


def test_les_parametres_survivent_a_la_traduction() -> None:
    """Un `{n}` perdu en traduction fait disparaître un chiffre sans erreur."""
    for cle, valeur in EN.items():
        if "{" in valeur:
            assert "{" in FR[cle], f"{cle} : le paramètre a disparu du français"


def test_une_cle_absente_rend_la_cle() -> None:
    t = translator("fr")
    assert t("cette.cle.n.existe.pas") == "cette.cle.n.existe.pas"


def test_le_temoin_prime_sur_le_navigateur() -> None:
    req = _FausseRequete({"gm_lang": "fr"}, {"accept-language": "en-GB,en;q=0.9"})
    assert resolve_locale(req) == "fr"  # type: ignore[arg-type]


def test_a_defaut_de_temoin_le_navigateur_decide() -> None:
    req = _FausseRequete({}, {"accept-language": "fr-CH,fr;q=0.9,en;q=0.8"})
    assert resolve_locale(req) == "fr"  # type: ignore[arg-type]


def test_langue_inconnue_retombe_sur_le_defaut() -> None:
    req = _FausseRequete({"gm_lang": "kl"}, {"accept-language": "kl"})
    assert resolve_locale(req) == DEFAULT  # type: ignore[arg-type]

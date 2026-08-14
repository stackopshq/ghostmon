"""Ce que `decode_token` doit refuser.

Ce fichier existe à cause d'une migration. `python-jose` validait `exp` de
lui-même ; `joserfc` ne valide **rien** par défaut — il vérifie la signature et
rend les claims. Une traduction ligne à ligne du module aurait donc produit un
service acceptant indéfiniment des jetons expirés, sans erreur ni journal.

Et rien ne l'aurait dit : avant ce fichier, `create_access_token` et
`decode_token` n'avaient **aucun test**. Le premier cas ci-dessous est donc le
vrai sujet ; l'aller-retour n'est là que pour prouver que le reste marche.
"""

from datetime import timedelta

import pytest

from app.core.security.tokens import TokenError, create_access_token, decode_token


def test_aller_retour():
    token = create_access_token("abc", {"role": "admin"})
    claims = decode_token(token)
    assert claims["sub"] == "abc"
    assert claims["role"] == "admin"
    assert claims["type"] == "access"


def test_un_jeton_expire_est_refuse():
    """Le cas qui justifie ce fichier.

    `expires_in` négatif : le jeton naît déjà périmé, ce qui évite d'attendre
    dans un test — et mesure exactement ce qui nous intéresse, la validation de
    `exp` à la lecture, pas l'écoulement du temps.
    """
    token = create_access_token("abc", expires_in=timedelta(seconds=-10))
    with pytest.raises(TokenError):
        decode_token(token)


def test_un_jeton_sans_expiration_est_refuse():
    """`exp` est déclaré `essential`, donc son ABSENCE est aussi un refus.

    Sans ce mot, la validation ne porterait que sur les claims présents : un
    jeton forgé sans `exp` passerait, et serait valable pour toujours.
    """
    from joserfc import jwt
    from joserfc.jwk import OctKey

    from app.core.config import get_settings

    key = OctKey.import_key(get_settings().app_secret_key)
    sans_exp = jwt.encode({"alg": get_settings().jwt_algorithm}, {"sub": "abc"}, key)
    with pytest.raises(TokenError):
        decode_token(sans_exp)


def test_une_signature_etrangere_est_refusee():
    from joserfc import jwt
    from joserfc.jwk import OctKey

    from app.core.config import get_settings

    autre = OctKey.import_key("x" * 48)
    forge = jwt.encode(
        {"alg": get_settings().jwt_algorithm}, {"sub": "abc", "exp": 9999999999}, autre
    )
    with pytest.raises(TokenError):
        decode_token(forge)

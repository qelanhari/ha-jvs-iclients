"""Client aiohttp des portails abonnés JVS-Mairistem « iclients » (Omega).

Flux : découverte du ``Api-Id`` dans le bundle JS public, login JSON:API, puis appels authentifiés
par l'en-tête ``Authorization`` (JWT renvoyé en en-tête de réponse) et les cookies de session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientSession

JSON_API = "application/vnd.api+json"
PARIS = ZoneInfo("Europe/Paris")
_BUNDLE_RE = re.compile(r'src="(/assets/index-[^"]+\.js)"')
_API_ID_RE = re.compile(r'"Api-Id":"([^"]+)"')


class JvsPortalError(Exception):
    """Erreur de communication avec le portail."""


class JvsAuthError(JvsPortalError):
    """Identifiants refusés ou session expirée."""


class JvsApiIdNotFound(JvsPortalError):
    """Impossible de trouver le Api-Id dans le bundle du portail."""


@dataclass(frozen=True)
class Contract:
    """Contrat d'abonnement."""

    id: str
    number: str
    active: bool
    principal: bool


@dataclass(frozen=True)
class Meter:
    """Compteur rattaché au contrat."""

    serial: str | None
    brand: str | None
    diameter: str | None
    model: str | None
    installed_on: str | None


@dataclass(frozen=True)
class Reading:
    """Relevé journalier de télérelève."""

    at: datetime
    index_liters: int
    consumption_liters: int | None
    estimated: bool

    @property
    def index_m3(self) -> float:
        """Index compteur en m³."""
        return self.index_liters / 1000


def parse_reading(item: dict[str, Any]) -> Reading | None:
    """Convertit un ``PORLV_Teleconso2`` ; ``None`` pour les éléments de complétion."""
    attrs = item.get("attributes", {})
    if str(item.get("id", "")).startswith("completion") or attrs.get("ni") is None:
        return None
    at = datetime.strptime(attrs["dateni"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=PARIS)
    return Reading(
        at=at,
        index_liters=int(attrs["ni"]),
        consumption_liters=attrs.get("l"),
        estimated=bool(attrs.get("estimated_consumption")),
    )


def _parse_contract(item: dict[str, Any]) -> Contract:
    attrs = item.get("attributes", {})
    return Contract(
        id=str(item["id"]),
        number=str(attrs.get("numcontrat") or item["id"]),
        active=bool(attrs.get("actif")),
        principal=bool(attrs.get("principal")),
    )


def _parse_meter(included: list[dict[str, Any]]) -> Meter | None:
    for item in included:
        if item.get("type") == "POICL_Compteur":
            attrs = item.get("attributes", {})
            return Meter(
                serial=attrs.get("numserie"),
                brand=attrs.get("enum_marq"),
                diameter=attrs.get("enum_diam"),
                model=attrs.get("enum_tcpt"),
                installed_on=attrs.get("dateinst"),
            )
    return None


async def discover_api_id(session: ClientSession, base_url: str) -> str:
    """Lit le ``Api-Id`` codé en dur dans le bundle JS public du portail."""
    try:
        async with session.get(f"{base_url}/") as response:
            match = _BUNDLE_RE.search(await response.text())
            if match is None:
                raise JvsApiIdNotFound("bundle JS introuvable dans la page d'accueil")
        async with session.get(f"{base_url}{match.group(1)}") as response:
            api_match = _API_ID_RE.search(await response.text())
    except ClientError as err:
        raise JvsPortalError(f"portail injoignable: {err}") from err
    if api_match is None:
        raise JvsApiIdNotFound("Api-Id absent du bundle JS")
    return api_match.group(1)


class JvsIclientsClient:
    """Client du portail : ``authenticate()`` avant chaque série d'appels, aucun jeton conservé."""

    def __init__(
        self,
        session: ClientSession,
        base_url: str,
        api_id: str,
        login: str,
        password: str,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._login = login
        self._password = password
        # Origin et Referer sont obligatoires : sans eux, 403 vide sur les endpoints de données.
        self._headers = {
            "Accept": JSON_API,
            "Api-Id": api_id,
            "Authorization": "JWT",
            "Origin": self._base_url,
            "Referer": f"{self._base_url}/accueil",
        }

    async def authenticate(self) -> None:
        """POST /signin ; conserve l'en-tête ``authorization`` renvoyé."""
        body = {
            "data": {
                "type": "POICL_Signin",
                "id": "",
                "attributes": {"login": self._login, "password": self._password, "remember": False},
            }
        }
        headers = {**self._headers, "Authorization": "JWT", "Content-Type": JSON_API}
        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/iclients/signin", json=body, headers=headers
            ) as response:
                authorization = response.headers.get("authorization")
                if response.status in (401, 403):
                    raise JvsAuthError(f"login refusé ({response.status})")
                if response.status >= 400:
                    raise JvsPortalError(f"login: HTTP {response.status}")
                if not authorization:
                    raise JvsAuthError("login refusé (pas de jeton renvoyé)")
        except ClientError as err:
            raise JvsPortalError(f"portail injoignable: {err}") from err
        self._headers["Authorization"] = authorization

    async def contracts(self) -> list[Contract]:
        """GET /contrat : contrats du compte."""
        payload = await self._get("/api/v1/iclients/contrat")
        return [_parse_contract(item) for item in payload.get("data", [])]

    async def meter(self, contract_id: str) -> Meter | None:
        """GET /contrat/<id> avec le compteur inclus."""
        payload = await self._get(
            f"/api/v1/iclients/contrat/{contract_id}", params={"include": "pconso,pconso.compteur"}
        )
        return _parse_meter(payload.get("included", []))

    async def readings(self, contract_id: str, start: date, end: date) -> list[Reading]:
        """GET /teleindex2 : relevés réels entre ``start`` et ``end`` inclus, triés."""
        path = f"/api/v1/iclients/teleindex2/{contract_id}/{start:%Y%m%d}/{end:%Y%m%d}"
        params = {"option[sort]": "asc", "option[algorithm]": "chronological"}
        payload = await self._get(path, params=params)
        parsed = (parse_reading(item) for item in payload.get("data", []))
        return sorted((r for r in parsed if r is not None), key=lambda r: r.at)

    async def _get(self, path: str, params: dict[str, str] | None = None) -> dict[str, Any]:
        try:
            async with self._session.get(
                f"{self._base_url}{path}", params=params, headers=self._headers
            ) as response:
                if response.status in (401, 403):
                    raise JvsAuthError(f"GET {path}: session refusée ({response.status})")
                if response.status != 200:
                    raise JvsPortalError(f"GET {path}: HTTP {response.status}")
                return await response.json(content_type=None)
        except ClientError as err:
            raise JvsPortalError(f"portail injoignable: {err}") from err

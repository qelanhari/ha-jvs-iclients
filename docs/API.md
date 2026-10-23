# Eau du Pic – analyse de l'API du portail abonnés

Portail : `https://eaudupic.client.ccgpsl.fr` (produit « Omega / iclients » de JVS‑Mairistem, version 3.34.13).
Analyse faite le 23/10/2026 depuis une session Chrome connectée. Toutes les réponses sont au format
[JSON:API](https://jsonapi.org) (`Accept: application/vnd.api+json`).

## 1. En-têtes obligatoires sur chaque appel

| En-tête | Valeur | Remarque |
|---|---|---|
| `Api-Id` | `d2e3b03552d0e10cfa2a5e1e9e3dc73b@iclients-35664-picsaintloup` | Constante codée en dur dans le bundle JS (identifie la collectivité). Sans lui : `401 Not authorized !`. |
| `Authorization` | `Jwt id="<jwt>"` | Renvoyé par le login (voir §2). Avant login le front envoie la valeur `JWT`. |
| `Accept` | `application/vnd.api+json` | |
| `Origin`, `Referer` | `https://eaudupic.client.ccgpsl.fr`, `…/accueil` | **Obligatoires** sur les endpoints de données (`contrat`, `teleindex2`…) : sans eux, `403` à corps vide. `signin` et `check` passent sans. Vérifié hors navigateur le 23/10/2026. |
| Cookies | `OGAWEB2227` (+ `Sso-Id`, `App-Id`, `Api-Id`) | Posés par le serveur au login. Conserver le cookie jar entre les appels. |

Le JWT (RS256) contient `aud.login`, `aud.ip`, `aud.ssoid`, et expire **100 h après émission** (`exp - iat = 360000 s`).
Il n'est pas renouvelé par les appels suivants : il faut se reconnecter (login + mot de passe, ou jeton « remember me », voir §2.3).

## 2. Authentification

### 2.1 Login

```
POST /api/v1/iclients/signin
Content-Type: application/vnd.api+json
Api-Id: <constante>
Authorization: JWT

{"data":{"type":"POICL_Signin","id":"","attributes":{"login":"<email>","password":"<mot de passe>","remember":false}}}
```

Réponse `201 Created` : corps JSON:API de type `POICL_User` et **en-têtes de réponse** :

| En-tête | Usage |
|---|---|
| `authorization` | Valeur complète `Jwt id="…"` à renvoyer telle quelle dans `Authorization` |
| `sso-id`, `app-id` | Le front les stocke (cookies `Sso-Id`/`App-Id`) mais ne les renvoie pas en pratique ; non requis |
| `autologin` | Présent seulement si `remember: true` ; jeton valable 1 an (§2.3) |

Si la collectivité active le MFA, la réponse est un `POICL_UserToken` et un code est demandé via `/public/code-connexion`
(`POST /api/v1/iclients/franceconnect/signin-mfa`). Ce n'est **pas** le cas sur Eau du Pic aujourd'hui.

### 2.2 Vérifier / rafraîchir une session

`POST /api/v1/iclients/check` (corps `{}`) avec `Authorization` → `200` + `POICL_User` si le JWT est valide.
Ne renvoie **pas** de nouveau JWT. Un `202` signifie qu'un code MFA est attendu.

### 2.3 Jeton « remember me »

Avec `remember: true`, le login renvoie l'en-tête `autologin`. Il peut ensuite être envoyé dans l'en-tête `AutoLogin`
sur `POST /api/v1/iclients/check` pour obtenir un nouveau `authorization` sans mot de passe. Non testé ici (la session
analysée n'avait pas coché « se souvenir de moi »).

### 2.4 Logout

`GET /api/v1/iclients/signout/<Api-Id>`.

## 3. Contrats

```
GET /api/v1/iclients/contrat
```

Liste des contrats du compte (`POICL_Contrat`). Champs utiles : `id` (identifiant interne, ex. `5288` (fictif), **c'est lui qui
est utilisé dans les URLs**), `numcontrat` (numéro visible, ex. `<numcontrat>`), `actif`, `principal`, `assujetti_a`.

Détail d'un contrat avec le compteur :

```
GET /api/v1/iclients/contrat/<id>?include=pconso,pconso.compteur,pconso.dernierreleve,telereleve
```

`included` contient entre autres `POICL_Compteur` (`numserie`, `enum_marq` = DIEHL, `enum_diam` = 15, `dateinst`,
`nbroues`) et `POGRC_Releve` (dernier relevé facturé : `dateai`/`ai`, `dateni`/`ni` en m³).

## 4. Télérelève (le point important pour Home Assistant)

```
GET /api/v1/iclients/teleindex2/<contrat_id>/<AAAAMMJJ>/<AAAAMMJJ>?option[sort]=asc&option[algorithm]=chronological
```

* Dates incluses, format `YYYYMMDD`. Le front demande 7 jours (vue semaine) ou 30 jours (vue mois), mais une plage
  longue fonctionne (`20250101/20261023` → 661 éléments, 39 relevés réels).
* `option[algorithm]` : seule la valeur `chronological` est utilisée par le front (configurable côté collectivité).
* Un relevé par jour, horodaté `01:00:00` (heure locale). Les données sont disponibles avec **1 à 2 jours de retard**.
* Partenaire : `suez` (module radio Diehl, lu par Suez).

Chaque élément `PORLV_Teleconso2` :

| Attribut | Sens |
|---|---|
| `dateni` | Date/heure du relevé (`"2026-10-20 01:00:00"`, heure locale, sans fuseau) |
| `ni` | **Index compteur en litres** (`106945` → 106,945 m³ ; le graphe « Index (m³) » affiche `ni/1000`) |
| `nie` | Index estimé (identique à `ni` sur un relevé réel) |
| `previous_dateni`, `previous_ni`, `after_dateni`, `after_ni` | Relevés voisins |
| `l` | Consommation du jour en litres (`ni - previous_ni`), `null` sur le premier relevé |
| `m3` | Partie entière de la consommation en m³ |
| `estimated_consumption` | `true` si la conso est estimée |
| `typerlv` | `TÉLÉRELÈVE` pour un relevé réel ; `NON DÉFINI` sur les jours sans donnée |
| `numserie`, `nummodule`, `id_externe` | Numéro de série du compteur, du module radio, identifiant Suez |

Les jours sans relevé sont renvoyés comme éléments de **complétion** (`id` = `completion_N`, `typerlv` = `NON DÉFINI`,
`ni` absent) : il faut les ignorer.

Exemple réel (contrat <id>, 20→21 oct. 2026) :

```json
{"type":"PORLV_Teleconso2","id":"4854b4…","attributes":{"partner":"suez","typerlv":"TÉLÉRELÈVE",
 "dateni":"2026-10-20 01:00:00","ni":106945,"nie":106945,
 "previous_dateni":"2026-10-19 01:00:00","previous_ni":106595,
 "after_dateni":"2026-10-21 01:00:00","after_ni":107284,
 "l":350,"m3":0,"add":false,"estimated_consumption":false}}
```

Premier relevé disponible sur ce contrat : `2026-09-10` (index 92 348 L).

## 5. Autres endpoints vus (non nécessaires pour HA)

`/api/v1/iclients/facture`, `/facture/<id>/download`, `/contrat/reglements/<id>`, `/releve/<id>`, `/messages/<id>`,
`/documents`, `/consomme`, `/enumerate`, `/connexion-type`, `/maintenance`, `/settings/langs`,
`/settings/translations/<lng>/<ns>`.

## 6. Recommandation Home Assistant

Les relevés sont journaliers, datés à 01:00 et arrivent avec 1–2 jours de retard : un capteur REST classique
enregistrerait la valeur à l'heure du poll et fausserait l'historique. La bonne approche est d'**importer des
statistiques externes** (`recorder/import_statistics` via l'API WebSocket), comme le font les intégrations Linky/Gazpar.
Le dossier `eaudupic/` contient un client Python qui fait exactement cela ; voir `README.md`.

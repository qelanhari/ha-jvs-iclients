# Portail abonnés eau JVS (iclients) pour Home Assistant

Intégration HACS pour les **portails abonnés eau JVS‑Mairistem « iclients »** (Omega), avec **Eau du Pic**
(Grand Pic Saint‑Loup) en préréglage. Elle lit la télérelève du compteur et l'importe dans les statistiques
de Home Assistant à la bonne date, pour le tableau de bord Énergie (section Eau).

> API privée, non documentée, analysée depuis le portail (voir [docs/API.md](docs/API.md)).
> Un changement du portail peut casser l'intégration.

## Fonctionnement

- Un relevé par jour, daté 01:00, publié avec 1 à 2 jours de retard : l'intégration interroge le portail
  **à 08:00 et 16:00** (heure locale) et **réimporte les 7 derniers jours** comme statistique externe
  `jvs_iclients:<hôte>_<contrat>_water_index` (m³ ; `state` = index, `sum` = index moins l'index du premier relevé, pour que la somme démarre à 0). Au premier démarrage, elle charge
  **2 ans d'historique**.
- Entités par contrat : index compteur (m³), consommation du dernier relevé (L), date du dernier relevé,
  numéro de série du compteur (diagnostic). Appareil « Compteur eau <n° contrat> » avec marque et diamètre.
- Chaque relance refait un login complet, aucun jeton n'est conservé. Si le portail refuse
  l'authentification ou est injoignable, l'intégration **réessaie une heure plus tard** sans redemander le
  mot de passe (pas de flux de réauthentification).
- Pour un autre fournisseur sur le même produit JVS, choisir « Autre portail JVS iclients » et saisir l'URL
  du portail : le `Api-Id` (constante propre à chaque collectivité) est **détecté automatiquement** dans
  le bundle JS public du portail.

## Installation

### HACS (recommandé)

1. HACS → Intégrations → menu ⋮ → **Dépôts personnalisés** → `https://github.com/qelanhari/ha-jvs-iclients`, catégorie *Intégration*.
2. Installer « Portail abonnés eau JVS (Eau du Pic) », redémarrer Home Assistant.
3. Paramètres → Appareils et services → **Ajouter une intégration** → « Portail abonnés eau JVS ».
4. Fournisseur (Eau du Pic ou autre + URL), e‑mail et mot de passe du portail. Si le compte a plusieurs
   contrats, choisir celui à suivre (une entrée par contrat).

### Manuelle (SSH)

```bash
scp -r custom_components/jvs_iclients tankou@<ip-ha>:/tmp/ && ssh tankou@<ip-ha> "sudo mv /tmp/jvs_iclients /config/custom_components/"
```

Puis redémarrer HA et ajouter l'intégration comme ci‑dessus.

## Tableau de bord Énergie

Paramètres → Tableaux de bord → Énergie → **Consommation d'eau** → Ajouter une source → choisir la statistique
`jvs_iclients:…_water_index` (elle apparaît dans la liste des statistiques en m³). La somme suivant l'index,
les barres journalières correspondent à la consommation réelle de chaque jour.

Consommation journalière en carte :

```yaml
type: statistics-graph
stat_types: [change]
period: day
entities:
  - jvs_iclients:eaudupic_client_ccgpsl_fr_<id contrat>_water_index
```

## Développement

```bash
uv sync --python 3.13
uv run pytest                                   # 51 tests, couverture 100 %
uv run ruff check . && uv run ruff format --check .
```

Structure : `api.py` (client aiohttp, découverte du Api-Id), `coordinator.py` (poll + import des statistiques),
`sensor.py`, `config_flow.py` (préréglages, URL libre, choix du contrat, reauth). CI : hassfest, HACS action
et tests (`.github/workflows/validate.yml`).

## Limites connues

- Les relevés arrivent avec 1 à 2 jours de retard : l'index HA est toujours celui d'avant‑hier au mieux.
- Pas de MFA géré : si la collectivité active l'authentification à deux facteurs sur le portail, le login
  échouera (`invalid_auth`).
- Un seul `Api-Id` par portail est détecté ; si le portail change la structure de son bundle, le préréglage
  Eau du Pic garde l'identifiant connu en secours, mais pas un portail saisi à la main.

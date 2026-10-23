# Changelog

## v0.1.0 – première version

- Préréglage **Eau du Pic** (Grand Pic Saint-Loup) et support de tout portail JVS iclients par son URL,
  avec détection automatique du `Api-Id`.
- Import des relevés de télérelève comme statistique externe `jvs_iclients:<hôte>_<contrat>_water_index`
  (m³, somme démarrant à 0) : 2 ans d'historique au premier démarrage puis fenêtre glissante de 7 jours,
  poll toutes les 12 h.
- Capteurs : index compteur, consommation du dernier relevé, date du dernier relevé, numéro de série.
- Flux de configuration avec choix du contrat et réauthentification.
- Requiert Home Assistant 2025.4 ou plus récent.

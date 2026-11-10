# Coûts d'infrastructure — pipeline Attaboy

Coût mensuel de fonctionnement de la solution complète, **hors honoraires**.
Prix vérifiés le 2026-11-10, en **USD hors taxes** (≈ ×1,4 en CAD, taux à vérifier). Les fournisseurs peuvent changer leurs prix.

## Synthèse

| Scénario | USD / mois |
|----------|-----------:|
| Pipeline seul (1 run par jour) | **≈ 4 à 13 $** |
| Pipeline + consultation régulière des données | **≈ 8 à 22 $** |
| Plafond maximum (Snowflake bloqué par le resource monitor) | **≈ 26 à 32 $** |
| Option : Power BI Pro pour partager les rapports en ligne | + 14 $ par utilisateur |

Fourchette basse : le pipeline tourne sur un serveur que le restaurant possède déjà. Fourchette haute : avec un petit VPS dédié.

Pendant la phase de mise en place, Snowflake ne coûte rien : il tourne sur le compte du consultant, financé par des crédits de formation.

## Détail par poste

| Poste | Hypothèse | USD / mois |
|-------|-----------|-----------:|
| **Snowflake : calcul** | Standard, AWS Canada (Central) : 2,25 $ par crédit. Warehouse XS = 1 crédit par heure, facturé à la seconde (60 s minimum à chaque démarrage). | |
| ↳ pipeline quotidien | ≈ 3 à 5 min par jour (ingest + dbt + 60 s avant la mise en veille) ≈ 1,5 à 2,5 crédits | 3,40 à 5,60 |
| ↳ consultation des données | 2 à 4 h de requêtes ou de dashboards par mois ≈ 2 à 4 crédits | 4,50 à 9,00 |
| ↳ plafond | Resource monitor : 10 crédits, puis arrêt forcé à 110 % = 11 crédits | max 24,75 |
| **Snowflake : stockage** | 25 $ par To et par mois. Moins de 1 Go de données la première année. | < 0,10 |
| **Snowflake : services cloud** | Gratuits jusqu'à 10 % du calcul quotidien. | 0 |
| **Serveur** (pipeline, cron) | Un petit VPS suffit, ex. OVHcloud VPS-1 (2 vCores, 4 Go de RAM). 0 $ de plus si le pipeline tourne sur un serveur que le restaurant a déjà. | 0 à 6,20 |
| **Extraction des factures PDF** (OpenRouter) | Modèle à 2 $ / 10 $ par million de tokens (entrée / sortie), + 5,5 % de frais sur l'achat de crédits. ≈ 0,03 $ par facture, 10 à 30 factures par mois. | 0,30 à 1,00 |
| **Surveillance** (Healthchecks.io) | Plan gratuit (20 checks) | 0 |
| **Clover API** | Comprise dans l'abonnement Clover déjà payé par le restaurant | 0 |
| **Visualisation** | Power BI Desktop ou dashboards Snowsight, connectés directement à Snowflake : gratuits (Snowsight consomme seulement du calcul Snowflake, déjà compté plus haut) | 0 |

## Ce qui fait varier la facture

1. **Le temps où le warehouse Snowflake est allumé**, presque tout le coût. Il se met en veille après 60 s d'inactivité. Un dashboard qui se rafraîchit toutes les 5 minutes le garderait allumé en permanence (environ 720 crédits par mois), d'où le plafond à 10 crédits.
2. **La taille du warehouse** : passer de XS à S double le prix par heure. XS suffit pour ce volume.
3. **L'édition** : Enterprise coûte 3,50 $ par crédit au lieu de 2,25 $. Standard suffit.

## Recommandations pour le compte Snowflake du restaurant

- Édition **Standard**, région **AWS Canada (Central)**, paiement à l'usage (on-demand), sans engagement.
- Garder `ATTABOY_RM` : alerte à 75 %, arrêt à 100 %.
- Suivre la consommation dans Snowsight → Admin → Cost Management.

## Sources

- Snowflake : [Pricing guide](https://www.snowflake.com/pricing/pricing-guide/) · [Compute cost](https://docs.snowflake.com/en/user-guide/cost-understanding-compute)
- [OpenRouter : prix des modèles](https://openrouter.ai/models) (modèle défini par `OPENROUTER_MODEL`)
- [OVHcloud VPS (Canada)](https://www.ovhcloud.com/en-ca/vps/)
- [Healthchecks.io pricing](https://healthchecks.io/pricing)

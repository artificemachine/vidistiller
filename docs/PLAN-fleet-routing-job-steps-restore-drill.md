# Plan — Routeur fleet, progrès persistant et restore drill

## 1. Scope summary

Construire trois capacités cohérentes pour Vidistiller : (1) un routeur LLM qui inventorie les modèles réellement chargés via `/v1/models`, élimine les candidats incompatibles puis classe les survivants par priorité, santé, fiabilité et latence; (2) un journal persistant des étapes `download`, `transcribe`, `snapshots`, `slides`, `summarize`, `export`, utilisé par les workers pour reprendre sans rejouer les étapes terminées; (3) une sauvegarde cohérente PostgreSQL + fichiers + configuration non secrète, copiée hors machine et restaurée périodiquement dans un environnement isolé. Le v1 n’inclut pas l’auto-chargement de modèles sur les VM, SSE, le backfill précis des anciens jobs, une interface d’administration du catalogue de modèles, ni plusieurs backends de stockage hors site.

Smallest possible v1: manifeste non secret de profils + routage déterministe, étapes persistantes exposées par le polling existant avec reprise d’une étape échouée, bundle sauvegardé via `rclone` et restore drill isolé produisant RPO/RTO.

Source design docs: brief de cette conversation; [plan historique du resolver](docs/PLAN-vllm-dynamic-model.md) — utile pour le contexte, mais remplacé par ce plan pour la sélection par capacités; [déploiement VM](docs/VM_DEPLOYMENT.md); [ROADMAP](docs/ROADMAP.md).

## 2. Prerequisites

- PostgreSQL 15, Redis 7, Celery, Docker Compose, `pg_dump`/`pg_restore`, `rclone`, et le test PostgreSQL existant `docker-compose.test.yml`.
- Avant de remplir le manifeste de production, vérifier deux fois les capacités et limites de contexte de chaque couple nœud/modèle; `/v1/models` ne fournit que les identifiants et ne prouve ni vision ni contexte.
- Existing code areas:
  - `backend/app/services/llm_resolution.py`, `llm_health.py`, `llm.py`, `llm_providers.py`
  - `backend/app/tasks.py`, `backend/app/services/snapshot.py`, `backend/app/services/slide_detection.py`
  - `backend/app/db/models.py`, `backend/app/schemas.py`, `backend/app/routes/jobs.py`, `backend/app/routes/snapshots.py`
  - `frontend/app/jobs/[id]/page.tsx`, `frontend/components/ProcessingStatus.tsx`
  - `migrations/versions/0002_transcript_fulltext_search.py`, `tests/test_migration_drift.py`
  - `docker-compose.prod.yml`, `.env.example`, `docs/VM_DEPLOYMENT.md`
- Risks/blockers:
  - Les capacités vision et fenêtres de contexte ne sont pas découvrables depuis l’API OpenAI-compatible; un manifeste opérateur est donc obligatoire.
  - `process_transcript` est monolithique et l’unique `celery_task_id` global ne peut pas protéger plusieurs étapes concurrentes; la revendication doit devenir propre à chaque étape.
  - Les snapshots automatiques ne sont pas actuellement exécutés malgré `extract_snapshots`; le plan rend ce choix persistant et exécutable.
  - Le restore drill doit lire une copie hors site et ne doit jamais monter ni modifier les volumes de production.

## 3. Iterations

#### Iteration 1 — Inventaire fleet et manifeste de capacités

**Goal:** Produire un inventaire typé des seuls modèles réellement chargés, enrichis par un profil opérateur déclaré.

**Shippable on its own?** Yes — addition en lecture seule, sans changer la sélection active.

**Source references:**
- `backend/app/services/llm_resolution.py` — vérifier `FLEET_VMS`, `_get_vm_model_ids` et `discover_fleet_model` avant de déplacer la découverte.
- `backend/app/services/llm_health.py` — réutiliser la mesure monotone de latence et la normalisation des erreurs, après vérification de sa forme actuelle.
- `backend/app/core/config.py` — ajouter le chemin optionnel du manifeste sans dupliquer les URLs fleet.

**Files touched:**
- `backend/app/core/llm_model_profiles.json` (new)
- `backend/app/services/llm_fleet.py` (new)
- `backend/app/core/config.py` (modified)
- `backend/app/services/llm_resolution.py` (modified)
- `tests/test_llm_fleet_router.py` (new)
- `.env.example` (modified)
- `docker-compose.prod.yml` (modified)

**Commit message:**
`feat(llm): inventory loaded fleet models with declared capabilities`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_llm_fleet_router.py::test_profile_manifest_requires_all_routing_fields` — exige `node`, `model`, `capabilities`, `priority`, `context_tokens`, `reliability`, `latency_ms`.
  - `tests/test_llm_fleet_router.py::test_inventory_keeps_only_models_reported_by_v1_models` — un profil non chargé n’est pas candidat.
  - `tests/test_llm_fleet_router.py::test_inventory_records_probe_health_and_latency` — chaque observation expose santé et latence mesurée.
  - `tests/test_llm_fleet_router.py::test_inventory_rejects_unknown_loaded_model` — un modèle chargé mais non déclaré reste inéligible.
  - `tests/test_llm_fleet_router.py::test_inventory_survives_one_dead_node` — une panne réseau n’annule pas les autres nœuds.
  - `tests/test_llm_fleet_router.py::test_duplicate_model_ids_remain_distinct_per_node` — deux VM servant le même ID donnent deux candidats.
- GREEN (minimal implementation to pass RED):
  - Définir `ModelCapability`, `ModelProfile`, `FleetObservation` et `discover_inventory()`.
  - Charger un manifeste JSON non secret, validé strictement; clé logique `node:model`.
  - Interroger `/v1/models` avec timeout court, mesurer la latence, joindre uniquement les profils déclarés.
  - Conserver `resolve_user_llm` inchangé pour cette itération.
- REFACTOR (cleanup planned after GREEN):
  - Déplacer `FLEET_VMS` et le parsing OpenAI-compatible dans `llm_fleet.py`; garder des wrappers de compatibilité dans `llm_resolution.py`.

**Test pyramid for this iteration:**
- Smoke: import du manifeste par défaut et inventaire vide sans variables fleet.
- Unit: 6 tests dans `tests/test_llm_fleet_router.py`.
- Integration: découverte multi-VM simulée au niveau HTTP `requests.get`.
- State machine: N/A — aucune transition persistante.
- Contract: validation stricte du manifeste, plage fiabilité 0..1, priorité entière, contexte/latence positifs.
- Regression: les tests existants de `tests/test_llm_resolution.py` restent verts.
- Chaos: timeout, JSON invalide et nœud refusant la connexion.
- E2E: N/A — aucune sélection active.
- Performance: inventaire de quatre nœuds en parallèle; budget inférieur au plus grand timeout individuel, vérifié avec réponses simulées.
- TDD Parity: 100% des nouveaux types/fonctions publics ont un test direct.
- Coverage: assumption: +0.5% global; vérifier avec pytest-cov, aucun `fail_under` actuel.

**Acceptance criteria (binary):**
- [ ] Aucun modèle absent de `/v1/models` n’apparaît dans l’inventaire.
- [ ] Chaque candidat expose capacités, priorité, contexte, fiabilité déclarée, santé et latence.
- [ ] Un modèle inconnu est journalisé puis ignoré.
- [ ] Les tests existants du resolver restent verts.

**Estimated effort:** M

**Blocked by:** None

**Side-effect fence:** repo tree uniquement; toutes les requêtes fleet sont simulées; aucun système live.

#### Iteration 2 — Filtrage, classement et fallback autorisé

**Goal:** Sélectionner un modèle compatible avec une tâche sans dépendre de l’ordre des VM.

**Shippable on its own?** Yes — moteur pur disponible derrière l’API interne, resolver historique encore compatible.

**Source references:**
- `backend/app/services/llm_resolution.py` — vérifier la priorité actuelle donnée au premier modèle/VM avant remplacement.
- `backend/app/services/llm_providers.py` — vérifier les providers locaux/cloud et leurs exigences de clés.
- `backend/app/core/config.py` — réutiliser les réglages provider et ajouter `LLM_ALLOW_CLOUD_FALLBACK=false`.

**Files touched:**
- `backend/app/services/llm_fleet.py` (modified)
- `backend/app/services/llm_resolution.py` (modified)
- `backend/app/core/config.py` (modified)
- `backend/app/core/llm_model_profiles.json` (modified)
- `tests/test_llm_fleet_router.py` (modified)
- `tests/test_llm_resolution.py` (modified)
- `.env.example` (modified)
- `docker-compose.prod.yml` (modified)

**Commit message:**
`feat(llm): route tasks by capability health and context`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_llm_fleet_router.py::test_route_filters_capabilities_before_sorting` — une priorité supérieure ne sauve pas un modèle incompatible.
  - `tests/test_llm_fleet_router.py::test_long_analysis_filters_insufficient_context` — le contexte requis est un filtre dur.
  - `tests/test_llm_fleet_router.py::test_route_excludes_unhealthy_candidate` — un endpoint non sain n’est pas classé.
  - `tests/test_llm_fleet_router.py::test_route_orders_priority_then_reliability_then_latency` — ordre déterministe explicite.
  - `tests/test_llm_fleet_router.py::test_route_never_uses_vm_order_as_tiebreaker` — le dernier tie-break est `node:model`, pas `FLEET_VMS`.
  - `tests/test_llm_fleet_router.py::test_cloud_fallback_is_disabled_by_default` — aucun appel cloud implicite.
  - `tests/test_llm_fleet_router.py::test_cloud_fallback_requires_flag_profile_and_key` — trois conditions nécessaires.
  - `tests/test_llm_fleet_router.py::test_no_compatible_candidate_raises_typed_error` — erreur exploitable, sans fallback incompatible.
- GREEN (minimal implementation to pass RED):
  - Définir `LLMTask` avec `TRANSCRIPT_SUMMARY`, `SNAPSHOT_DESCRIPTION`, `SLIDE_DESCRIPTION`, `LONG_ANALYSIS`, `SLIDE_CLASSIFICATION`.
  - Définir `RouteRequest(required_capabilities, required_context_tokens)` et `route_llm(owner, request)`.
  - Filtrer chargé + sain + capacités + contexte; classer `priority desc, reliability desc, observed_latency_ms asc, node:model asc`.
  - Autoriser le cloud uniquement avec flag opérateur, profil compatible et clé disponible; sinon lever `NoCompatibleModelError`.
  - Garder `resolve_user_llm(owner)` comme wrapper de compatibilité pour `TRANSCRIPT_SUMMARY`.
- REFACTOR (cleanup planned after GREEN):
  - Extraire `filter_candidates` et `rank_candidates` comme fonctions pures.

**Test pyramid for this iteration:**
- Smoke: `route_llm` retourne un `ResolvedLLM` synthétique text.
- Unit: 8 tests de filtrage/classement/fallback.
- Integration: wrapper `resolve_user_llm` + provider utilisateur existant.
- State machine: N/A — sélection sans persistance.
- Contract: `LLMTask` vers capacités/contextes requis; cloud désactivé par défaut.
- Regression: `tests/test_llm_resolution.py::TestDynamicFleetAdoption` reste vert avec le wrapper.
- Chaos: nœud mort, flotte vide, cloud sans clé.
- E2E: N/A — moteur pas encore branché aux workers.
- Performance: classement de 100 candidats sous 10 ms sur fixture locale.
- TDD Parity: ≥90%; tout symbole public testé, helpers privés couverts indirectement.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Le candidat choisi satisfait toutes les capacités et le contexte demandés.
- [ ] Modifier l’ordre de `FLEET_VMS` ne change pas le résultat à données égales.
- [ ] Le cloud n’est jamais choisi avec `LLM_ALLOW_CLOUD_FALLBACK=false`.
- [ ] L’absence de candidat compatible produit `NoCompatibleModelError`.

**Estimated effort:** M

**Blocked by:** Iteration 1

**Side-effect fence:** repo tree uniquement; endpoints et clés factices; aucun appel cloud/live.

#### Iteration 3 — Routage effectif des tâches text, vision et longues

**Goal:** Faire utiliser le routeur par la synthèse, l’analyse longue, la description de snapshots/slides et la classification de slides.

**Shippable on its own?** Yes — remplace le choix “premier modèle” tout en gardant le wrapper de compatibilité.

**Source references:**
- `backend/app/tasks.py` — vérifier `_resolve_job_llm`, `summarize_transcript_task` et `process_slides` avant intégration.
- `backend/app/services/llm.py` — vérifier le vision pre-pass `summarize_transcript_sections` et `_analyze_transcript`.
- `backend/app/services/slide_detection.py` — vérifier `llm_ambiguity_classification`.
- `backend/app/routes/health.py` — étendre le diagnostic sans inventer une seconde résolution.

**Files touched:**
- `backend/app/tasks.py` (modified)
- `backend/app/services/llm.py` (modified)
- `backend/app/services/slide_detection.py` (modified)
- `backend/app/routes/health.py` (modified)
- `backend/app/schemas.py` (modified)
- `tests/test_llm_task_routing.py` (new)
- `tests/test_llm_celery_task_resolution.py` (modified)
- `tests/test_llm_vision_prepass.py` (modified)
- `tests/test_process_slides_task.py` (modified)
- `tests/test_diagnostics.py` (modified)

**Commit message:**
`feat(llm): route transcript and vision work to compatible models`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_llm_task_routing.py::test_summary_requests_text_capability`.
  - `tests/test_llm_task_routing.py::test_long_transcript_requests_sufficient_context` — estimation déterministe `ceil(chars/4)+output_reserve`.
  - `tests/test_llm_task_routing.py::test_snapshot_prepass_uses_separate_vision_route`.
  - `tests/test_llm_task_routing.py::test_slide_image_fallback_uses_vision_route`.
  - `tests/test_llm_task_routing.py::test_slide_ambiguity_requests_text_classification`.
  - `tests/test_llm_task_routing.py::test_incompatible_vision_model_is_never_called`.
  - `tests/test_diagnostics.py::test_diagnostics_exposes_route_reason_and_candidate_metrics`.
- GREEN (minimal implementation to pass RED):
  - Router une fois pour text/long analysis et séparément pour vision.
  - Permettre à `LLMService` de recevoir un provider/modèle vision distinct du provider/modèle text.
  - Calculer le contexte requis avant la sélection; ne jamais tronquer silencieusement pour rendre un candidat compatible.
  - Enregistrer dans les logs le task type, modèle, nœud, contexte, latence et raison de sélection, sans clé ni secret.
- REFACTOR (cleanup planned after GREEN):
  - Remplacer `_resolve_job_llm` par un adaptateur unique autour de `route_llm`; supprimer la dépendance fonctionnelle à `discover_fleet_model()[0]`.

**Test pyramid for this iteration:**
- Smoke: tâche de résumé avec providers factices text + vision.
- Unit: 6 tests de mapping tâche/exigences.
- Integration: worker → routeur → `LLMService`; diagnostic → même routeur.
- State machine: N/A — aucune étape DB encore.
- Contract: schéma diagnostic enrichi, sans secrets.
- Regression: vision pre-pass existant et staleness guards restent verts.
- Chaos: vision indisponible avec text disponible échoue/saute explicitement selon le mode, sans appeler text comme vision.
- E2E: résumé synthétique contenant une annotation vision produite par deux providers factices.
- Performance: une découverte partagée/cache courte par tâche, au plus une sonde par nœud; assertion de nombre d’appels HTTP.
- TDD Parity: ≥85%; toutes les nouvelles branches publiques testées.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Une synthèse n’utilise qu’un profil `text`.
- [ ] Une description d’image n’utilise qu’un profil `vision`.
- [ ] Une analyse longue ne sélectionne aucun modèle sous le contexte requis.
- [ ] Le diagnostic explique le choix final et les candidats rejetés sans exposer de secret.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 2

**Side-effect fence:** repo tree et fixtures synthétiques; aucun endpoint fleet/cloud réel.

#### Iteration 4 — Schéma persistant et machine d’états des étapes

**Goal:** Persister six étapes par nouveau job avec transitions atomiques et idempotentes.

**Shippable on its own?** Yes — API additive; le statut global reste compatible.

**Source references:**
- `backend/app/db/models.py` — vérifier `ProcessingJob`, `ProcessingStatus` et les relations cascade.
- `backend/app/routes/jobs.py` — vérifier la transaction de `create_job` et les réponses status/detail.
- `migrations/versions/0002_transcript_fulltext_search.py` — utiliser comme `down_revision`.
- `tests/test_migration_drift.py` — réutiliser le contrôle Alembic-vers-modèles.

**Files touched:**
- `backend/app/db/models.py` (modified)
- `backend/app/services/job_steps.py` (new)
- `backend/app/schemas.py` (modified)
- `backend/app/routes/jobs.py` (modified)
- `migrations/versions/0003_job_steps.py` (new)
- `tests/test_job_steps.py` (new)
- `tests/test_job_steps_routes.py` (new)
- `tests/test_migration_drift.py` (modified)

**Commit message:**
`feat(jobs): persist atomic progress for each processing step`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_job_steps.py::test_seed_creates_six_unique_steps`.
  - `tests/test_job_steps.py::test_claim_pending_step_is_atomic_and_increments_attempt`.
  - `tests/test_job_steps.py::test_same_claim_token_is_idempotent`.
  - `tests/test_job_steps.py::test_different_claim_cannot_steal_running_step`.
  - `tests/test_job_steps.py::test_progress_is_monotonic_and_bounded`.
  - `tests/test_job_steps.py::test_stale_claim_cannot_complete_step`.
  - `tests/test_job_steps.py::test_failure_persists_error_finish_time_and_metrics`.
  - `tests/test_job_steps_routes.py::test_job_status_returns_steps_in_canonical_order`.
- GREEN (minimal implementation to pass RED):
  - Ajouter `JobStep`: `name`, `status`, `attempt`, `percent`, `started_at`, `finished_at`, `error_message`, `metrics` JSON, `claim_token`, timestamps, contrainte unique `job_id,name`.
  - Statuts: `pending`, `running`, `completed`, `failed`, `skipped`, `cancelled`.
  - Implémenter `seed_job_steps`, `claim_step`, `set_step_progress`, `complete_step`, `fail_step`, `skip_step` par UPDATE conditionnel et vérification `rowcount`.
  - Créer les étapes dans la même transaction que le job; `slides` est `skipped` hors mode slide, `snapshots` selon `extract_snapshots`.
  - Retourner `steps` dans `JobStatusResponse` et `JobResponse`; anciens jobs: liste vide, sans faux backfill.
- REFACTOR (cleanup planned after GREEN):
  - Centraliser ordre canonique et graphe de dépendances dans `job_steps.py`.

**Test pyramid for this iteration:**
- Smoke: `alembic upgrade head` crée `job_steps`.
- Unit: 7 tests de service.
- Integration: création API → six lignes → status API.
- State machine: pending→running→completed; pending/failed→running; running→failed/cancelled; terminal protégé.
- Contract: contraintes DB, enum applicatif, ordre de réponse.
- Regression: `test_alembic_head_matches_models` et réponses jobs existantes.
- Chaos: deux sessions DB tentent de revendiquer la même étape; une seule réussit.
- E2E: N/A — UI inchangée.
- Performance: requête status charge six lignes avec une relation; pas de N+1.
- TDD Parity: 100% des fonctions publiques du service testées.
- Coverage: assumption: +1% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Un nouveau job contient exactement six étapes persistées.
- [ ] Deux claim tokens concurrents ne peuvent pas exécuter la même étape.
- [ ] Un worker obsolète ne peut ni terminer ni faire échouer l’étape d’un autre worker.
- [ ] La migration est sans drift sur PostgreSQL.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 3

**Side-effect fence:** repo tree + PostgreSQL de test synthétique; aucun DB/live.

#### Iteration 5 — Checkpoints download/transcribe sans reprise globale

**Goal:** Reprendre `download` ou `transcribe` en sautant toute étape déjà terminée.

**Shippable on its own?** Yes — même tâche Celery et même résultat, avec checkpoints durables.

**Source references:**
- `backend/app/tasks.py` — vérifier `process_transcript`, `_fetch_platform_captions`, `_transcribe_audio`, `_save_transcript_and_segments`.
- `backend/app/services/video.py` — vérifier les chemins de sortie réutilisables avant de considérer un téléchargement terminé.
- `tests/test_task_idempotency.py` — préserver les gardes terminales/redelivery.

**Files touched:**
- `backend/app/tasks.py` (modified)
- `backend/app/services/job_steps.py` (modified)
- `tests/test_task_step_progress.py` (new)
- `tests/test_task_idempotency.py` (modified)
- `tests/test_transcript_service.py` (modified)

**Commit message:**
`refactor(jobs): checkpoint download and transcription work`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_task_step_progress.py::test_process_transcript_claims_and_completes_transcribe`.
  - `tests/test_task_step_progress.py::test_retry_skips_completed_transcribe`.
  - `tests/test_task_step_progress.py::test_retry_reuses_existing_video_download`.
  - `tests/test_task_step_progress.py::test_transcribe_failure_marks_only_transcribe_failed`.
  - `tests/test_task_step_progress.py::test_download_failure_preserves_completed_transcript`.
  - `tests/test_task_step_progress.py::test_redelivery_with_other_claim_skips_without_mutation`.
- GREEN (minimal implementation to pass RED):
  - Extraire `run_transcribe_step` et `run_download_step`.
  - Revendiquer chaque étape avec `self.request.id`; sauter `completed/skipped`.
  - Réutiliser Transcript/video_file_path existants lorsque leur étape est terminée et l’artefact existe.
  - Enregistrer métriques source/langue/caractères pour transcribe et chemin/taille/durée pour download.
  - Calculer le statut global à partir des étapes obligatoires, sans effacer une réussite partielle.
- REFACTOR (cleanup planned after GREEN):
  - Réduire `process_transcript` à un orchestrateur de fonctions d’étape.

**Test pyramid for this iteration:**
- Smoke: tâche synthétique captions-only atteint transcribe completed.
- Unit: 6 tests de checkpoints.
- Integration: Celery task directe + SQLite DB + services mockés.
- State machine: failed→running→completed et redelivery running→skip.
- Contract: métriques JSON stables et sans chemin secret.
- Regression: tests de `TestProcessTranscriptIdempotency` et staleness guard.
- Chaos: crash simulé après commit transcribe puis avant download; redelivery ne retranscrit pas.
- E2E: N/A — UI pas encore branchée.
- Performance: compteur de mocks prouve zéro nouvel appel réseau pour une étape completed.
- TDD Parity: ≥85%.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Une reprise après échec download ne rappelle pas la transcription terminée.
- [ ] Une reprise après échec transcribe réutilise le média téléchargé valide.
- [ ] Une redelivery concurrente ne modifie aucune étape détenue par un autre token.
- [ ] Le statut global reste compatible avec les clients actuels.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 4

**Side-effect fence:** repo tree + fichiers temporaires de test; aucun média utilisateur/live.

#### Iteration 6 — Étapes snapshots et slides orchestrées

**Goal:** Exécuter et reprendre snapshots/slides indépendamment avec progression et métriques.

**Shippable on its own?** Yes — ferme le chemin média demandé par `extract_snapshots` et conserve le mode slide.

**Source references:**
- `backend/app/services/snapshot.py` — vérifier `detect_scene_changes`, `extract_frames`, `save_snapshots`.
- `backend/app/routes/snapshots.py` — vérifier les deux endpoints d’extraction manuelle et leur contrôle de chemin.
- `backend/app/tasks.py` — vérifier la dispatch actuelle `process_slides.delay`.
- `backend/app/services/slide_detection.py` — vérifier `run_full_pipeline` et son `cancel_check`.

**Files touched:**
- `backend/app/tasks.py` (modified)
- `backend/app/services/snapshot.py` (modified)
- `backend/app/services/job_steps.py` (modified)
- `backend/app/routes/snapshots.py` (modified)
- `tests/test_snapshot_step_task.py` (new)
- `tests/test_snapshot_routes.py` (modified)
- `tests/test_process_slides_task.py` (modified)
- `tests/test_slide_routes.py` (modified)

**Commit message:**
`feat(jobs): resume snapshot and slide processing by step`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_snapshot_step_task.py::test_requested_snapshots_dispatch_after_download`.
  - `tests/test_snapshot_step_task.py::test_snapshot_progress_callback_is_monotonic`.
  - `tests/test_snapshot_step_task.py::test_snapshot_retry_skips_existing_completed_rows`.
  - `tests/test_snapshot_step_task.py::test_unrequested_snapshots_are_skipped`.
  - `tests/test_process_slides_task.py::test_slide_task_claims_step_not_global_job_slot`.
  - `tests/test_process_slides_task.py::test_slide_redelivery_cannot_restart_running_step`.
  - `tests/test_process_slides_task.py::test_slide_failure_preserves_other_completed_steps`.
- GREEN (minimal implementation to pass RED):
  - Ajouter `process_snapshots` Celery et un callback optionnel de progression aux boucles snapshot.
  - Enchaîner download→snapshots→slides selon les étapes pending/skipped, avec une seule étape revendiquée à la fois.
  - Adapter les endpoints manuels pour utiliser la même machine d’états.
  - Remplacer le verrou fonctionnel `ProcessingJob.celery_task_id` par `JobStep.claim_token` pour snapshots/slides; garder le champ global comme compatibilité UI/cancel jusqu’à migration ultérieure.
  - Stocker comptes, durée, frames analysées et LLM classifications dans metrics.
- REFACTOR (cleanup planned after GREEN):
  - Extraire `dispatch_next_media_step` et `recompute_job_status`.

**Test pyramid for this iteration:**
- Smoke: pipeline synthétique avec une frame et une slide.
- Unit: 7 tests de tâches/callbacks.
- Integration: task→SnapshotService→DB et task→SlideDetectionService→DB.
- State machine: snapshots/slides pending→running→completed/failed/skipped.
- Contract: `extract_snapshots=false` implique snapshots skipped; standard implique slides skipped.
- Regression: incident redelivery PR #200 couvert par le claim d’étape.
- Chaos: exception après sauvegarde des snapshots mais avant ack; redelivery ne crée pas de doublons.
- E2E: N/A — rendu UI à l’itération 8.
- Performance: callback limité à des écritures par paliers (≤20 updates par étape).
- TDD Parity: ≥85%.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Un job `extract_snapshots=true` exécute snapshots après download.
- [ ] Un job standard marque slides skipped.
- [ ] Une reprise slides ne rejoue ni transcribe, ni download, ni snapshots terminés.
- [ ] Une redelivery ne duplique ni snapshots ni slides.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 5

**Side-effect fence:** repo tree + petites images/vidéos fixtures; aucun fichier sous le data dir live.

#### Iteration 7 — Summarize, export et endpoint de reprise

**Goal:** Suivre summarize/export et permettre la reprise explicite d’une étape échouée.

**Shippable on its own?** Yes — API complète de reprise avec compatibilité `summarize_status`.

**Source references:**
- `backend/app/tasks.py` — vérifier `summarize_transcript_task` et sa garde de document existant.
- `backend/app/routes/jobs.py` — vérifier `export_job`, `summarize_transcript` et `cancel_job`.
- `tests/test_job_export_import.py` — préserver le contrat export/import 1.0.

**Files touched:**
- `backend/app/tasks.py` (modified)
- `backend/app/routes/jobs.py` (modified)
- `backend/app/services/job_steps.py` (modified)
- `backend/app/schemas.py` (modified)
- `tests/test_step_retry.py` (new)
- `tests/test_llm_celery_task_resolution.py` (modified)
- `tests/test_job_export_import.py` (modified)

**Commit message:**
`feat(jobs): retry failed summarize and export steps`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_step_retry.py::test_retry_failed_transcribe_dispatches_pipeline_without_resetting_completed_steps`.
  - `tests/test_step_retry.py::test_retry_failed_snapshots_dispatches_snapshot_task_only`.
  - `tests/test_step_retry.py::test_retry_failed_slides_dispatches_slide_task_only`.
  - `tests/test_step_retry.py::test_retry_failed_summarize_dispatches_summary_task_only`.
  - `tests/test_step_retry.py::test_retry_rejects_running_completed_or_unauthorized_step`.
  - `tests/test_step_retry.py::test_export_retry_resets_step_and_requires_new_download_request`.
  - `tests/test_job_export_import.py::test_export_step_records_bytes_and_item_counts`.
  - `tests/test_llm_celery_task_resolution.py::test_summarize_step_claim_blocks_stale_completion`.
- GREEN (minimal implementation to pass RED):
  - Utiliser la machine d’états pour summarize tout en miroirant `summarize_status` pendant la compatibilité.
  - Encadrer `export_job` par claim/complete/fail; métriques bytes, transcripts, snapshots, documents.
  - Ajouter `POST /jobs/{job_id}/steps/{step_name}/retry`; mapper chaque étape à sa tâche, valider ownership et dépendances.
  - Ne remettre à pending que l’étape ciblée; les prédécesseurs completed restent intacts.
- REFACTOR (cleanup planned after GREEN):
  - Centraliser le mapping step→dispatcher et la validation de dépendances.

**Test pyramid for this iteration:**
- Smoke: retry synthétique summarize retourne 202.
- Unit: 8 tests de mapping et transitions.
- Integration: routes auth→DB→Celery mocks; export réel sur petits artefacts.
- State machine: failed/cancelled→pending→running; terminal/running retry interdit.
- Contract: 202 pour dispatch, 409 transition invalide, 404 ownership masqué.
- Regression: export/import v1.0 et document-source-of-truth du summarize restent verts.
- Chaos: exception JSONResponse/read file marque export failed sans toucher aux autres étapes.
- E2E: API new job fixture→échec summarize→retry→completed.
- Performance: export ne fait qu’un claim et un complete, hors génération existante.
- TDD Parity: ≥85%.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Chaque étape échouée possède une reprise autorisée et ciblée.
- [ ] Retenter summarize ne rejoue aucune étape média.
- [ ] Export conserve son contrat de fichier et persiste ses métriques.
- [ ] Une reprise inter-utilisateur est refusée.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 6

**Side-effect fence:** repo tree + DB/fichiers fixtures; aucune tâche live.

#### Iteration 8 — UI de progression réelle par étape

**Goal:** Remplacer le faux 50% global par six étapes persistantes et une action retry sur échec.

**Shippable on its own?** Yes — parcours utilisateur complet via le polling 5 s existant.

**Source references:**
- `frontend/app/jobs/[id]/page.tsx` — vérifier `JobDetail`, `pollJob` et les trois rendus `ProcessingStatus`.
- `frontend/components/ProcessingStatus.tsx` — préserver l’affichage global de compatibilité.
- `frontend/__tests__/pages/JobDetail.test.tsx` — réutiliser les mocks Axios et fake timers existants.

**Files touched:**
- `frontend/components/JobStepsProgress.tsx` (new)
- `frontend/components/ProcessingStatus.tsx` (modified)
- `frontend/app/jobs/[id]/page.tsx` (modified)
- `frontend/__tests__/components/JobStepsProgress.test.tsx` (new)
- `frontend/__tests__/components/ProcessingStatus.test.tsx` (modified)
- `frontend/__tests__/pages/JobDetail.test.tsx` (modified)
- `e2e/tests/job-step-progress.spec.ts` (new)

**Commit message:**
`feat(ui): show persistent job steps and targeted retries`

**TDD cycle:**
- RED (failing tests to write first):
  - `frontend/__tests__/components/JobStepsProgress.test.tsx::renders_steps_in_canonical_order`.
  - `frontend/__tests__/components/JobStepsProgress.test.tsx::renders_attempt_percent_timestamps_and_error`.
  - `frontend/__tests__/components/JobStepsProgress.test.tsx::shows_retry_only_for_failed_step`.
  - `frontend/__tests__/components/JobStepsProgress.test.tsx::does_not_invent_progress_when_steps_are_empty`.
  - `frontend/__tests__/pages/JobDetail.test.tsx::retries_only_the_selected_failed_step`.
  - `frontend/__tests__/pages/JobDetail.test.tsx::polling_stops_when_no_step_is_active`.
  - `e2e/tests/job-step-progress.spec.ts::failed_step_can_be_retried_without_resetting_completed_steps`.
- GREEN (minimal implementation to pass RED):
  - Ajouter types `JobStep` et composant accessible listant statut, attempt, pourcentage, erreur et métriques essentielles.
  - Utiliser `steps` du job pour le progrès agrégé; supprimer les valeurs codées 50%.
  - Appeler l’endpoint retry sur la seule étape choisie et reprendre le polling.
  - Garder l’affichage global pour anciens jobs sans steps, sans fausse barre.
- REFACTOR (cleanup planned after GREEN):
  - Extraire un hook `useJobPolling` seulement si nécessaire pour éviter les trois rendus dupliqués.

**Test pyramid for this iteration:**
- Smoke: page détail rend un job avec six étapes.
- Unit: 6 tests Vitest/Testing Library.
- Integration: page→Axios mock→retry→polling.
- State machine: rendu des six statuts et passage failed→pending/running.
- Contract: types TypeScript alignés sur `JobStepResponse`.
- Regression: résumé async, cancel et galerie restent verts.
- Chaos: réponse steps absente/malformée n’effondre pas la page.
- E2E: Playwright intercepte les réponses API successives et prouve que les étapes completed restent completed.
- Performance: un seul polling existant; aucun timer supplémentaire.
- TDD Parity: ≥90% des nouveaux exports/hooks testés.
- Coverage: assumption: +1% frontend; vérifier avec Vitest coverage, aucun seuil actuel.

**Acceptance criteria (binary):**
- [ ] L’UI affiche les six étapes avec les valeurs DB réelles.
- [ ] Aucune barre 50% codée en dur ne subsiste.
- [ ] Retry cible exactement l’étape échouée.
- [ ] Un job historique sans steps reste affichable.

**Estimated effort:** M

**Blocked by:** Iteration 7

**Side-effect fence:** repo tree et API interceptée; aucun job live.

#### Iteration 9 — Bundle de sauvegarde cohérent et copie hors site

**Goal:** Créer un bundle atomique vérifiable contenant DB, data et configuration non secrète, puis le copier hors machine avec rétention.

**Shippable on its own?** Yes — commande de sauvegarde autonome, sans restore automatique.

**Source references:**
- `docker-compose.prod.yml` — vérifier services, data dir, migrations et noms DB; ne pas copier les volumes bruts PostgreSQL.
- `docs/VM_DEPLOYMENT.md` — remplacer le brouillon pg_dump-only après vérification de sa section backup.
- `.env.example` — définir les options sans secret et la liste d’exclusion.

**Files touched:**
- `scripts/backup_system.py` (new)
- `tests/test_backup_system.py` (new)
- `.env.example` (modified)
- `docs/VM_DEPLOYMENT.md` (modified)

**Commit message:**
`feat(backup): create checksummed offsite system bundles`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_backup_system.py::test_bundle_contains_database_data_migrations_and_safe_config`.
  - `tests/test_backup_system.py::test_secret_named_env_keys_are_never_exported`.
  - `tests/test_backup_system.py::test_manifest_records_schema_version_sizes_and_sha256`.
  - `tests/test_backup_system.py::test_bundle_is_published_atomically_after_checksum_validation`.
  - `tests/test_backup_system.py::test_failed_pg_dump_never_publishes_or_prunes`.
  - `tests/test_backup_system.py::test_offsite_copy_is_verified_before_success`.
  - `tests/test_backup_system.py::test_retention_prunes_only_verified_expired_bundles`.
- GREEN (minimal implementation to pass RED):
  - Exécuter `pg_dump --format=custom` avec credentials fournis par environnement sans les imprimer.
  - Copier `app-data`, `alembic.ini`, `migrations/`, compose prod et une env allowlistée; exclure toute clé contenant secret/password/token/key/dsn/credential.
  - Écrire `manifest.json` + `checksums.sha256`, valider, puis rename atomique du temp bundle.
  - Exiger `--offsite-remote` en mode production; `rclone copyto` puis `rclone check`; `--local-only` réservé aux tests/dev.
  - Appliquer rétention locale/distante uniquement aux bundles marqués verified.
- REFACTOR (cleanup planned after GREEN):
  - Extraire runner subprocess, filtre config et checksum walker pour tests purs.

**Test pyramid for this iteration:**
- Smoke: `python scripts/backup_system.py --help`.
- Unit: 7 tests sur temp dirs et subprocess mocké.
- Integration: bundle synthétique avec fake pg_dump et data tree.
- State machine: temp→validated→published→offsite_verified; échec n’avance pas.
- Contract: schema version du manifest et liste allowlist/exclusion.
- Regression: le vieux mode pg_dump-only n’est plus présenté comme sauvegarde validée.
- Chaos: pg_dump non-zéro, fichier change pendant checksum, rclone échoue, disque destination plein simulé.
- E2E: N/A — restore prouvé à l’itération 10.
- Performance: streaming de checksum/copie; mémoire bornée, test avec fichier sparse.
- TDD Parity: 100% des fonctions publiques CLI/helper testées.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Le bundle contient DB, data, migrations et config non secrète.
- [ ] Chaque fichier est couvert par SHA-256 et la vérification passe avant publication.
- [ ] Aucun nom de variable secret-like n’apparaît dans la config exportée.
- [ ] Un échec offsite retourne non-zéro et n’applique pas la rétention.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 8

**Side-effect fence:** tests dans temp dirs; aucun volume live. Le premier backup production nécessite confirmation explicite et écrit seulement dans une destination dédiée + remote configuré.

#### Iteration 10 — Restore drill isolé avec RPO/RTO

**Goal:** Restaurer un bundle hors site dans un stack isolé et prouver migrations, comptes, job, transcript, snapshots et exports.

**Shippable on its own?** Yes — ferme la validation backup/restore et produit un rapport auditable.

**Source references:**
- `docker-compose.test.yml` — reprendre PostgreSQL isolé après vérification; ne pas réutiliser ses container names/volumes fixes.
- `tests/test_migration_drift.py` — réutiliser `alembic upgrade head` et la comparaison de schéma.
- `backend/app/db/models.py` — définir les invariants de preuve users/jobs/transcripts/snapshots/documents.
- `docs/ROADMAP.md` — ne cocher backup qu’après un vrai drill réussi.

**Files touched:**
- `scripts/restore_drill.py` (new)
- `docker-compose.restore-drill.yml` (new)
- `tests/test_restore_drill.py` (new)
- `docs/VM_DEPLOYMENT.md` (modified)
- `docs/ROADMAP.md` (modified)

**Commit message:**
`feat(backup): verify backups with an isolated restore drill`

**TDD cycle:**
- RED (failing tests to write first):
  - `tests/test_restore_drill.py::test_drill_refuses_bundle_with_bad_checksum`.
  - `tests/test_restore_drill.py::test_drill_uses_unique_project_and_temporary_paths`.
  - `tests/test_restore_drill.py::test_drill_never_mounts_production_paths`.
  - `tests/test_restore_drill.py::test_drill_restores_dump_then_runs_alembic_head`.
  - `tests/test_restore_drill.py::test_verifier_requires_account_completed_job_transcript_snapshot_and_export`.
  - `tests/test_restore_drill.py::test_report_contains_numeric_rpo_rto_and_evidence_counts`.
  - `tests/test_restore_drill.py::test_cleanup_targets_only_validated_drill_project`.
  - `tests/test_restore_drill.py::test_failed_verification_returns_nonzero_and_keeps_report`.
- GREEN (minimal implementation to pass RED):
  - Télécharger un bundle depuis `rclone` dans `mktemp`, vérifier manifest/checksums avant extraction.
  - Démarrer Compose avec nom aléatoire préfixé `vidistiller-drill-`, ports dynamiques et volumes temporaires.
  - Restaurer via `pg_restore`, lancer `alembic upgrade head`, puis requêter les invariants et vérifier les fichiers restaurés.
  - Mesurer RPO = âge du snapshot au début; RTO = début restore jusqu’à toutes vérifications vertes.
  - Écrire un rapport JSON/Markdown hors du bundle source; teardown seulement du project/dir validé.
- REFACTOR (cleanup planned after GREEN):
  - Partager validation du manifest/checksum avec `backup_system.py`.

**Test pyramid for this iteration:**
- Smoke: validation CLI et rendu Compose config.
- Unit: 8 tests de garde, calcul et orchestration.
- Integration: Postgres Docker opt-in restaure une fixture synthétique.
- State machine: fetched→verified→restored→migrated→validated→cleaned.
- Contract: rapport versionné avec RPO/RTO, compteurs et verdict.
- Regression: migration drift test exécuté après restore.
- Chaos: checksum corrompu, pg_restore échoue, migration échoue, artefact manquant; aucune suppression source.
- E2E: bundle hors site→stack isolé→preuves complètes→rapport PASS.
- Performance: RPO/RTO réellement mesurés; aucune cible inventée avant décision opérateur.
- TDD Parity: 100% des nouvelles commandes publiques testées.
- Coverage: assumption: +0.5% global; mesurer avec pytest-cov.

**Acceptance criteria (binary):**
- [ ] Le drill lit la copie hors site, pas le bundle local primaire.
- [ ] Migrations, au moins un compte, un job completed, un transcript, un snapshot et un export/document sont vérifiés.
- [ ] Le rapport contient RPO et RTO numériques plus les preuves.
- [ ] Aucun chemin/volume de production n’est monté, modifié ou supprimé.
- [ ] Une corruption ou preuve manquante donne un verdict FAIL et un exit non-zéro.

**Estimated effort:** L (one day maximum)

**Blocked by:** Iteration 9

**Side-effect fence:** stack Docker au nom validé et temp dir uniquement. Exécution du vrai drill requiert confirmation avant Docker; backup source monté/read-only et jamais supprimé.

## 4. Test inventory summary

| Iter | Smoke | Unit | Integration | State machine | Contract | Regression | Chaos | E2E | Performance | TDD Parity | Coverage Δ |
|------|-------|------|-------------|---------------|----------|------------|-------|-----|-------------|------------|------------|
| 1 | 1 | 6 | 1 | 0 | 1 | 1 | 3 | 0 | 1 | 100% | ~+0.5% |
| 2 | 1 | 8 | 1 | 0 | 1 | 1 | 3 | 0 | 1 | ≥90% | ~+0.5% |
| 3 | 1 | 6 | 2 | 0 | 1 | 2 | 1 | 1 | 1 | ≥85% | ~+0.5% |
| 4 | 1 | 7 | 1 | 6 | 1 | 1 | 1 | 0 | 1 | 100% | ~+1% |
| 5 | 1 | 6 | 1 | 2 | 1 | 2 | 1 | 0 | 1 | ≥85% | ~+0.5% |
| 6 | 1 | 7 | 2 | 3 | 2 | 2 | 1 | 0 | 1 | ≥85% | ~+0.5% |
| 7 | 1 | 8 | 2 | 2 | 1 | 2 | 1 | 1 | 1 | ≥85% | ~+0.5% |
| 8 | 1 | 6 | 1 | 1 | 1 | 3 | 1 | 1 | 1 | ≥90% | ~+1% frontend |
| 9 | 1 | 7 | 1 | 1 | 1 | 1 | 4 | 0 | 1 | 100% | ~+0.5% |
| 10 | 1 | 8 | 1 | 1 | 1 | 1 | 4 | 1 | 1 | 100% | ~+0.5% |

Coverage deltas are assumptions because the repo has no recorded baseline or `fail_under`; measure them during implementation rather than present them as results.

## 5. End-to-end definition of done

- Every loaded local model is joined to a declared node/model profile; unknown or incompatible candidates are never selected.
- Text, vision and long-analysis requests use explicit requirements, deterministic ranking and cloud fallback disabled by default.
- New jobs persist exactly six steps; claims, progress and terminal transitions are atomic/idempotent.
- Retrying one failed step leaves all completed predecessors untouched and prevents stale workers from overwriting success.
- The UI displays DB progress and targeted retry; no hardcoded 50% remains.
- A backup bundle contains PostgreSQL, `app-data`, migrations and safe config, has SHA-256, verified retention and verified offsite copy.
- A drill restores the offsite copy in isolation, upgrades migrations, verifies required records/files and emits numeric RPO/RTO.

Single end-to-end manual test:
1. Configure a validated production model manifest; probe each declared node/model twice and compare inventory output.
2. Submit one synthetic/authorized short video with snapshots and slide mode; observe six persisted steps.
3. Inject one controlled snapshots failure, retry only snapshots, and verify transcribe/download attempts do not increment.
4. Trigger summarize and export; confirm text/vision routes and all terminal step metrics.
5. With explicit approval, run `scripts/backup_system.py` against the dedicated backup destination and configured `rclone` remote.
6. With explicit approval, run `scripts/restore_drill.py` from that remote; require PASS evidence and numeric RPO/RTO.
7. Verify production remains healthy and its data/volumes were never mounted by the drill.

Exact test commands that must return green:

- `PYTHONPATH=backend .venv/bin/python -m pytest tests/test_llm_fleet_router.py tests/test_llm_task_routing.py tests/test_llm_resolution.py tests/test_llm_celery_task_resolution.py tests/test_llm_vision_prepass.py tests/test_process_slides_task.py tests/test_diagnostics.py tests/test_job_steps.py tests/test_job_steps_routes.py tests/test_task_step_progress.py tests/test_task_idempotency.py tests/test_transcript_service.py tests/test_snapshot_step_task.py tests/test_snapshot_routes.py tests/test_slide_routes.py tests/test_step_retry.py tests/test_job_export_import.py tests/test_backup_system.py tests/test_restore_drill.py -v`
- `TEST_DATABASE_URL=postgresql://tutorial_user:tutorial_password@localhost:5432/tutorial_db PYTHONPATH=backend .venv/bin/python -m pytest tests/test_migration_drift.py -v`
- `cd frontend && npm test -- --run JobStepsProgress ProcessingStatus JobDetail` (explicit Vitest file stems; full `.tsx` paths are declared in Iteration 8)
- `cd frontend && npm run test:e2e -- job-step-progress.spec.ts`
- `PYTHONPATH=backend .venv/bin/python -m pytest tests/ -q`
- `cd frontend && npm test -- --run`

## 6. Out of scope

- SSE/WebSocket progress — polling exists déjà et suffit au v1; ajouter SSE après stabilisation du contrat DB/API.
- Backfill exact des anciens jobs — les anciens statuts globaux ne permettent pas de reconstruire honnêtement attempts/timestamps/metrics.
- Auto-loading/swap via vllm-manager — mutation d’infrastructure séparée, plus risquée que la sélection de modèles déjà chargés.
- UI d’édition du manifeste de modèles — le catalogue est une configuration opérateur non secrète dans ce v1.
- Apprentissage automatique de fiabilité/latence — le v1 combine valeurs déclarées et latence/health observées; historique persistant plus tard.
- Plusieurs providers offsite — `rclone` fournit une abstraction unique; ajouter des adapters seulement si nécessaire.
- PRA complet/failover production — le restore drill prouve la récupérabilité, pas une bascule automatique.

## 7. Open questions

- Quels couples nœud/modèle sont officiellement certifiés `vision` et quelles fenêtres de contexte faut-il inscrire dans le manifeste initial? Cette décision doit être fondée sur deux vérifications, pas sur le seul nom du modèle.
- Quelle destination `rclone` hors machine doit recevoir les bundles de production?
- Quelles limites maximales RPO et RTO doivent transformer les mesures du drill en gate PASS/FAIL? En attendant, le v1 rapporte les valeurs sans inventer de seuil.

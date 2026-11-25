# Documentation technique

- `openapi.yaml` : description OpenAPI 3.0 de l'API (35 adresses, 41 routes). S'ouvre dans https://editor.swagger.io (Fichier > Importer).
- `api.html` : la même référence affichée avec Swagger UI (consultation seule).
- `diagrammes/*.mmd` : sources Mermaid du MCD et des diagrammes UML (processus, architecture, cas d'utilisation, classes, séquences, états) ; `*.svg` = rendu.
- Contrôle du site en ligne : `../deploiement/verifier-en-ligne.sh <nom-du-site>` (sur le serveur, en root, pour les contrôles complets).

Mettre à jour ces fichiers quand une route, une table ou une règle change.

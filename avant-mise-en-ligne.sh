#!/bin/bash
# À lancer avant chaque mise en ligne : tous les tests doivent passer.
cd "$(dirname "$0")" || exit 1
echo "1/2 Tests calculs, API, sécurité, plusieurs entreprises"
bash lancer_tests.sh > /tmp/erp_tests.log 2>&1 && grep -E "^Ran|^OK" /tmp/erp_tests.log || { tail -40 /tmp/erp_tests.log; echo "ÉCHEC : ne pas mettre en ligne."; exit 1; }
echo "2/2 Tests dans un vrai navigateur"
bash tests/e2e/lancer_tests_navigateur.sh || { echo "ÉCHEC : ne pas mettre en ligne."; exit 1; }
echo "Tout est vert : la mise en ligne peut se faire."

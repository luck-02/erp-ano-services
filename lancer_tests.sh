#!/bin/bash
# Lance tous les tests automatiques (calculs + API + sécurité).
cd "$(dirname "$0")" || exit 1
python3 tests/test_metier.py && python3 tests/test_api.py && python3 tests/test_multi.py && bash tests/test_deploiement.sh

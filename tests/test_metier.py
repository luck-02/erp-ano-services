"""Tests des règles de calcul (sans serveur). Lancer : python3 tests/test_metier.py"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app"))
import db  # noqa: E402
import metier as M  # noqa: E402

D = dt.date
CH = [{"libelle": l, "taux_pdm": t} for l, t in db.CHARGES_INITIALES]
P = {"visite_ht": 45000, "tva_pdm": 1800, "validite_visite_mois": 12}


class TestsMetier(unittest.TestCase):
    def test_coefficient_191(self):
        self.assertEqual(M.coefficient_pdm(CH), 19100)
        self.assertEqual(M.cout_mensuel(576300, CH), 1100733)

    def test_cas_de_reference(self):
        d = {"date_debut": D(2026, 11, 2), "date_fin": D(2027, 5, 1), "visite_mode": "Auto"}
        a = {"nom": "X", "poste": "p", "salaire_base": 576300, "derniere_visite": None}
        p = M.calcul_proforma(d, [a], CH, P)
        self.assertEqual(p["cumul_ht"], 6648214)
        self.assertEqual(len(M.lignes_factures_agent(d, a, CH, P)), 8)

    def test_proforma_reelle_2(self):
        # Proforma réelle 335 : 3 890 280 (Lola arrondit chaque mois) ; l'outil
        # arrondit une seule fois, comme pour le cas de référence -> 1 XAF d'écart, connu.
        d = {"date_debut": D(2026, 9, 14), "date_fin": D(2026, 12, 13)}
        p = M.calcul_proforma(d, [{"nom": "Y", "poste": "p", "salaire_base": 674220}], CH, P)
        self.assertEqual(p["cout_mensuel_total"], 1287760)
        self.assertEqual(p["cumul_ht"], 3890279)

    def test_prorata(self):
        self.assertEqual(M.mois_couverts(D(2027, 2, 10), D(2027, 3, 5)), [(D(2027, 2, 1), 19, 28), (D(2027, 3, 1), 5, 31)])
        self.assertEqual(M.mois_couverts(D(2028, 2, 1), D(2028, 2, 29)), [(D(2028, 2, 1), 29, 29)])

    def test_visites(self):
        self.assertEqual(len(M.dates_visites(D(2027, 1, 1), D(2028, 3, 31), None, "Auto")), 2)
        self.assertEqual(M.dates_visites(D(2027, 5, 2), D(2027, 11, 1), D(2026, 11, 2), "Auto"), [])
        self.assertEqual(M.dates_visites(D(2027, 5, 2), D(2028, 5, 1), D(2026, 11, 2), "Auto"), [D(2027, 11, 2)])
        self.assertEqual(M.dates_visites(D(2027, 1, 1), D(2029, 1, 1), None, "Non"), [])

    def test_numeros_et_echeance(self):
        self.assertEqual(M.numero_proforma(348, D(2026, 10, 30), "Dupont Mbïna"), "348-10-ANO-DUPONT MBINA/2026")
        self.assertEqual(M.numero_facture(153, "VISITE", D(2026, 11, 1)), "FA 153/11-Visite Médicale/2026")
        self.assertEqual(M.numero_bis("FA 152/08-MAD/2026"), "FA 152 bis/08-MAD/2026")
        # V1 B2B : codes réglables par entreprise
        self.assertEqual(M.numero_proforma(12, D(2027, 2, 3), "Fictif", "xyz"), "12-02-XYZ-FICTIF/2027")
        self.assertEqual(M.numero_facture(7, "MAD", D(2027, 2, 1), "FAC", "PREST", "VM"), "FAC 7/02-PREST/2027")
        self.assertEqual(M.numero_facture(8, "VISITE", D(2027, 2, 1), "", "PREST", "VM"), "8/02-VM/2027")
        self.assertEqual(M.echeance(D(2026, 12, 5), 30), D(2027, 1, 31))

    def test_arrondi(self):
        self.assertEqual(M.arrondi(2.5), 3)
        self.assertEqual(M.tva(1064042, 1800), 191528)


if __name__ == "__main__":
    unittest.main(verbosity=2)

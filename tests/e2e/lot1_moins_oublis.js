// Lot 1 « moins d'oublis » (25/11/2026), dans un vrai navigateur, données FICTIVES :
//   - la DA reçue (PDF) s'affiche à côté du formulaire et est jointe au dossier ;
//   - « Prochaine étape » en haut du dossier ;
//   - proforma imprimée -> dossier « Envoyé » tout seul ;
//   - BC conforme -> factures prévues créées tout de suite ;
//   - « À faire » : imputation à demander (avec lien vers le dossier), visites ;
//   - « Visite faite le… » retire l'alerte.
// Lancer : node tests/e2e/lot1_moins_oublis.js   (code 0 si tout passe)

const { chromium } = require('playwright');
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');

const RACINE = path.resolve(__dirname, '..', '..');
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'erp_lot1_'));
const MDP = 'Moanda-Bureau-2026!';
let echecs = 0, reussis = 0;

function verifier(cond, libelle, detail) {
  if (cond) { reussis++; console.log('  ok   ' + libelle); }
  else { echecs++; console.log('  ÉCHEC ' + libelle + (detail !== undefined ? ' -> ' + JSON.stringify(detail).slice(0, 300) : '')); }
}
function portLibre() {
  return new Promise((ok) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
}
async function lancerServeur(env) {
  const port = await portLibre();
  const p = spawn('python3', ['app/serveur.py'], { cwd: RACINE, env: { ...process.env, ...env, ANO_PORT: String(port) }, stdio: ['ignore', 'ignore', 'pipe'] });
  for (let i = 0; i < 100; i++) {
    try { const r = await fetch(`http://localhost:${port}/api/etat`); if (r.ok) break; } catch (e) { /* pas encore prêt */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  return { port, arreter: () => p.kill() };
}
// petit PDF valide d'une page (texte « DA fictive »)
function pdfFictif() {
  const objets = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    null,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  const flux = 'BT /F1 24 Tf 72 760 Td (DA fictive - test) Tj ET';
  objets[3] = `<< /Length ${flux.length} >>\nstream\n${flux}\nendstream`;
  let corps = '%PDF-1.4\n';
  const pos = [];
  objets.forEach((o, i) => { pos.push(corps.length); corps += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const xref = corps.length;
  corps += `xref\n0 ${objets.length + 1}\n0000000000 65535 f \n` + pos.map((p) => String(p).padStart(10, '0') + ' 00000 n \n').join('');
  corps += `trailer\n<< /Size ${objets.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`;
  return Buffer.from(corps, 'latin1');
}
const iso = (d) => d.toISOString().slice(0, 10);

(async () => {
  const donnees = fs.mkdtempSync(path.join(os.tmpdir(), 'erp_lot1_donnees_'));
  const prive = path.join(donnees, 'prive');
  fs.mkdirSync(prive);
  const srv = await lancerServeur({ ANO_DONNEES: donnees, ANO_PRIVE: prive, ANO_SOFFICE: path.join(donnees, 'sans-libreoffice') });
  const U = `http://localhost:${srv.port}`;
  const navigateur = await chromium.launch();
  const ctx = await navigateur.newContext({ viewport: { width: 1360, height: 900 } });
  const page = await ctx.newPage();
  const erreurs = [];
  page.on('pageerror', (e) => erreurs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 40[134]/.test(m.text())) erreurs.push(m.text()); });
  const pdf = path.join(OUT, 'DA fictive.pdf');
  fs.writeFileSync(pdf, pdfFictif());
  try {
    console.log('Lot 1 : moins d\'oublis');
    await page.goto(U + '/');
    await page.waitForSelector('#f-ins');
    await page.fill('#i-nom', 'Direction (test)'); await page.fill('#i-id', 'direction');
    await page.fill('#i-mdp', MDP); await page.fill('#i-mdp2', MDP);
    await page.click('#f-ins button[type=submit]');
    await page.waitForSelector('#f-cnx');
    await page.fill('#c-id', 'direction'); await page.fill('#c-mdp', MDP);
    await page.click('#f-cnx button');
    await page.waitForSelector('.kpi');

    // --- nouvelle DA, sans imputation, contrat qui commence aujourd'hui (visite due aujourd'hui)
    const auj = new Date();
    const fin = new Date(auj.getTime() + 120 * 86400000);
    await page.goto(U + '/#/nouvelle-da');
    await page.waitForSelector('#f-da');
    await page.setInputFiles('#da-fichier', pdf);
    await page.locator('#da-vue iframe').waitFor();
    verifier(await page.isVisible('#da-vue iframe'), 'DA en PDF affichée à côté du formulaire');
    await page.screenshot({ path: path.join(OUT, '1_saisie_da.png') });
    await page.fill('#da-service', 'DAF'); await page.fill('#da-lieu', 'Moanda');
    await page.fill('#da-d1', iso(auj)); await page.fill('#da-d2', iso(fin));
    await page.fill('input[data-c=nom]', 'FICTIF Lotun Alpha');
    await page.fill('input[data-c=poste]', 'Comptable');
    await page.fill('input[data-c=salaire_base]', '500000');
    await page.click('#f-da button[type=submit]');
    await page.locator('#ds-etape').waitFor();
    verifier((await page.textContent('#ds-etape')).includes('Imprimer la proforma'), 'prochaine étape d\'un brouillon : imprimer la proforma');
    await page.locator('#ds-docs table').waitFor();
    verifier((await page.textContent('#ds-docs')).includes('DA fictive.pdf'), 'la DA est jointe au dossier (pièce DA)');
    const did = Number(page.url().split('/').pop());

    // --- impression de la proforma -> « Envoyé »
    await page.click('#ds-etape-b');
    await page.waitForSelector('#imp');
    await page.evaluate(() => { window.print = () => {}; });
    await page.click('#imp');
    await page.locator('.toast', { hasText: 'Envoyé' }).first().waitFor();
    const d1 = await page.evaluate(async (id) => (await fetch('/api/dossiers/' + id)).json(), did);
    verifier(d1.dossier.statut === 'Envoyé' && !!d1.dossier.envoye_le, 'proforma imprimée : dossier « Envoyé » avec la date', d1.dossier.statut);

    // --- tableau de bord : imputation à demander, avec lien vers le dossier ; visite à organiser
    await page.goto(U + '/#/tableau');
    await page.waitForSelector('.a-faire');
    const af = await page.textContent('.a-faire');
    verifier(af.includes("sans n° d'imputation") && !!(await page.$(`.a-faire a[href="#/dossier/${did}"]`)), 'À faire : imputation à demander, lien direct vers le dossier', af);
    await page.screenshot({ path: path.join(OUT, '2_tableau_a_faire.png'), fullPage: true });

    // --- BC conforme -> factures préparées tout de suite
    await page.goto(U + '/#/dossier/' + did);
    await page.waitForSelector('#f-bc');
    verifier((await page.textContent('#ds-etape')).includes('bon de commande'), 'prochaine étape d\'une proforma envoyée : saisir le BC');
    const cumul = d1.proforma.cumul_ht;
    await page.fill('#bc-n', '900001'); await page.fill('#bc-m', String(cumul));
    await page.click('#f-bc button[type=submit]');
    await page.locator('.toast', { hasText: 'préparée' }).first().waitFor();
    const d2 = await page.evaluate(async (id) => (await fetch('/api/dossiers/' + id)).json(), did);
    verifier(d2.dossier.statut === 'En cours' && d2.factures.length > 0, 'BC conforme : factures prévues créées, dossier « En cours »', [d2.dossier.statut, d2.factures.length]);
    // le dossier se redessine après le BC : on attend le nouveau texte (locator, pas waitForFunction : CSP sans eval)
    const apresBC = await page.locator('#ds-etape', { hasText: /Émettre|Rien à faire/ }).waitFor({ timeout: 10000 }).then(() => true, () => false);
    verifier(apresBC, 'prochaine étape après le BC : émettre (ou rien à faire)', await page.textContent('#ds-etape').catch(() => ''));
    await page.screenshot({ path: path.join(OUT, '3_dossier_prochaine_etape.png') });

    // --- contrat en place : la visite due aujourd'hui apparaît dans « À faire » ; « Faite le… » la retire
    await page.goto(U + '/#/tableau');
    await page.waitForSelector('.a-faire');
    verifier((await page.textContent('.a-faire')).includes('visite(s) médicale(s)'), 'À faire : visite médicale à organiser');
    await page.click('[data-visite="0"]');
    await page.waitForSelector('#vf-f');
    await page.click('#vf-f button[type=submit]');
    await page.locator('.toast', { hasText: 'Visite notée' }).first().waitFor();
    const partie = await page.locator('[data-visite]').waitFor({ state: 'detached', timeout: 8000 }).then(() => true, () => false);
    const t2 = await page.evaluate(async () => (await fetch('/api/tableau-de-bord')).json());
    verifier(partie && t2.alertes_visite.length === 0, '« Faite le… » : l\'alerte de visite disparaît', t2.alertes_visite);


    // --- téléphone : pas de défilement horizontal sur la saisie et le dossier
    await page.setViewportSize({ width: 390, height: 844 });
    for (const h of ['#/dossier/' + did, '#/modifier-da/' + did, '#/tableau']) {
      await page.goto(U + '/' + h);
      await page.waitForTimeout(400);
      const deborde = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      verifier(deborde <= 1, 'téléphone, pas de défilement horizontal : ' + h, deborde);
    }
    await page.screenshot({ path: path.join(OUT, '4_tableau_telephone.png'), fullPage: true });
    verifier(!erreurs.length, 'aucune erreur JavaScript', erreurs);
  } catch (e) {
    echecs++;
    console.log('  ÉCHEC exception : ' + e.message);
    await page.screenshot({ path: path.join(OUT, 'echec.png') }).catch(() => {});
  } finally {
    await navigateur.close();
    srv.arreter();
  }
  console.log(`\n${reussis} vérification(s) réussie(s), ${echecs} échec(s). Captures : ${OUT}`);
  process.exit(echecs ? 1 : 0);
})();

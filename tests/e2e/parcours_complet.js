// Tests de bout en bout dans un vrai navigateur (Playwright + Chromium).
// Lance lui-même deux serveurs sur des bases temporaires (données FICTIVES) :
//   A. installation ANO sur un poste (parcours complet DA -> proforma -> BC -> factures -> PDF/Word/CSV)
//   B. version en ligne avec deux entreprises (connexion par code, isolation des données)
// et vérifie à chaque page : aucune erreur JavaScript, accessibilité de base, pas de
// défilement horizontal sur téléphone.
// Pas de page.waitForFunction : la CSP de l'appli interdit eval, on attend avec des locators.
// Lancer : ./tests/e2e/lancer_tests_navigateur.sh   (installe Playwright si besoin)
// Sortie : code 0 si tout passe, 1 sinon ; captures dans le dossier affiché à la fin.

const { chromium } = require('playwright');
const { spawn, execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const net = require('net');

const RACINE = path.resolve(__dirname, '..', '..');
const OUT = fs.mkdtempSync(path.join(os.tmpdir(), 'erp_e2e_'));
const MDP = 'Moanda-Bureau-2026!';
let echecs = 0, reussis = 0;

function verifier(cond, libelle, detail) {
  if (cond) { reussis++; console.log('  ok   ' + libelle); }
  else { echecs++; console.log('  ÉCHEC ' + libelle + (detail !== undefined ? ' -> ' + JSON.stringify(detail).slice(0, 300) : '')); }
}

function portLibre() {
  return new Promise((ok) => { const s = net.createServer(); s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => ok(p)); }); });
}

async function lancerServeur(env, script = 'app/serveur.py') {
  const port = await portLibre();
  const p = spawn('python3', [script], { cwd: RACINE, env: { ...process.env, ...env, ANO_PORT: String(port) }, stdio: ['ignore', 'ignore', 'pipe'] });
  let journal = '';
  p.stderr.on('data', (d) => { journal += d; });
  for (let i = 0; i < 100; i++) {
    try { const r = await fetch(`http://localhost:${port}/api/etat`); if (r.ok) break; } catch (e) { /* pas encore prêt */ }
    await new Promise((r) => setTimeout(r, 100));
  }
  return { port, arreter: () => p.kill(), journal: () => journal };
}

// Accessibilité de base (pas un audit complet) : langue, libellés, textes alternatifs, boutons nommés
async function controleAccessibilite(page, nom) {
  const pb = await page.evaluate(() => {
    const p = [];
    if (!document.documentElement.lang) p.push('html sans lang');
    document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([hidden]), select, textarea').forEach((el) => {
      const lab = (el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest('label') || el.getAttribute('aria-label') || el.getAttribute('title');
      if (!lab && el.offsetParent !== null) p.push('champ sans libellé : ' + (el.id || el.outerHTML.slice(0, 60)));
    });
    document.querySelectorAll('img').forEach((im) => { if (!im.hasAttribute('alt')) p.push('image sans alt : ' + im.src.slice(-30)); });
    document.querySelectorAll('button').forEach((b) => { if (!b.textContent.trim() && !b.getAttribute('aria-label') && !b.title) p.push('bouton sans nom'); });
    return p;
  });
  verifier(pb.length === 0, 'accessibilité de base : ' + nom, pb);
}

async function pasDeDefilementHorizontal(page, nom) {
  const ok = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
  verifier(ok, 'téléphone, pas de défilement horizontal : ' + nom);
}

async function telechargement(page, declencheur) {
  const [dl] = await Promise.all([page.waitForEvent('download'), declencheur()]);
  const chemin = path.join(OUT, dl.suggestedFilename());
  await dl.saveAs(chemin);
  return { nom: dl.suggestedFilename(), contenu: fs.readFileSync(chemin) };
}

function suivreErreurs(page, erreurs) {
  page.on('pageerror', (e) => erreurs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 40[134]/.test(m.text())) erreurs.push(m.text()); });
}

// ---------------------------------------------------------------------------
async function scenarioANO(navigateur) {
  console.log('\nA. Installation ANO sur un poste : parcours complet');
  const donnees = fs.mkdtempSync(path.join(os.tmpdir(), 'erp_e2e_ano_'));
  const prive = path.join(donnees, 'prive-test');
  fs.mkdirSync(prive);
  fs.copyFileSync(path.join(RACINE, 'app', 'static', 'logo.png'), path.join(prive, 'signature.png'));   // cachet fictif
  const srv = await lancerServeur({ ANO_DONNEES: donnees, ANO_PRIVE: prive, ANO_SOFFICE: path.join(donnees, 'sans-libreoffice') });
  const U = `http://localhost:${srv.port}`;
  const ctx = await navigateur.newContext({ viewport: { width: 1360, height: 900 }, acceptDownloads: true });
  await ctx.addInitScript(() => { delete window.showSaveFilePicker; });   // téléchargement classique
  const page = await ctx.newPage();
  const erreurs = [];
  suivreErreurs(page, erreurs);
  try {
    await page.goto(U + '/');
    await page.waitForSelector('#f-ins');
    await controleAccessibilite(page, 'installation');
    await page.fill('#i-nom', 'Direction (test)'); await page.fill('#i-id', 'direction');
    await page.fill('#i-mdp', MDP); await page.fill('#i-mdp2', MDP);
    await page.click('#f-ins button[type=submit]');
    await page.waitForSelector('#f-cnx');
    verifier(!(await page.$('#c-ent')), 'un seul établissement : pas de champ « code entreprise »');
    await page.fill('#c-id', 'direction'); await page.fill('#c-mdp', MDP);
    await page.click('#f-cnx button');
    await page.waitForSelector('.kpi');
    await controleAccessibilite(page, 'tableau de bord');
    verifier((await page.textContent('.marque')).includes('ANO Services'), 'menu au nom de l\'entreprise');

    await page.goto(U + '/#/parametres');
    await page.waitForSelector('#p-exemples');
    await controleAccessibilite(page, 'paramètres');
    verifier((await page.textContent('#p-exemples')).includes('-ANO-NOM/'), 'exemple de n° de proforma affiché');

    await page.goto(U + '/#/nouvelle-da');
    await page.waitForSelector('#f-da');
    await controleAccessibilite(page, 'nouvelle DA');
    // v3.5.0 : champs obligatoires marqués, aides au survol, rien ne déborde des cartes sur ordinateur
    verifier(await page.$('label[for=da-d1] .requis') && await page.$('label[for=da-service] .requis') && !(await page.$('label[for=da-imp] .requis')),
      'champs obligatoires marqués d\'un astérisque (et seulement eux)');
    await page.hover('label[for=da-imp] .info');
    verifier(await page.isVisible('label[for=da-imp] .bulle'), 'aide affichée au survol de l\'icône');
    verifier(!(await page.$('#f-da .aide')), 'plus de texte d\'aide sous les champs du formulaire DA');
    for (const largeur of [1360, 1100, 1024]) {
      await page.setViewportSize({ width: largeur, height: 900 });
      const debord = await page.$$eval('#f-da .carte', (cs) => cs.filter((c) => c.scrollWidth > c.clientWidth + 1).map((c) => c.querySelector('h2').textContent));
      verifier(debord.length === 0, 'ordinateur ' + largeur + ' px : rien ne déborde (période comprise)', debord);
    }
    await page.setViewportSize({ width: 1360, height: 900 });
    await page.fill('#da-service', 'DAF'); await page.fill('#da-lieu', 'Moanda');
    await page.fill('#da-d1', '2026-11-02'); await page.fill('#da-d2', '2027-05-01'); await page.fill('#da-dp', '2026-10-30');
    await page.fill('input[data-c=nom]', 'AGENT FICTIF Elise');
    await page.fill('input[data-c=poste]', 'Comptable fournisseurs');
    await page.fill('input[data-c=salaire_base]', '576300');
    await page.fill('#da-nom', 'AGENT FICTIF');
    await page.locator('#apercu', { hasText: /6.648.214/ }).waitFor({ timeout: 5000 });
    const apercu = await page.textContent('#apercu');
    verifier(/6.648.214/.test(apercu), 'cas de référence : cumul HT 6 648 214');
    verifier(/349-10-ANO-AGENT FICTIF\/2026/.test(apercu), 'n° de proforma 349-10-ANO-…/2026', apercu.match(/\d+-\d+-[A-Z]+-[^/]+\/\d+/)?.[0]);
    await page.click('#f-da button[type=submit]');
    await page.waitForSelector('#f-bc');
    await page.fill('#bc-n', '493930'); await page.fill('#bc-m', '6648214');
    await page.click('#f-bc button[type=submit]');
    await page.waitForTimeout(700);
    await page.click('#ds-gen');
    await page.waitForSelector('#t-fact');
    const nb = await page.$$eval('#t-fact tbody tr', (r) => r.length);
    verifier(nb === 8, '8 factures prévues (7 mois + 1 visite médicale)', nb);
    // tout sélectionner puis tout désélectionner
    await page.check('#f-tout');
    verifier((await page.textContent('#f-nb')).startsWith('8'), 'tout sélectionner : 8 factures');
    await page.click('#f-aucune');
    verifier((await page.textContent('#f-nb')).startsWith('0') && (await page.$$('.f-sel:checked')).length === 0, 'bouton « Tout désélectionner »');
    // modifier une facture prévue : unité changée
    await page.click('#t-fact tbody tr:nth-child(2) [data-modif]');
    await page.waitForSelector('#f-mf');
    await controleAccessibilite(page, 'modifier une facture');
    await page.fill('#mf-u', 'Jours ouvrés');
    await page.click('#f-mf button[type=submit]');
    await page.waitForSelector('#f-mf', { state: 'detached' });
    await page.waitForTimeout(800);   // la liste se recharge
    verifier(true, 'facture modifiable depuis le tableau');

    // proforma : cumul HT seul, sans TVA/TTC, sans n° de DA
    await page.goto(U + '/#/imprimer/proforma/1');
    await page.waitForSelector('.doc');
    const pf = await page.textContent('.doc');
    verifier(!/TTC/.test(pf), 'proforma sans TTC');
    verifier(!/DA-20\d\d-/.test(pf), 'proforma sans n° de DA interne');
    await page.pdf({ path: path.join(OUT, 'proforma.pdf'), format: 'A4', printBackground: true });
    const pages = (fs.readFileSync(path.join(OUT, 'proforma.pdf')).toString('latin1').match(/\/Type\s*\/Page[^s]/g) || []).length;
    verifier(pages === 1, 'proforma PDF sur 1 page', pages);

    // émission de décembre + documents imprimés
    await page.goto(U + '/#/factures');
    await page.waitForSelector('#fa-m');
    await page.fill('#fa-m', '2026-12'); await page.dispatchEvent('#fa-m', 'change');
    await page.waitForTimeout(500);
    await page.click('#fa-mois');
    await page.fill('#e-d', '2026-12-05');
    await page.click('#f-em button[type=submit]');
    await page.waitForSelector('.doc');
    const docs = await page.$$eval('.doc', (d) => d.map((x) => x.textContent));
    verifier(docs.length >= 1, 'factures de décembre imprimables', docs.length);
    verifier(docs.every((t) => /TVA \(18/.test(t)), '« TVA (18 %) » sur chaque facture');
    verifier(docs.every((t) => !/IMP-|DA-20\d\d-|CLI00|Modalité/.test(t)), 'factures sans imputation, n° de DA, code client ni modalité');
    verifier(docs.every((t) => !/576.300/.test(t)), 'aucun salaire de base sur les factures');
    verifier((await page.$$('.doc img.sig-img')).length === docs.length, 'cachet sur chaque facture');
    await page.pdf({ path: path.join(OUT, 'factures.pdf'), format: 'A4', printBackground: true });

    // Word (.docx) depuis la page d'impression
    const w = await telechargement(page, () => page.click('#imp-word'));
    verifier(/\.(docx|zip)$/.test(w.nom) && w.contenu.slice(0, 2).toString() === 'PK', 'export Word téléchargé (' + w.nom + ')');
    verifier(w.nom.startsWith('COMILOG'), 'nom du fichier Word commence par le client', w.nom);

    // CSV pour Excel
    await page.goto(U + '/#/factures');
    await page.waitForSelector('#fa-csv');
    await controleAccessibilite(page, 'factures');
    const c = await telechargement(page, () => page.click('#fa-csv'));
    const csv = c.contenu.toString('utf8');
    verifier(csv.charCodeAt(0) === 0xfeff && csv.includes('N° facture;'), 'export CSV lisible par Excel');
    verifier(!csv.includes('576300'), 'CSV sans salaire');

    // Documents du dossier : copies des factures émises + pièce du client
    await page.goto(U + '/#/dossiers');
    await page.waitForSelector('table');
    verifier(/576.300/.test(await page.textContent('table')), 'salaire de base visible dans la liste des dossiers');
    await page.goto(U + '/#/dossier/1');
    await page.waitForSelector('#ds-docs table');
    const lignes = await page.$$eval('#ds-docs tbody tr', (t) => t.map((x) => x.textContent));
    verifier(lignes.length >= 1 && lignes.every((t) => /Facture FA /.test(t)), 'copie de chaque facture émise gardée dans le dossier', lignes.length);
    const pdfFictif = path.join(OUT, 'BC fictif.pdf');
    fs.writeFileSync(pdfFictif, '%PDF-1.4\n% BC fictif pour les tests\n%%EOF\n');
    await page.selectOption('#pc-cat', 'BC');
    await page.setInputFiles('#pc-f', pdfFictif);
    await page.click('#pc-ok');
    await page.locator('#ds-docs', { hasText: 'BC fictif.pdf' }).waitFor();
    verifier(true, 'pièce du client ajoutée (BC en PDF)');
    await controleAccessibilite(page, 'documents du dossier');
    const bouton = await page.$('#ds-docs tbody tr:first-child [data-doc-tel]');
    const p = await telechargement(page, () => bouton.click());
    verifier(p.nom === 'BC fictif.pdf' && p.contenu.toString().startsWith('%PDF-'), 'pièce téléchargée telle quelle', p.nom);
    const faux = path.join(OUT, 'page.html');
    fs.writeFileSync(faux, '<html>pas une pièce</html>');
    await page.setInputFiles('#pc-f', faux);
    await page.click('#pc-ok');
    await page.waitForSelector('.toast.err');
    verifier(/PDF, PNG ou JPEG/.test(await page.textContent('.toast.err')), 'fichier HTML refusé');

    // téléphone
    await page.setViewportSize({ width: 390, height: 844 });
    for (const [h, sel] of [['#/tableau', '.kpi'], ['#/factures', '#fa-m'], ['#/dossiers', 'table'], ['#/dossier/1', '#ds-docs table']]) {
      await page.goto(U + '/' + h); await page.waitForSelector(sel);
      await pasDeDefilementHorizontal(page, h);
    }
    await page.screenshot({ path: path.join(OUT, 'ano-telephone.png'), fullPage: true });
    verifier(erreurs.length === 0, 'aucune erreur JavaScript (ANO)', erreurs);
  } finally {
    await ctx.close(); srv.arreter();
  }
}

// ---------------------------------------------------------------------------
async function connexionPremiereFois(page, U, code, ident, provisoire, nouveau) {
  await page.goto(U + '/');
  await page.waitForSelector('#f-cnx');
  await page.fill('#c-ent', code); await page.fill('#c-id', ident); await page.fill('#c-mdp', provisoire);
  await page.click('#f-cnx button');
  await page.waitForSelector('#f-mdp');
  await page.fill('#m-a', provisoire); await page.fill('#m-n', nouveau); await page.fill('#m-n2', nouveau);
  await page.click('#f-mdp button[type=submit]');
  await page.waitForSelector('.kpi');
}

async function scenarioMulti(navigateur) {
  console.log('\nB. Version en ligne : deux entreprises, isolation des données');
  const donnees = fs.mkdtempSync(path.join(os.tmpdir(), 'erp_e2e_multi_'));
  const env = { ANO_DONNEES: donnees, ANO_EN_LIGNE: '1' };
  execFileSync('python3', ['-c', `
import sys; sys.path.insert(0, 'app'); import plateforme as P
r = P.Registre(${JSON.stringify(donnees)}); r.initialiser(en_ligne=True)
r.creer('alpha', 'Alpha Interim (fictif)', 'direction', 'Provisoire-Alpha-1')
r.creer('beta', 'Beta Services (fictif)', 'direction', 'Provisoire-Beta-22')`], { cwd: RACINE, env: { ...process.env, ...env } });
  const srv = await lancerServeur(env);
  const U = `http://localhost:${srv.port}`;
  const erreurs = [];
  const ctxA = await navigateur.newContext({ viewport: { width: 1360, height: 900 } });
  const ctxB = await navigateur.newContext({ viewport: { width: 1360, height: 900 } });
  try {
    const a = await ctxA.newPage(); suivreErreurs(a, erreurs);
    await a.goto(U + '/');
    await a.waitForSelector('#f-cnx');
    verifier(!!(await a.$('#c-ent')), 'connexion en ligne : champ « code entreprise »');
    await controleAccessibilite(a, 'connexion en ligne');
    // mauvais code : même message qu'un mauvais mot de passe
    await a.fill('#c-ent', 'inconnue'); await a.fill('#c-id', 'direction'); await a.fill('#c-mdp', 'Provisoire-Alpha-1');
    await a.click('#f-cnx button');
    await a.locator('#c-err', { hasText: /\S/ }).waitFor();
    const msg1 = await a.textContent('#c-err');
    await a.fill('#c-ent', 'alpha'); await a.fill('#c-mdp', 'Mauvais-mot-de-passe');
    await a.click('#f-cnx button');
    await a.waitForTimeout(800);
    verifier(msg1 === (await a.textContent('#c-err')), 'code inconnu et mauvais mot de passe : même message', msg1);

    await connexionPremiereFois(a, U, 'alpha', 'direction', 'Provisoire-Alpha-1', 'Alpha-Interim-2027!');
    verifier((await a.textContent('.marque')).includes('Alpha'), 'Alpha voit son propre nom');
    await a.goto(U + '/#/clients'); await a.waitForSelector('#cl-plus');
    await a.click('#cl-plus'); await a.waitForSelector('#f-cl');
    await a.fill('#cl-nom', 'CLIENT SECRET ALPHA'); await a.click('#f-cl button[type=submit]');
    await a.waitForTimeout(600);
    await a.goto(U + '/#/nouvelle-da'); await a.waitForSelector('#f-da');
    await a.fill('#da-service', 'Achats'); await a.fill('#da-lieu', 'Libreville');
    await a.fill('#da-d1', '2026-12-01'); await a.fill('#da-d2', '2027-02-28'); await a.fill('#da-dp', '2026-11-20');
    await a.fill('input[data-c=nom]', 'AGENT SECRET ALPHA'); await a.fill('input[data-c=poste]', 'Assistant');
    await a.fill('input[data-c=salaire_base]', '400000'); await a.fill('#da-nom', 'SECRET');
    await a.locator('#apercu', { hasText: /ALPHA-SECRET/ }).waitFor({ timeout: 5000 });
    await a.click('#f-da button[type=submit]');
    await a.waitForSelector('#f-bc');
    verifier(/1-11-ALPHA-SECRET\/2026/.test(await a.textContent('body')), 'n° de proforma propre à Alpha (1-11-ALPHA-…)');

    const b = await ctxB.newPage(); suivreErreurs(b, erreurs);
    await connexionPremiereFois(b, U, 'beta', 'direction', 'Provisoire-Beta-22', 'Beta-Services-2027!');
    const vus = [];
    for (const [h, sel] of [['#/tableau', '.kpi'], ['#/dossiers', '.entete'], ['#/factures', '#fa-m'], ['#/clients', '#cl-plus'], ['#/interimaires', '.entete'], ['#/journal', '.entete']]) {
      await b.goto(U + '/' + h); await b.waitForSelector(sel); await b.waitForTimeout(300);
      if (/SECRET|ALPHA/i.test(await b.textContent('#app'))) vus.push(h);
    }
    verifier(vus.length === 0, 'Beta ne voit rien d\'Alpha (tableau, dossiers, factures, clients, intérimaires, journal)', vus);
    await b.goto(U + '/#/dossier/1'); await b.waitForTimeout(800);
    verifier(!/SECRET/.test(await b.textContent('#app')), 'Beta ne peut pas ouvrir le dossier n° 1 d\'Alpha');
    const brut = await b.evaluate(async () => (await fetch('/api/dossiers/1')).status);
    verifier(brut === 404, 'API : dossier d\'Alpha introuvable pour Beta', brut);
    // compte « Lecture » : une page qui ne lui est pas ouverte renvoie au tableau de bord
    const cree = await b.evaluate(() => api('POST', '/api/utilisateurs', { identifiant: 'lecteur', nom: 'Lecteur fictif', role: 'lecture', mot_de_passe: 'Lecture-Provisoire-9' }).then(() => true, (e) => e.message));
    verifier(cree === true, 'compte Lecture créé', cree);
    const ctxL = await navigateur.newContext({ viewport: { width: 1360, height: 900 } });
    const l = await ctxL.newPage(); suivreErreurs(l, erreurs);
    await connexionPremiereFois(l, U, 'beta', 'lecteur', 'Lecture-Provisoire-9', 'Lecture-Beta-2027!x');
    await l.goto(U + '/#/dossiers'); await l.waitForSelector('.kpi');
    verifier(/#\/tableau$/.test(l.url()) && !(await l.$('.bandeau.danger')), 'Lecture sur #/dossiers : renvoyé au tableau de bord', l.url());
    await ctxL.close();
    const params = await b.evaluate(async () => (await (await fetch('/api/parametres')).json()).parametres);
    verifier(params.nif === '' && params.code_entreprise === 'BETA', 'Beta démarre vierge (sans les données d\'ANO)');
    await b.screenshot({ path: path.join(OUT, 'beta-tableau.png'), fullPage: true });
    verifier(erreurs.length === 0, 'aucune erreur JavaScript (en ligne)', erreurs);
  } finally {
    await ctxA.close(); await ctxB.close(); srv.arreter();
  }
}

(async () => {
  const navigateur = await chromium.launch();
  try {
    await scenarioANO(navigateur);
    await scenarioMulti(navigateur);
  } catch (e) {
    echecs++; console.log('  ÉCHEC inattendu : ' + e.message);
  } finally {
    await navigateur.close();
  }
  console.log(`\n${reussis} vérification(s) réussie(s), ${echecs} échec(s). Captures et fichiers : ${OUT}`);
  process.exit(echecs ? 1 : 0);
})();

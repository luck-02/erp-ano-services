// Vérifications EN LIGNE du site de test dans un vrai navigateur (Playwright + Chromium),
// sur l'entreprise « verif » remplie avec le jeu de données fictives. Lancé par GitHub
// après chaque mise à jour du site de test.
//   SITE=https://dev.exemple.com MDP_VERIF=... node tests/e2e/en_ligne_dev.js
// Captures d'écran dans CAPTURES (par défaut un dossier temporaire affiché à la fin).
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const SITE = process.env.SITE.replace(/\/$/, '');
const MDP = process.env.MDP_VERIF;
const OUT = process.env.CAPTURES || fs.mkdtempSync(path.join(os.tmpdir(), 'erp_dev_'));
fs.mkdirSync(OUT, { recursive: true });
let reussis = 0, echecs = 0;

function verifier(cond, libelle, detail) {
  if (cond) { reussis++; console.log('  ok    ' + libelle); }
  else { echecs++; console.log('  ÉCHEC ' + libelle + (detail !== undefined ? ' -> ' + JSON.stringify(detail).slice(0, 300) : '')); }
}

function suivreErreurs(page, erreurs) {
  page.on('pageerror', (e) => erreurs.push('pageerror: ' + e.message));
  page.on('console', (m) => { if (m.type() === 'error' && !/status of 40[134]|Cross-Origin-Opener-Policy/.test(m.text())) erreurs.push(m.text()); });
}

async function accessibilite(page) {
  return page.evaluate(() => {
    const p = [];
    if (!document.documentElement.lang) p.push('html sans lang');
    document.querySelectorAll('input:not([type=hidden]):not([type=checkbox]):not([hidden]), select, textarea').forEach((el) => {
      const lab = (el.id && document.querySelector(`label[for="${el.id}"]`)) || el.closest('label') || el.getAttribute('aria-label') || el.getAttribute('title');
      if (!lab && el.offsetParent !== null) p.push('champ sans libellé : ' + (el.id || el.outerHTML.slice(0, 60)));
    });
    document.querySelectorAll('img').forEach((im) => { if (!im.hasAttribute('alt')) p.push('image sans alt'); });
    document.querySelectorAll('button').forEach((b) => { if (!b.textContent.trim() && !b.getAttribute('aria-label') && !b.title) p.push('bouton sans nom'); });
    return p;
  });
}

async function connexion(page) {
  await page.goto(SITE + '/');
  await page.waitForSelector('#f-cnx');
  await page.fill('#c-ent', 'verif'); await page.fill('#c-id', 'direction'); await page.fill('#c-mdp', MDP);
  await page.click('#f-cnx button');
  await page.waitForSelector('.kpi');
}

const PAGES = [['#/tableau', '.kpi'], ['#/dossiers', 'table'], ['#/dossier/2', '#ds-docs table'], ['#/dossier/4', '#ds-docs table'],
  ['#/factures', '#fa-m'], ['#/nouvelle-da', '#f-da'], ['#/clients', '#cl-plus'], ['#/interimaires', '.entete'],
  ['#/journal', '.entete'], ['#/parametres', 'form'], ['#/utilisateurs', '.entete'], ['#/recherche/ndong', '.r-table']];

(async () => {
  const navigateur = await chromium.launch(process.env.CHROMIUM_ARGS ? { args: [process.env.CHROMIUM_ARGS] } : {});
  const erreurs = [];
  try {
    console.log('\n1. Ordinateur (1360 px)');
    const ctx = await navigateur.newContext({ viewport: { width: 1360, height: 900 }, acceptDownloads: true, locale: 'fr-FR' });
    const page = await ctx.newPage(); suivreErreurs(page, erreurs);
    await connexion(page);
    verifier(/verif|Vérification|ESSAI INTÉRIM/i.test(await page.textContent('.marque')), 'connecté à l\'entreprise de vérification');
    await page.waitForTimeout(500);
    verifier(/À vérifier/.test(await page.textContent('#app')), 'tableau de bord : paiement supérieur à la facture signalé');
    await page.screenshot({ path: path.join(OUT, '01-tableau-de-bord.png'), fullPage: true });
    const pbA = {};
    let n = 2;
    for (const [h, sel] of PAGES) {
      await page.goto(SITE + '/' + h); await page.waitForSelector(sel); await page.waitForTimeout(400);
      const pb = await accessibilite(page);
      if (pb.length) pbA[h] = pb;
      const debord = await page.$$eval('.carte', (cs) => cs.filter((c) => c.scrollWidth > c.clientWidth + 1).length);
      if (debord) pbA[h] = (pbA[h] || []).concat(['carte qui déborde']);
      await page.screenshot({ path: path.join(OUT, String(n++).padStart(2, '0') + '-' + h.replace(/[#/]+/g, '-').replace(/^-/, '') + '.png'), fullPage: true });
    }
    verifier(Object.keys(pbA).length === 0, PAGES.length + ' pages ouvertes : libellés, boutons nommés, rien ne déborde', pbA);
    // toutes largeurs (= tous niveaux de zoom) : la page ne défile jamais de côté
    const larges = [];
    for (const w of [1600, 1440, 1280, 1170, 1024, 900, 768, 600]) {
      await page.setViewportSize({ width: w, height: 900 });
      for (const [h2, sel] of PAGES) {
        await page.goto(SITE + '/' + h2); await page.waitForSelector(sel); await page.waitForTimeout(250);
        if (!(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1))) larges.push(w + ' ' + h2);
      }
    }
    await page.setViewportSize({ width: 1360, height: 900 });
    verifier(larges.length === 0, 'de 1600 à 600 px (zoom compris) : aucune page ne défile de côté', larges);

    await page.goto(SITE + '/#/dossiers'); await page.waitForSelector('table');
    const liste = await page.textContent('table');
    verifier(/650.000/.test(liste) && /NDONG/.test(liste), 'liste des dossiers : noms et salaire de base visibles');

    // proforma du groupe de 9
    await page.goto(SITE + '/#/imprimer/proforma/2'); await page.waitForSelector('.doc');
    const pf = await page.textContent('.doc');
    verifier(/NDONG_MBOUMBA_OBAME_MOUSSAVOU_NZIENGUI_BOUSSOUGOU_KOUMBA_MAKAYA_IVANGA/.test(pf), 'proforma : ligne des 9 noms');
    verifier(/33.925.500/.test(pf) && !/TTC/.test(pf), 'proforma : cumul HT 33 925 500, sans TTC');
    const pdfPf = path.join(OUT, 'proforma-groupe.pdf');
    await page.pdf({ path: pdfPf, format: 'A4', printBackground: true });
    const pagesPf = (fs.readFileSync(pdfPf).toString('latin1').match(/\/Type\s*\/Page[^s]/g) || []).length;
    verifier(pagesPf === 1, 'proforma du groupe en PDF sur 1 page', pagesPf);

    // factures du groupe
    const ids = await page.evaluate(async () => (await (await fetch('/api/factures?dossier=2')).json()).factures.filter((f) => f.numero).map((f) => f.id));
    await page.goto(SITE + '/#/imprimer/factures/' + ids.join(',')); await page.waitForSelector('.doc');
    const docs = await page.$$eval('.doc', (d) => d.map((x) => x.textContent));
    verifier(docs.length === ids.length && ids.length === 4, 'factures du groupe imprimables (visites + 3 mois)', [docs.length, ids.length]);
    verifier(docs.filter((t) => /MAD de 9 IDE/.test(t)).length === 3, '« MAD de 9 IDE » sur chaque facture mensuelle');
    verifier(docs.every((t) => !/650.000|IMP-|DA-20\d\d-|CLI00/.test(t)), 'factures sans salaire, imputation, n° de DA ni code client');
    verifier(docs.filter((t) => /TVA \(18/.test(t)).length >= 3, '« TVA (18 %) » sur les factures mensuelles');
    await page.pdf({ path: path.join(OUT, 'factures-groupe.pdf'), format: 'A4', printBackground: true });
    const [dl] = await Promise.all([page.waitForEvent('download'), page.click('#imp-word')]);
    const w = path.join(OUT, dl.suggestedFilename()); await dl.saveAs(w);
    verifier(fs.readFileSync(w).slice(0, 2).toString() === 'PK', 'export Word des factures du groupe (' + dl.suggestedFilename() + ')');

    // recherche globale : touche « / », plusieurs mots, filtres
    await page.goto(SITE + '/#/tableau'); await page.waitForSelector('.kpi');
    await page.keyboard.press('/'); await page.keyboard.type('nguema septembre'); await page.keyboard.press('Enter');
    await page.waitForSelector('.r-table'); await page.waitForTimeout(400);
    const rt = await page.textContent('#r-res');
    verifier(/FA 59\/09\/2026/.test(rt) && /FA 59 bis\/09\/2026/.test(rt), 'recherche « nguema septembre » (touche /) : facture et « bis » trouvées');
    await page.fill('#r-q', ''); await page.click('#r-plus summary'); await page.selectOption('#r-statut', 'En retard');
    await page.locator('.r-total', { hasText: '1 résultat' }).waitFor();
    verifier(/FA 51\/09\/2026/.test(await page.textContent('#r-res')), 'filtre « En retard » : la facture en retard seule');
    await page.click('#r-raz');
    await page.fill('#r-q', 'DA fictive'); await page.selectOption('#r-type', 'document');
    await page.waitForSelector('[data-r-doc]');
    const [dd] = await Promise.all([page.waitForEvent('download'), page.click('[data-r-doc]')]);
    const pd = path.join(OUT, dd.suggestedFilename()); await dd.saveAs(pd);
    verifier(fs.readFileSync(pd).slice(0, 5).toString() === '%PDF-', 'document trouvé et téléchargé depuis la recherche (' + dd.suggestedFilename() + ')');
    await page.selectOption('#r-type', '');
    await page.screenshot({ path: path.join(OUT, '15-recherche.png'), fullPage: true });

    // facture « bis » et facture corrigée
    await page.goto(SITE + '/#/dossier/4'); await page.waitForSelector('#ds-docs table'); await page.waitForTimeout(400);
    const d4 = await page.textContent('#app');
    verifier(/bis/.test(d4) && /Remplacée/.test(d4), 'dossier 4 : facture « bis » et facture remplacée visibles');

    // en-têtes de sécurité et cookie
    const h = await page.evaluate(async () => { const r = await fetch('/'); return { 'content-security-policy': r.headers.get('content-security-policy'), 'strict-transport-security': r.headers.get('strict-transport-security') }; });
    verifier(/default-src 'self'/.test(h['content-security-policy'] || '') && /max-age/.test(h['strict-transport-security'] || '') || !SITE.startsWith('https'),
      'en-têtes de sécurité (CSP, HTTPS strict)', [h['content-security-policy'], h['strict-transport-security']]);
    const ck = (await ctx.cookies()).find((c) => /session|erp/i.test(c.name));
    verifier(ck && ck.httpOnly && ck.sameSite !== 'None' && (ck.secure || !SITE.startsWith('https')), 'cookie de session HttpOnly, SameSite, Secure', ck && { httpOnly: ck.httpOnly, sameSite: ck.sameSite, secure: ck.secure });
    await ctx.close();

    console.log('\n2. Téléphone (390 px)');
    const mob = await navigateur.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 2, locale: 'fr-FR' });
    const m = await mob.newPage(); suivreErreurs(m, erreurs);
    await connexion(m);
    const defile = [];
    for (const [h2, sel] of PAGES.concat([['#/imprimer/proforma/2', '.doc']])) {
      await m.goto(SITE + '/' + h2); await m.waitForSelector(sel); await m.waitForTimeout(400);
      if (!(await m.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)) && !h2.includes('imprimer')) defile.push(h2);
    }
    await m.goto(SITE + '/#/tableau'); await m.waitForSelector('.kpi');
    await m.screenshot({ path: path.join(OUT, '20-telephone-tableau.png'), fullPage: true });
    await m.goto(SITE + '/#/factures'); await m.waitForSelector('#fa-m'); await m.waitForTimeout(400);
    await m.screenshot({ path: path.join(OUT, '21-telephone-factures.png'), fullPage: true });
    verifier(defile.length === 0, 'téléphone : aucune page ne défile de côté', defile);
    await mob.close();

    verifier(erreurs.length === 0, 'aucune erreur JavaScript', erreurs.slice(0, 5));
  } catch (e) {
    verifier(false, 'parcours interrompu : ' + e.message.split('\n')[0]);
  } finally {
    await navigateur.close();
  }
  console.log('\n' + reussis + ' contrôle(s) réussi(s), ' + echecs + ' échec(s). Captures : ' + OUT);
  process.exit(echecs ? 1 : 0);
})();

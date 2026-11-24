// Test du parcours complet dans un vrai navigateur (Playwright). Pour développeurs :
// lancer le serveur sur une base vide (ANO_DONNEES=/tmp/x python3 app/serveur.py), puis node tests/parcours_navigateur.js

const { chromium } = require('playwright');
const OUT = require('os').tmpdir() + '/';
(async () => {
  const b = await chromium.launch();
  const page = await b.newPage({ viewport: { width: 1360, height: 900 } });
  const errs = [];
  page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errs.push(m.type() + ': ' + m.text()); });
  page.on('pageerror', e => errs.push('pageerror: ' + e.message));
  const shot = async (n) => page.screenshot({ path: OUT + n + '.png', fullPage: true });
  await page.goto('http://localhost:8765/');
  await page.waitForSelector('#f-ins');
  await shot('01-installation');
  await page.fill('#i-nom', 'Luc (test)'); await page.fill('#i-id', 'luc');
  await page.fill('#i-mdp', 'Moanda-Bureau-2026!'); await page.fill('#i-mdp2', 'Moanda-Bureau-2026!');
  await page.click('#f-ins button[type=submit]');
  await page.waitForSelector('#f-cnx');
  await page.fill('#c-id', 'luc'); await page.fill('#c-mdp', 'Moanda-Bureau-2026!');
  await page.click('#f-cnx button');
  await page.waitForSelector('.kpi');
  await shot('02-tableau-vide');
  // paramètres : dernier n° facture
  await page.click('a[href="#/parametres"]');
  await page.waitForSelector('#p-dernier_num_facture');
  await page.fill('#p-dernier_num_facture', '152');
  await page.click('#f-par button[type=submit]');
  await page.waitForTimeout(500);
  await shot('03-parametres');
  // nouvelle DA
  await page.click('a[href="#/nouvelle-da"]');
  await page.waitForSelector('#f-da');
  await page.fill('#da-service', 'DAF'); await page.fill('#da-lieu', 'Moanda');
  await page.fill('#da-num', 'DA-2026-0099'); 
  await page.fill('#da-d1', '2026-11-02'); await page.fill('#da-d2', '2027-05-01');
  await page.fill('#da-dp', '2026-10-30');
  await page.fill('input[data-c=nom]', 'AGENT FICTIF Elise');
  await page.fill('input[data-c=poste]', 'Comptable fournisseurs');
  await page.fill('input[data-c=salaire_base]', '576300');
  await page.fill('#da-nom', 'AGENT FICTIF');
  await page.waitForFunction(() => document.querySelector('#apercu').textContent.includes('6 648 214') || document.querySelector('#apercu').textContent.includes('6 648 214'), null, { timeout: 5000 });
  await shot('04-saisie-da-apercu');
  const apercuTxt = await page.textContent('#apercu');
  console.log('APERCU contient cumul:', /6.648.214/.test(apercuTxt), '| n°:', apercuTxt.match(/\d+-10-ANO-[A-Z ]+\/2026/)?.[0]);
  await page.click('#f-da button[type=submit]');
  await page.waitForSelector('#f-bc');
  await shot('05-dossier');
  // BC
  await page.fill('#bc-n', '493930'); await page.fill('#bc-m', '6648214');
  await page.click('#f-bc button[type=submit]');
  await page.waitForTimeout(700);
  await page.click('#ds-gen');
  await page.waitForSelector('#t-fact');
  const nbLignes = await page.$$eval('#t-fact tbody tr', r => r.length);
  console.log('Factures générées (lignes):', nbLignes);
  await shot('06-dossier-factures');
  // factures : émettre décembre + rattrapage
  await page.goto('http://localhost:8765/#/factures');
  await page.waitForSelector('#fa-m');
  await page.fill('#fa-m', '2026-12'); await page.dispatchEvent('#fa-m', 'change');
  await page.waitForTimeout(500);
  await page.click('#fa-mois');
  await page.fill('#e-d', '2026-12-05');
  await page.click('#f-em button[type=submit]');
  await page.waitForSelector('.doc');
  const nbDocs = await page.$$eval('.doc', d => d.length);
  const nums = await page.$$eval('.titre-doc', d => d.map(x => x.textContent.trim()));
  console.log('Factures imprimables:', nbDocs, nums);
  await shot('07-factures-impression');
  await page.pdf({ path: OUT + 'factures.pdf', format: 'A4', printBackground: true });
  // proforma PDF
  await page.goto('http://localhost:8765/#/imprimer/proforma/1');
  await page.waitForSelector('.doc');
  await shot('08-proforma-impression');
  await page.pdf({ path: OUT + 'proforma.pdf', format: 'A4', printBackground: true });
  // factures list, paiement
  await page.goto('http://localhost:8765/#/factures');
  await page.waitForSelector('#fa-tous');
  await page.click('#fa-tous');
  await page.waitForTimeout(500);
  const first = await page.$('.f-sel');
  await first.check();
  await page.click('[data-act=envoyee]');
  await page.waitForTimeout(500);
  await (await page.$('.f-sel')).check();
  await page.click('[data-act=paiement]');
  await page.fill('#p-r', 'VIR-TEST-01');
  await page.click('#f-pay button[type=submit]');
  await page.waitForTimeout(600);
  await shot('09-factures-liste');
  // bis
  const bisBtn = await page.$('[data-bis]');
  await bisBtn.click();
  await page.fill('#b-m', '1060000');
  await page.click('#f-bis button[type=submit]');
  await page.waitForTimeout(600);
  await shot('10-factures-bis');
  // tableau de bord novembre
  await page.goto('http://localhost:8765/#/tableau');
  await page.waitForSelector('#tb-mois');
  await page.fill('#tb-mois', '2026-11'); await page.dispatchEvent('#tb-mois', 'change');
  await page.waitForTimeout(700);
  await shot('11-tableau-novembre');
  const kpis = await page.$$eval('.kpi', k => k.slice(0,4).map(x => x.innerText.replace(/\n/g,' | ')));
  console.log('KPI nov:', kpis);
  await page.goto('http://localhost:8765/#/dossiers');
  await page.waitForSelector('table');
  await shot('12-dossiers');
  // mobile
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('http://localhost:8765/#/tableau');
  await page.waitForSelector('.kpi');
  await shot('13-mobile');
  console.log('ERREURS CONSOLE:', errs.length ? errs : 'aucune');
  await b.close();
})().catch(e => { console.error('ECHEC', e); process.exit(1); });

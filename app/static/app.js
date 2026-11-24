/* ERP ANO Services – interface (JavaScript sans dépendance).
 * Tout texte affiché passe par le gabarit html`` qui échappe les valeurs :
 * aucune donnée saisie n'est interprétée comme du HTML. */
"use strict";

// ---------------------------------------------------------------------------
// Outils
// ---------------------------------------------------------------------------
class Sur { constructor(s) { this.s = s; } toString() { return this.s; } }
const ESC = { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" };
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
function val(v) {
  if (v instanceof Sur) return v.s;
  if (Array.isArray(v)) return v.map(val).join("");
  if (v === null || v === undefined || v === false) return "";
  return esc(v);
}
function html(parts, ...vals) {
  let o = parts[0];
  vals.forEach((v, i) => { o += val(v) + parts[i + 1]; });
  return new Sur(o);
}
const $ = (sel, el = document) => el.querySelector(sel);
const $$ = (sel, el = document) => Array.from(el.querySelectorAll(sel));
const NF = new Intl.NumberFormat("fr-FR");
const fmt = (n) => (n === null || n === undefined || n === "" ? "" : NF.format(n));
const xaf = (n) => (n === null || n === undefined ? "" : fmt(n) + " XAF");
const pct = (pdm) => (pdm === null || pdm === undefined ? "" : (pdm / 100).toLocaleString("fr-FR", { maximumFractionDigits: 2 }) + " %");
const dateFr = (iso) => (iso ? iso.slice(8, 10) + "/" + iso.slice(5, 7) + "/" + iso.slice(0, 4) : "");
const MOIS = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin", "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"];
const moisFr = (iso) => (iso ? MOIS[+iso.slice(5, 7) - 1] + " " + iso.slice(0, 4) : "");
const auj = () => { const d = new Date(); d.setMinutes(d.getMinutes() - d.getTimezoneOffset()); return d.toISOString().slice(0, 10); };
const moisCourant = () => auj().slice(0, 7);
const badge = (s) => html`<span class="badge ${"b-" + s}">${s}</span>`;
const entierSaisi = (s) => { const t = String(s || "").replace(/[\s  ]/g, ""); return /^\d+$/.test(t) ? parseInt(t, 10) : null; };
const pdmSaisi = (s) => { const t = String(s || "").replace(",", ".").replace(/[\s%]/g, ""); if (!/^\d+(\.\d{1,2})?$/.test(t)) return null; return Math.round(parseFloat(t) * 100); };
const TYPES = { MAD: "Mise à disposition", VISITE: "Visite médicale", BIS: "Facture bis (PV)" };

function toast(msg, err) {
  const t = document.createElement("div");
  t.className = "toast" + (err ? " err" : "");
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), err ? 7000 : 3500);
}

// ---------------------------------------------------------------------------
// API
// ---------------------------------------------------------------------------
const etat = { user: null, csrf: null, params: null };

class ErreurApi extends Error { constructor(m, code, status) { super(m); this.code = code; this.status = status; } }

async function api(methode, chemin, corps) {
  const opts = { method: methode, credentials: "same-origin", headers: {} };
  if (corps !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(corps);
  }
  if (methode !== "GET" && etat.csrf) opts.headers["X-CSRF-Token"] = etat.csrf;
  let r;
  try { r = await fetch(chemin, opts); } catch (e) { throw new ErreurApi("Le serveur ne répond pas. L'application est-elle toujours lancée ?"); }
  let j = {};
  try { j = await r.json(); } catch (e) { /* vide */ }
  if (!r.ok) {
    if (j.code === "NON_CONNECTE" && chemin !== "/api/moi") { etat.user = null; afficherConnexion("Session expirée : reconnectez-vous."); }
    if (j.code === "CHANGER_MDP") { afficherChangerMdp(true); }
    throw new ErreurApi(j.erreur || "Erreur " + r.status, j.code, r.status);
  }
  return j;
}

// Téléchargement d'un fichier produit par l'API (factures Word).
// Chrome / Edge : fenêtre « Enregistrer sous » pour choisir le dossier.
// Safari : enregistré dans Téléchargements (ou le dossier réglé dans Safari).
async function telecharger(chemin) {
  let r;
  try { r = await fetch(chemin, { credentials: "same-origin" }); } catch (e) { throw new ErreurApi("Le serveur ne répond pas. L'application est-elle toujours lancée ?"); }
  if (!r.ok) {
    let j = {};
    try { j = await r.json(); } catch (e) { /* vide */ }
    if (j.code === "NON_CONNECTE") { etat.user = null; afficherConnexion("Session expirée : reconnectez-vous."); }
    throw new ErreurApi(j.erreur || "Erreur " + r.status, j.code, r.status);
  }
  const cd = r.headers.get("Content-Disposition") || "";
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd);
  const nom = m ? decodeURIComponent(m[1]) : "factures.docx";
  const blob = await r.blob();
  if (window.showSaveFilePicker) {
    try {
      const ext = nom.slice(nom.lastIndexOf("."));
      const desc = { ".zip": "Archive zip", ".docx": "Document Word", ".csv": "Tableau (Excel, Numbers)" }[ext] || "Fichier";
      const h = await window.showSaveFilePicker({ suggestedName: nom, types: [{ description: desc, accept: { [blob.type.split(";")[0]]: [ext] } }] });
      const w = await h.createWritable(); await w.write(blob); await w.close();
      return nom;
    } catch (e) { if (e.name === "AbortError") return null; /* sinon : téléchargement classique */ }
  }
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = nom; document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
  return nom;
}

async function exporterWord(ids) {
  try {
    const nom = await telecharger("/api/factures/word?ids=" + ids.join(","));
    if (nom) toast(nom.endsWith(".zip") ? "Fichier zip enregistré : " + nom + " (un document Word par facture, double-cliquez pour l'ouvrir)." : "Document Word enregistré : " + nom);
  } catch (e) { toast(e.message, true); }
}

async function action(fn, msgOk) {
  try { const r = await fn(); if (msgOk) toast(msgOk); return r; } catch (e) { toast(e.message, true); throw e; }
}

// ---------------------------------------------------------------------------
// Modale
// ---------------------------------------------------------------------------
function ouvrirModale(contenu, large) {
  const m = $("#modale");
  m.innerHTML = html`<div class="boite ${large ? "large" : ""}">${contenu}</div>`.s;
  m.classList.remove("cache");
  appliquerStyles(m);
  const premier = $("input, select, textarea", m);
  if (premier) premier.focus();
  return m;
}
function fermerModale() { $("#modale").classList.add("cache"); $("#modale").innerHTML = ""; }
document.addEventListener("keydown", (e) => { if (e.key === "Escape") fermerModale(); });
document.addEventListener("click", (e) => { if (e.target.id === "modale") fermerModale(); if (e.target.closest("[data-fermer]")) fermerModale(); });

function confirmer(titre, texte, libelle = "Confirmer", classe = "") {
  return new Promise((res) => {
    const m = ouvrirModale(html`<h2>${titre}</h2><p>${texte}</p>
      <div class="pied"><button class="secondaire" data-non>Annuler</button><button class="${classe}" data-oui>${libelle}</button></div>`);
    $("[data-oui]", m).onclick = () => { fermerModale(); res(true); };
    $("[data-non]", m).onclick = () => { fermerModale(); res(false); };
    $("[data-oui]", m).focus();
  });
}

// ---------------------------------------------------------------------------
// Connexion, installation, mot de passe
// ---------------------------------------------------------------------------
function afficherConnexion(message) {
  $("#app").className = "";
  $("#app").innerHTML = html`<div class="connexion"><form class="carte" id="f-cnx">
    <img class="logo-connexion" src="/static/logo.png" alt=""><h1>Connexion</h1><p class="doux">Gestion des mises à disposition</p>
    ${message ? html`<div class="bandeau alerte petit">${message}</div>` : ""}
    <div class="champ"><label for="c-id">Identifiant</label><input id="c-id" autocomplete="username" required maxlength="40"></div>
    <div class="champ"><label for="c-mdp">Mot de passe</label><input id="c-mdp" type="password" autocomplete="current-password" required maxlength="128"></div>
    <div class="erreur-form" id="c-err"></div>
    <button type="submit" data-style="width:100%">Se connecter</button></form></div>`.s;
  $("#c-id").focus();
  $("#f-cnx").onsubmit = async (e) => {
    e.preventDefault();
    $("#c-err").textContent = "";
    try {
      const r = await api("POST", "/api/connexion", { identifiant: $("#c-id").value.trim(), mot_de_passe: $("#c-mdp").value });
      etat.user = r.utilisateur; etat.csrf = r.csrf;
      if (etat.user.doit_changer_mdp) return afficherChangerMdp(true);
      demarrerApp();
    } catch (err) { $("#c-err").textContent = err.message; $("#c-mdp").value = ""; }
  };
}

function afficherInstallation() {
  $("#app").className = "";
  $("#app").innerHTML = html`<div class="connexion"><form class="carte" id="f-ins">
    <h1>Bienvenue</h1><p class="doux">Première ouverture : créez le compte de la direction (administrateur).</p>
    <div class="champ"><label for="i-nom">Votre nom</label><input id="i-nom" required maxlength="80"></div>
    <div class="champ"><label for="i-id">Identifiant de connexion</label><input id="i-id" required maxlength="40" autocomplete="username" pattern="[A-Za-z0-9._\\-]{3,40}"><div class="aide">Lettres, chiffres, point ou tiret (ex. luc).</div></div>
    <div class="champ"><label for="i-mdp">Mot de passe</label><input id="i-mdp" type="password" required minlength="12" maxlength="128" autocomplete="new-password"><div class="aide">Au moins 12 caractères. Une phrase courte est idéale.</div></div>
    <div class="champ"><label for="i-mdp2">Confirmer le mot de passe</label><input id="i-mdp2" type="password" required autocomplete="new-password"></div>
    <div class="erreur-form" id="i-err"></div>
    <button type="submit" data-style="width:100%">Créer le compte</button></form></div>`.s;
  $("#f-ins").onsubmit = async (e) => {
    e.preventDefault();
    if ($("#i-mdp").value !== $("#i-mdp2").value) { $("#i-err").textContent = "Les deux mots de passe sont différents."; return; }
    try {
      await api("POST", "/api/installation", { nom: $("#i-nom").value, identifiant: $("#i-id").value.trim(), mot_de_passe: $("#i-mdp").value });
      afficherConnexion("Compte créé. Connectez-vous.");
    } catch (err) { $("#i-err").textContent = err.message; }
  };
}

function formMdp(oblige) {
  return html`<form id="f-mdp">
    <h2>${oblige ? "Choisissez votre mot de passe" : "Changer mon mot de passe"}</h2>
    ${oblige ? html`<p class="doux petit">Votre mot de passe est provisoire : remplacez-le pour continuer.</p>` : ""}
    <div class="champ"><label for="m-a">Mot de passe actuel</label><input id="m-a" type="password" required autocomplete="current-password"></div>
    <div class="champ"><label for="m-n">Nouveau mot de passe</label><input id="m-n" type="password" required minlength="12" maxlength="128" autocomplete="new-password"><div class="aide">Au moins 12 caractères, sans votre identifiant.</div></div>
    <div class="champ"><label for="m-n2">Confirmer</label><input id="m-n2" type="password" required autocomplete="new-password"></div>
    <div class="erreur-form" id="m-err"></div>
    <div class="pied">${oblige ? "" : html`<button type="button" class="secondaire" data-fermer>Annuler</button>`}<button type="submit">Enregistrer</button></div></form>`;
}

function brancherFormMdp(apres) {
  $("#f-mdp").onsubmit = async (e) => {
    e.preventDefault();
    if ($("#m-n").value !== $("#m-n2").value) { $("#m-err").textContent = "Les deux mots de passe sont différents."; return; }
    try {
      await api("POST", "/api/moi/mot-de-passe", { actuel: $("#m-a").value, nouveau: $("#m-n").value });
      toast("Mot de passe modifié.");
      apres();
    } catch (err) { $("#m-err").textContent = err.message; }
  };
}

function afficherChangerMdp(oblige) {
  if (oblige) {
    $("#app").className = "";
    $("#app").innerHTML = html`<div class="connexion"><div class="carte">${formMdp(true)}</div></div>`.s;
    brancherFormMdp(() => { etat.user.doit_changer_mdp = false; demarrerApp(); });
  } else {
    ouvrirModale(formMdp(false));
    brancherFormMdp(fermerModale);
  }
}

// ---------------------------------------------------------------------------
// Structure de l'application et navigation
// ---------------------------------------------------------------------------
const PAGES = [
  { h: "#/tableau", t: "Tableau de bord", roles: ["admin", "gestion", "lecture"] },
  { h: "#/dossiers", t: "Dossiers (DA)", roles: ["admin", "gestion"] },
  { h: "#/nouvelle-da", t: "+ Nouvelle DA", roles: ["admin", "gestion"] },
  { h: "#/interimaires", t: "Intérimaires", roles: ["admin", "gestion"] },
  { h: "#/factures", t: "Factures", roles: ["admin", "gestion", "lecture"] },
  { sep: true },
  { h: "#/clients", t: "Clients", roles: ["admin", "gestion"] },
  { h: "#/parametres", t: "Paramètres", roles: ["admin", "gestion"] },
  { h: "#/utilisateurs", t: "Utilisateurs", roles: ["admin"] },
  { h: "#/journal", t: "Journal d'activité", roles: ["admin"] },
];
const ROLES = { admin: "Direction (admin)", gestion: "Gestion (devis, factures)", lecture: "Lecture (tableau de bord)" };
const peut = (...roles) => etat.user && roles.includes(etat.user.role);

async function demarrerApp() {
  try { etat.params = await api("GET", "/api/parametres"); } catch (e) { return; }
  $("#app").className = "";
  $("#app").innerHTML = html`<div class="coque">
    <nav class="menu"><div class="marque">${etat.params.parametres.raison_sociale}<small>ERP – version MVP</small></div>
      ${PAGES.map((p) => (p.sep ? html`<div class="sep"></div>` : p.roles.includes(etat.user.role) ? html`<a href="${p.h}">${p.t}</a>` : ""))}
      <div class="sep"></div>
      <div class="moi"><b>${etat.user.nom}</b>${ROLES[etat.user.role]}</div>
      <a href="#/mon-compte" data-mdp>Changer mon mot de passe</a>
      <a href="#/" data-deco>Se déconnecter</a>
    </nav>
    <main class="contenu" id="page"></main></div>`.s;
  $("[data-deco]").onclick = async (e) => { e.preventDefault(); try { await api("POST", "/api/deconnexion", {}); } catch (x) { /* rien */ } etat.user = null; etat.csrf = null; afficherConnexion("Vous êtes déconnecté."); };
  $("[data-mdp]").onclick = (e) => { e.preventDefault(); afficherChangerMdp(false); };
  router();
}

window.addEventListener("hashchange", () => { if (etat.user) router(); });

async function router() {
  fermerModale();
  const h = location.hash || "#/tableau";
  $$(".menu a").forEach((a) => a.classList.toggle("actif", h.startsWith(a.getAttribute("href")) && a.getAttribute("href") !== "#/"));
  const page = $("#page");
  if (!page) return;
  page.innerHTML = '<p class="doux">Chargement…</p>';
  const [, nom, a1, a2] = h.split("/");
  try {
    if (nom === "tableau" || !nom) await pageTableau(page);
    else if (nom === "dossiers") await pageDossiers(page);
    else if (nom === "dossier") await pageDossier(page, +a1);
    else if (nom === "nouvelle-da") await pageSaisieDA(page, null);
    else if (nom === "modifier-da") await pageSaisieDA(page, +a1);
    else if (nom === "factures") await pageFactures(page);
    else if (nom === "clients") await pageClients(page);
    else if (nom === "interimaires") await pageInterimaires(page);
    else if (nom === "parametres") await pageParametres(page);
    else if (nom === "utilisateurs") await pageUtilisateurs(page);
    else if (nom === "journal") await pageJournal(page);
    else if (nom === "imprimer") await pageImprimer(page, a1, a2);
    else page.innerHTML = html`<p>Page introuvable. <a href="#/tableau">Retour au tableau de bord</a></p>`.s;
  } catch (e) {
    if (e.status !== 401) page.innerHTML = html`<div class="bandeau danger">${e.message}</div>`.s;
  }
  window.scrollTo(0, 0);
}

// ---------------------------------------------------------------------------
// Tableau de bord
// ---------------------------------------------------------------------------
const filtres = { mois: moisCourant(), factMois: moisCourant(), factStatut: "", dosStatut: "", dosQ: "" };

// Carte « À faire » : chaque ligne = une action, avec le lien qui y mène
function carteAFaire(a) {
  const lignes = [
    [a.a_emettre, "facture(s) à émettre (mois en cours et mois passés)", "#/factures", "À émettre"],
    [a.a_envoyer, "facture(s) émise(s) pas encore envoyée(s) au client", "#/factures", "À envoyer"],
    [a.en_retard, "facture(s) en retard de paiement (échéance dépassée)", "#/factures", "En retard"],
    [a.sans_bc, "proforma(s) envoyée(s) ou validée(s) sans bon de commande", "#/dossiers", null],
    [a.brouillons, "proforma(s) en brouillon, pas encore envoyée(s)", "#/dossiers", null],
  ].filter((l) => l[0]);
  return html`<div class="carte a-faire"><h2>À faire</h2>${lignes.length
    ? html`<ul>${lignes.map(([n, lib, lien, statut]) => html`<li><a href="${lien}" ${statut ? html`data-statut="${statut}"` : ""}><b>${n}</b> ${lib}</a></li>`)}</ul>`
    : html`<p class="doux">Rien en attente : tout est émis, envoyé et à jour.</p>`}</div>`;
}

async function pageTableau(page) {
  const t = await api("GET", "/api/tableau-de-bord?mois=" + filtres.mois);
  const premier = t.serie.findIndex((s) => s.a_facturer_ht || s.facture_ht || s.paye);
  t.serie = premier < 0 ? t.serie.slice(-1) : t.serie.slice(premier);
  const maxi = Math.max(1, ...t.serie.map((s) => Math.max(s.a_facturer_ht, s.facture_ht, s.paye)));
  const largeur = (v) => Math.round((100 * v) / maxi) + "%";
  page.innerHTML = html`
    <div class="entete"><div><h1>Tableau de bord</h1><p>Situation du mois de ${t.libelle}</p></div>
      <div class="actions"><label for="tb-mois" class="doux" data-style="margin:0">Mois</label><input type="month" id="tb-mois" value="${filtres.mois}" data-style="width:auto"></div></div>
    ${t.num_facture_manquant && peut("admin") ? html`<div class="bandeau alerte"><span>Avant d'émettre la première facture, indiquez le <b>dernier n° de facture</b> réellement utilisé (ex. 152).</span><a class="bouton" href="#/parametres">Ouvrir les paramètres</a></div>` : ""}
    ${peut("admin", "gestion") ? carteAFaire(t.a_faire) : ""}
    ${t.ecarts_bc.length ? html`<div class="bandeau danger"><span>Écart entre BC et proforma : ${t.ecarts_bc.map((e) => html`<a href="#/dossier/${e.dossier_id}">${e.numero}</a> (${fmt(e.ecart)} XAF) `)}</span></div>` : ""}
    <div class="grille g4">
      <div class="kpi accent"><div class="lib">Personnes en contrat</div><div class="val">${t.personnes_en_contrat}</div><div class="sous">${t.nouveaux} nouveau(x), ${t.fins} fin(s) dans le mois${t.personnes_en_attente ? html`<br>+ ${t.personnes_en_attente} en attente de validation` : ""}</div></div>
      <div class="kpi"><div class="lib">À facturer (HT)</div><div class="val">${fmt(t.a_facturer_total_ht)}</div><div class="sous">dont visites médicales ${fmt(t.visites_ht)} · TTC ${fmt(t.a_facturer_ttc)}</div></div>
      <div class="kpi ok"><div class="lib">Facturé (TTC)</div><div class="val">${fmt(t.facture_ttc)}</div><div class="sous">${t.factures_emises} émise(s), ${t.factures_envoyees} envoyée(s), ${t.factures_payees} payée(s)</div></div>
      <div class="kpi ${t.impaye_mois > 0 ? "alerte" : "ok"}"><div class="lib">Payé sur ce mois</div><div class="val">${fmt(t.paye)}</div><div class="sous">Reste dû sur ce mois : ${fmt(t.impaye_mois)}</div></div>
    </div>
    <h3>Tous mois confondus</h3>
    <div class="grille g4">
      <div class="kpi"><div class="lib">Total facturé (TTC)</div><div class="val">${fmt(t.total_facture_ttc)}</div></div>
      <div class="kpi ok"><div class="lib">Total encaissé</div><div class="val">${fmt(t.total_paye)}</div></div>
      <div class="kpi alerte"><div class="lib">Reste à encaisser</div><div class="val">${fmt(t.reste_a_encaisser)}</div></div>
      <div class="kpi ${t.factures_en_retard ? "danger" : ""}"><div class="lib">Factures en retard</div><div class="val">${t.factures_en_retard}</div><div class="sous">${fmt(t.montant_en_retard)} XAF TTC (échéance dépassée)</div></div>
    </div>
    <div class="grille g2" data-style="margin-top:1rem">
      <div class="carte"><h2>Contrats qui se terminent bientôt</h2>
        ${t.alertes_fin.length ? html`<table><thead><tr><th>Agent</th><th>Fin</th><th class="num">Jours</th></tr></thead><tbody>
          ${t.alertes_fin.map((a) => html`<tr class="cliquable" data-href="#/dossier/${a.dossier_id}"><td>${a.agent}</td><td>${dateFr(a.fin)}</td><td class="num">${a.jours}</td></tr>`)}</tbody></table>
          <p class="aide">Renouvellement = nouvelle DA.</p>` : html`<p class="doux">Aucun contrat ne se termine dans les ${etat.params.parametres.alerte_fin_jours} jours.</p>`}</div>
      <div class="carte"><h2>Visites médicales à refaire</h2>
        ${t.alertes_visite.length ? html`<table><thead><tr><th>Agent</th><th>À refaire le</th><th>Fin du contrat</th></tr></thead><tbody>
          ${t.alertes_visite.map((a) => html`<tr class="cliquable" data-href="#/dossier/${a.dossier_id}"><td>${a.agent}</td><td>${dateFr(a.date)}</td><td>${dateFr(a.fin)}</td></tr>`)}</tbody></table>` : html`<p class="doux">Aucune visite à prévoir dans les ${etat.params.parametres.alerte_visite_jours} jours.</p>`}</div>
    </div>
    <div class="carte"><h2>Mois par mois (12 derniers mois au plus)</h2>
      <div class="legende"><span class="l-prevu">Prévu (HT)</span><span class="l-facture">Facturé (HT)</span><span class="l-paye">Payé (TTC)</span></div>
      <div class="tableau-wrap"><table class="barres"><thead><tr><th>Mois</th><th class="num">Prévu HT</th><th class="num">Facturé HT</th><th class="num">Payé</th><th data-style="width:40%"></th></tr></thead><tbody>
      ${t.serie.map((s) => html`<tr><td>${s.libelle}</td><td class="num">${fmt(s.a_facturer_ht)}</td><td class="num">${fmt(s.facture_ht)}</td><td class="num">${fmt(s.paye)}</td>
        <td><div class="barre-fond"><div class="barre-val bv-prevu" data-style="width:${largeur(s.a_facturer_ht)}"></div></div>
            <div class="barre-fond" data-style="margin-top:2px"><div class="barre-val bv-facture" data-style="width:${largeur(s.facture_ht)}"></div></div>
            <div class="barre-fond" data-style="margin-top:2px"><div class="barre-val bv-paye" data-style="width:${largeur(s.paye)}"></div></div></td></tr>`)}
      </tbody></table></div>
      <p class="aide">« Prévu » = montants au prorata des contrats validés + visites médicales dues dans le mois.</p></div>`.s;
  // largeur des barres : data-style="" est bloqué par la CSP, on l'applique en JS
  appliquerStyles(page);
  $("#tb-mois").onchange = (e) => { if (e.target.value) { filtres.mois = e.target.value; pageTableau(page); } };
  // un clic sur une ligne « À faire » ouvre les factures déjà filtrées sur ce statut
  $$(".a-faire a[data-statut]", page).forEach((l) => { l.onclick = () => { filtres.factStatut = l.dataset.statut; filtres.factMois = ""; }; });
  lignesCliquables(page);
}

// La politique de sécurité (CSP) interdit les attributs data-style="" : on les
// recopie en propriétés JS, ce qui est autorisé.
function appliquerStyles(racine) {
  $$("[data-style]", racine).forEach((el) => {
    const s = el.getAttribute("data-style");
    el.removeAttribute("data-style");
    s.split(";").forEach((d) => { const i = d.indexOf(":"); if (i > 0) el.style.setProperty(d.slice(0, i).trim(), d.slice(i + 1).trim()); });
  });
}
function lignesCliquables(racine) {
  $$("tr[data-href]", racine).forEach((tr) => { tr.onclick = (e) => { if (!e.target.closest("button, input, a")) location.hash = tr.dataset.href; }; });
}
function rendre(page, contenu) { page.innerHTML = contenu.s; appliquerStyles(page); lignesCliquables(page); }

// ---------------------------------------------------------------------------
// Dossiers
// ---------------------------------------------------------------------------
async function pageDossiers(page) {
  const q = new URLSearchParams();
  if (filtres.dosStatut) q.set("statut", filtres.dosStatut);
  if (filtres.dosQ) q.set("q", filtres.dosQ);
  const r = await api("GET", "/api/dossiers?" + q);
  rendre(page, html`
    <div class="entete"><div><h1>Dossiers</h1><p>Une ligne par DA / proforma. Cliquez pour voir la proforma, le BC et les factures.</p></div>
      <div class="actions"><a class="bouton" href="#/nouvelle-da">+ Nouvelle DA</a></div></div>
    <div class="carte">
      <div class="ligne-form lf3" data-style="margin-bottom:.75rem">
        <div><input id="d-q" placeholder="Rechercher : agent, matricule, n° proforma, BC, service…" value="${filtres.dosQ}"></div>
        <div><select id="d-st"><option value="">Tous les statuts</option>${etat.params.statuts.map((s) => html`<option ${s === filtres.dosStatut ? "selected" : ""}>${s}</option>`)}</select></div>
        <div class="doux petit" data-style="align-self:center">${r.dossiers.length} dossier(s)</div>
      </div>
      <div class="tableau-wrap"><table><thead><tr><th>N° proforma</th><th>Agent(s)</th><th>Service · lieu</th><th>Période</th><th class="num">Cumul HT</th><th>BC</th><th>Factures</th><th>Statut</th></tr></thead><tbody>
      ${r.dossiers.length ? r.dossiers.map((d) => html`<tr class="cliquable" data-href="#/dossier/${d.id}">
        <td class="gras">${d.numero_proforma}</td>
        <td>${d.agents.map((n, i) => html`${i ? ", " : ""}${n}${d.matricules[i] ? html` <span class="matricule">${d.matricules[i]}</span>` : ""}`)}<div class="doux petit">${[...new Set(d.postes)].join(", ")}</div></td>
        <td>${d.service}<div class="doux petit">${d.lieu}</div></td>
        <td class="petit">${dateFr(d.date_debut)} → ${dateFr(d.date_fin)}</td>
        <td class="num">${fmt(d.cumul_ht)}</td>
        <td>${d.bc_numero || html`<span class="doux">—</span>`}${d.ecart_bc !== null && Math.abs(d.ecart_bc) > 1 ? html`<div class="badge b-Annulé">écart ${fmt(d.ecart_bc)}</div>` : ""}</td>
        <td class="petit">${d.nb_factures ? html`${d.nb_emises} / ${d.nb_factures} émises` : html`<span class="doux">—</span>`}</td>
        <td>${badge(d.statut)}</td></tr>`) : html`<tr><td colspan="8" class="doux">Aucun dossier. Commencez par « Nouvelle DA ».</td></tr>`}
      </tbody></table></div></div>`);
  let minuteur;
  $("#d-q").oninput = (e) => { clearTimeout(minuteur); minuteur = setTimeout(() => { filtres.dosQ = e.target.value; pageDossiers(page).then(() => { const i = $("#d-q"); i.focus(); i.setSelectionRange(i.value.length, i.value.length); }); }, 300); };
  $("#d-st").onchange = (e) => { filtres.dosStatut = e.target.value; pageDossiers(page); };
}

// ---------------------------------------------------------------------------
// Saisie / modification d'une DA, avec proforma calculée en direct
// ---------------------------------------------------------------------------
async function pageSaisieDA(page, id) {
  const [cl, det, it] = await Promise.all([api("GET", "/api/clients"), id ? api("GET", "/api/dossiers/" + id) : null, api("GET", "/api/interimaires")]);
  const connus = it.interimaires;
  const p = etat.params.parametres;
  const d = det ? det.dossier : { client_id: (cl.clients[0] || {}).id, visite_mode: "Auto", date_proforma: auj(), service: "", lieu: "", num_da: "", imputation: "", date_debut: "", date_fin: "", notes: "", nom_numero: "" };
  const agents = det ? det.agents.map((a) => ({ nom: a.nom, poste: a.poste, salaire_base: a.salaire_base, derniere_visite: a.derniere_visite || "" })) : [{ nom: "", poste: "", salaire_base: "", derniere_visite: "" }];
  const verrou = det && det.verrouille;
  rendre(page, html`
    <div class="entete"><div><h1>${id ? "Modifier la DA " + det.dossier.numero_proforma : "Nouvelle DA"}</h1>
      <p>Saisissez la demande d'achat du client : la proforma se calcule à droite au fur et à mesure.</p></div></div>
    ${verrou ? html`<div class="bandeau alerte">Des factures sont déjà émises : seuls le n° de DA, le service, l'imputation, le lieu et les notes peuvent changer.</div>` : ""}
    <div class="da">
      <form id="f-da" autocomplete="off">
        <div class="carte"><h2>1. La demande</h2>
          <div class="ligne-form lf2">
            <div class="champ"><label for="da-client">Client</label><select id="da-client">${cl.clients.filter((c) => c.actif || c.id === d.client_id).map((c) => html`<option value="${c.id}" ${c.id === d.client_id ? "selected" : ""}>${c.nom}</option>`)}</select></div>
            <div class="champ"><label for="da-service">Service demandeur</label><input id="da-service" list="l-services" value="${d.service}" required maxlength="80" placeholder="ex. DAF"></div>
          </div>
          <div class="ligne-form lf3">
            <div class="champ"><label for="da-lieu">Lieu de travail</label><input id="da-lieu" list="l-lieux" value="${d.lieu}" required maxlength="80"></div>
            <div class="champ"><label for="da-num">N° de DA</label><input id="da-num" value="${d.num_da}" maxlength="60" placeholder="Automatique"><div class="aide">Laissez vide : n° donné automatiquement (<span id="da-num-auto">DA-AAAA-001</span>). Sinon, saisissez celui de la DA.</div></div>
            <div class="champ"><label for="da-imp">N° d'imputation</label><input id="da-imp" value="${d.imputation}" maxlength="80"><div class="aide">Souvent en bleu sur la DA. Non bloquant.</div></div>
          </div>
          <datalist id="l-services">${p.services.map((s) => html`<option value="${s}">`)}</datalist>
          <datalist id="l-interimaires">${connus.map((x) => html`<option value="${x.nom}">${x.matricule} · ${x.poste}</option>`)}</datalist>
          <datalist id="l-lieux">${p.lieux.map((s) => html`<option value="${s}">`)}</datalist>
        </div>
        <div class="carte"><h2>2. La période</h2>
          <div class="ligne-form lf3">
            <div class="champ"><label for="da-d1">Date de début</label><input type="date" id="da-d1" value="${d.date_debut}" required ${verrou ? "disabled" : ""}></div>
            <div class="champ"><label for="da-d2">Date de fin</label><input type="date" id="da-d2" value="${d.date_fin}" required ${verrou ? "disabled" : ""}></div>
            <div class="champ"><label>Visite médicale</label><div class="radios" id="da-visite">
              <label class="${d.visite_mode === "Auto" ? "choisi" : ""}"><input type="radio" name="visite" value="Auto" ${d.visite_mode === "Auto" ? "checked" : ""} ${verrou ? "disabled" : ""}>Automatique</label>
              <label class="${d.visite_mode === "Non" ? "choisi" : ""}"><input type="radio" name="visite" value="Non" ${d.visite_mode === "Non" ? "checked" : ""} ${verrou ? "disabled" : ""}>Aucune</label></div>
              <div class="aide">Automatique : au début si la dernière a plus d'un an, puis chaque année.</div></div>
          </div>
        </div>
        <div class="carte"><h2>3. Les agents</h2>
          <table class="agents-saisie"><thead><tr><th>Nom et prénoms</th><th>Poste</th><th>Salaire de base</th><th>Dernière visite</th><th></th></tr></thead>
          <tbody id="da-agents"></tbody></table>
          ${verrou ? "" : html`<button type="button" class="secondaire petit" id="da-plus">+ Ajouter un agent</button>`}
          <p class="aide">Dernière visite : laissez vide, elle est retrouvée automatiquement si l'agent a déjà eu un contrat.</p>
        </div>
        <div class="carte"><h2>4. La proforma</h2>
          <div class="ligne-form lf2">
            <div class="champ"><label for="da-dp">Date de la proforma</label><input type="date" id="da-dp" value="${d.date_proforma}" ${verrou ? "disabled" : ""}></div>
            <div class="champ"><label for="da-nom">Nom dans le n° de proforma</label><input id="da-nom" value="${d.nom_numero}" maxlength="40" placeholder="1er mot du nom" ${verrou ? "disabled" : ""}><div class="aide">ex. DUPONT MBINA</div></div>
          </div>
          <div class="champ"><label for="da-notes">Notes internes</label><textarea id="da-notes" rows="2" maxlength="2000">${d.notes}</textarea></div>
          <div class="erreur-form" id="da-err"></div>
          <div class="actions"><button type="submit" class="vert">${id ? "Enregistrer les modifications" : "Enregistrer la DA et créer la proforma"}</button>
            <a class="bouton secondaire" href="${id ? "#/dossier/" + id : "#/dossiers"}">Annuler</a></div>
        </div>
      </form>
      <div class="apercu"><div class="carte" id="apercu"><h2>Aperçu de la proforma</h2><p class="doux">Remplissez les dates et au moins un agent.</p></div></div>
    </div>`);

  const corpsAgents = $("#da-agents");
  function dessinerAgents() {
    corpsAgents.innerHTML = agents.map((a, i) => html`<tr data-i="${i}">
      <td><input data-c="nom" list="l-interimaires" value="${a.nom}" maxlength="120" placeholder="NOM Prénoms" required ${verrou ? "disabled" : ""}></td>
      <td><input data-c="poste" value="${a.poste}" maxlength="120" required ${verrou ? "disabled" : ""}></td>
      <td><input data-c="salaire_base" class="montant" inputmode="numeric" value="${a.salaire_base === "" ? "" : fmt(a.salaire_base)}" placeholder="0" required ${verrou ? "disabled" : ""}></td>
      <td><input data-c="derniere_visite" type="date" value="${a.derniere_visite}" ${verrou ? "disabled" : ""}></td>
      <td>${agents.length > 1 && !verrou ? html`<button type="button" class="lien" data-suppr="${i}" title="Retirer">✕</button>` : ""}</td></tr>`).join("");
    $$("input", corpsAgents).forEach((inp) => {
      inp.oninput = () => {
        const i = +inp.closest("tr").dataset.i;
        agents[i][inp.dataset.c] = inp.dataset.c === "salaire_base" ? (entierSaisi(inp.value) ?? "") : inp.value;
        if (inp.dataset.c === "nom" && !agents[i].poste) {
          // intérimaire déjà connu : on reprend son dernier poste
          const k = connus.find((x) => x.nom.toUpperCase() === inp.value.trim().toUpperCase());
          if (k && k.poste) { agents[i].poste = k.poste; $("input[data-c=poste]", inp.closest("tr")).value = k.poste; }
        }
        planifierApercu();
      };
      if (inp.dataset.c === "salaire_base") inp.onblur = () => { const v = entierSaisi(inp.value); if (v !== null) inp.value = fmt(v); };
    });
    $$("[data-suppr]", corpsAgents).forEach((b) => { b.onclick = () => { agents.splice(+b.dataset.suppr, 1); dessinerAgents(); planifierApercu(); }; });
  }
  dessinerAgents();
  if ($("#da-plus")) $("#da-plus").onclick = () => { agents.push({ nom: "", poste: agents[agents.length - 1].poste, salaire_base: "", derniere_visite: "" }); dessinerAgents(); $$("input[data-c=nom]", corpsAgents).pop().focus(); };
  $$("#da-visite input").forEach((r) => { r.onchange = () => { $$("#da-visite label").forEach((l) => l.classList.toggle("choisi", $("input", l).checked)); planifierApercu(); }; });

  function corps() {
    return {
      client_id: +$("#da-client").value, service: $("#da-service").value, lieu: $("#da-lieu").value, num_da: $("#da-num").value,
      imputation: $("#da-imp").value, date_debut: $("#da-d1").value, date_fin: $("#da-d2").value,
      visite_mode: ($("#da-visite input:checked") || {}).value || "Auto", date_proforma: $("#da-dp").value || auj(),
      nom_numero: $("#da-nom").value, notes: $("#da-notes").value,
      agents: agents.map((a) => ({ nom: a.nom, poste: a.poste, salaire_base: a.salaire_base === "" ? null : a.salaire_base, derniere_visite: a.derniere_visite || null })),
    };
  }
  let minuteur, numeroApercu = 0;
  function planifierApercu() { clearTimeout(minuteur); minuteur = setTimeout(apercu, 350); }
  async function apercu() {
    const zone = $("#apercu");
    if (!zone || !$("#f-da")) return;   // on a quitté la page entre-temps
    const c = corps();
    if (!c.date_debut || !c.date_fin || !c.agents.some((a) => a.nom && a.salaire_base)) return;
    const n = ++numeroApercu;
    try {
      const pr = await api("POST", "/api/dossiers/apercu", c);
      if (n !== numeroApercu) return;
      zone.innerHTML = html`<h2>Aperçu de la proforma</h2>
        <div class="doux petit">N° de DA</div><div class="gras" data-style="margin-bottom:.35rem">${pr.num_da_propose}</div>
        <div class="doux petit">${id ? "N° (inchangé)" : "N° proposé"}</div><div class="gras" data-style="margin-bottom:.5rem">${id ? det.dossier.numero_proforma : pr.numero_propose}</div>
        <table><tbody>${pr.agents.map((a, i) => html`<tr><td>${a.nom} ${pr.matricules[i] ? html`<span class="matricule">${pr.matricules[i]}</span>` : html`<span class="matricule nouveau">nouveau</span>`}<div class="doux petit">${a.poste}</div></td><td class="num">${fmt(a.salaire_base)}<div class="doux petit">coût ${fmt(a.cout_mensuel)}</div></td></tr>`)}
          <tr><td class="gras">Coût mensuel total</td><td class="num gras">${fmt(pr.cout_mensuel_total)}</td></tr></tbody></table>
        <h3>Mois par mois</h3>
        <table><thead><tr><th>Mois</th><th class="num">Nb jours effectués</th><th class="num">Prorata</th><th class="num">Montant HT</th></tr></thead><tbody>
          ${pr.nb_visites ? html`<tr><td>Visite médicale</td><td class="num">${pr.nb_visites}</td><td class="num">× ${fmt(pr.visite_ht)}</td><td class="num gras">${fmt(pr.visites_ht)}</td></tr>` : ""}
          ${pr.mois.map((m) => html`<tr><td>${m.libelle}</td><td class="num gras">${m.jours}/${m.jours_mois}</td><td class="num">${m.complet ? "1" : m.prorata.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}</td><td class="num gras">${fmt(Math.round(m.montant))}</td></tr>`)}
          <tr class="total"><td colspan="3">Cumul HT</td><td class="num">${fmt(pr.cumul_ht)}</td></tr>
</tbody></table>
        ${pr.dernieres_visites.some((x) => x) ? html`<p class="aide">Dernière visite retrouvée : ${pr.agents.map((a, i) => (pr.dernieres_visites[i] ? a.nom + " le " + dateFr(pr.dernieres_visites[i]) : "")).filter((x) => x).join(", ")}.</p>` : ""}
        <div class="aide">Le cumul est arrondi une seule fois (comme la proforma Excel).</div>`.s;
      appliquerStyles(zone);
      $("#da-err").textContent = "";
      if ($("#da-num-auto")) $("#da-num-auto").textContent = c.num_da ? "DA-AAAA-001" : pr.num_da_propose;
    } catch (e) {
      if (n === numeroApercu) zone.innerHTML = html`<h2>Aperçu de la proforma</h2><div class="bandeau alerte petit">${e.message}</div>`.s;
    }
  }
  $$("#f-da input, #f-da select, #f-da textarea").forEach((el) => { if (!el.closest("#da-agents")) { el.addEventListener("input", planifierApercu); el.addEventListener("change", planifierApercu); } });
  $("#f-da").onsubmit = async (e) => {
    e.preventDefault();
    const bouton = $("#f-da button[type=submit]");
    bouton.disabled = true;
    try {
      if (id) {
        await api("PUT", "/api/dossiers/" + id, corps());
        toast("Dossier mis à jour.");
        location.hash = "#/dossier/" + id;
      } else {
        const r = await api("POST", "/api/dossiers", corps());
        toast("DA " + r.num_da + " enregistrée : proforma " + r.numero_proforma);
        location.hash = "#/dossier/" + r.id;
      }
    } catch (err) { $("#da-err").textContent = err.message; bouton.disabled = false; }
  };
  apercu();
}

// ---------------------------------------------------------------------------
// Détail d'un dossier : proforma, BC, factures
// ---------------------------------------------------------------------------
const ORDRE_ETAPES = ["Brouillon", "Envoyé", "Validé", "BC reçu", "En cours", "Terminé"];

async function pageDossier(page, id) {
  const r = await api("GET", "/api/dossiers/" + id);
  const d = r.dossier, pr = r.proforma;
  const iEtape = ORDRE_ETAPES.indexOf(d.statut);
  const nbFact = r.factures.length, nbEmises = r.factures.filter((f) => f.numero && f.statut !== "Remplacée").length;
  const ecartOk = r.ecart_bc !== null && Math.abs(r.ecart_bc) <= 1;
  rendre(page, html`
    <div class="entete"><div><h1>${d.numero_proforma}</h1><p>${r.client.nom} · ${d.service} · ${d.lieu} · du ${dateFr(d.date_debut)} au ${dateFr(d.date_fin)}</p></div>
      <div class="actions">
        <a class="bouton secondaire" href="#/imprimer/proforma/${id}">Proforma en PDF</a>
        ${d.statut !== "Annulé" ? html`<a class="bouton secondaire" href="#/modifier-da/${id}">Modifier</a>` : ""}
        <select id="ds-statut" data-style="width:auto" title="Statut">${etat.params.statuts.map((s) => html`<option ${s === d.statut ? "selected" : ""}>${s}</option>`)}</select>
      </div></div>
    <div class="etapes">${ORDRE_ETAPES.map((s, i) => html`<div class="etape ${d.statut === "Annulé" ? "" : i < iEtape ? "fait" : i === iEtape ? "courant" : ""}">${s}</div>`)}</div>
    ${d.statut === "Annulé" ? html`<div class="bandeau danger">Dossier annulé.</div>` : ""}
    <div class="grille g3">
      <div class="kpi accent"><div class="lib">Cumul proforma HT</div><div class="val">${fmt(pr.cumul_ht)}</div><div class="sous">XAF hors taxes</div></div>
      <div class="kpi ${d.bc_numero ? (ecartOk ? "ok" : "danger") : "alerte"}"><div class="lib">Bon de commande</div><div class="val">${d.bc_numero || "En attente"}</div>
        <div class="sous">${d.bc_numero ? html`${fmt(d.bc_montant)} XAF · ${ecartOk ? (r.ecart_bc === 0 ? "identique à la proforma" : "écart d'arrondi de " + r.ecart_bc + " XAF") : "écart de " + fmt(r.ecart_bc) + " XAF"}` : "Saisissez le BC dès réception"}</div></div>
      <div class="kpi"><div class="lib">Factures</div><div class="val">${nbEmises} / ${nbFact}</div><div class="sous">émises / prévues</div></div>
    </div>
    <div class="grille g2" data-style="margin-top:1rem">
      <div class="carte"><h2>Demande d'achat</h2><table><tbody>
        <tr><td class="doux">N° de DA</td><td>${d.num_da || "—"}</td></tr>
        <tr><td class="doux">Imputation</td><td>${d.imputation || html`<span class="badge b-À émettre">à demander</span>`}</td></tr>
        <tr><td class="doux">Date proforma</td><td>${dateFr(d.date_proforma)}</td></tr>
        <tr><td class="doux">Visite médicale</td><td>${d.visite_mode === "Auto" ? "Automatique (annuelle)" : "Aucune"}</td></tr>
        ${d.notes ? html`<tr><td class="doux">Notes</td><td>${d.notes}</td></tr>` : ""}</tbody></table></div>
      <div class="carte"><h2>Bon de commande (PO)</h2>
        ${d.statut === "Annulé" ? html`<p class="doux">—</p>` : html`<form id="f-bc"><div class="ligne-form lf3">
          <div class="champ"><label for="bc-n">N° de BC</label><input id="bc-n" value="${d.bc_numero}" inputmode="numeric" maxlength="20" placeholder="6 chiffres" required></div>
          <div class="champ"><label for="bc-m">Montant HT</label><input id="bc-m" class="montant" inputmode="numeric" value="${d.bc_montant === null ? "" : fmt(d.bc_montant)}" required></div>
          <div class="champ"><label for="bc-d">Reçu le</label><input id="bc-d" type="date" value="${d.bc_date || auj()}"></div></div>
          <div class="actions"><button type="submit">Enregistrer le BC</button><span class="doux petit" id="bc-ecart"></span></div></form>`}
      </div>
    </div>
    <div class="carte"><h2>Agents</h2><table><thead><tr><th>Matricule</th><th>Agent</th><th>Poste</th><th class="num">Salaire de base</th><th class="num">Coût mensuel HT</th><th>Visites prévues</th></tr></thead><tbody>
      ${pr.agents.map((a, i) => html`<tr><td><span class="matricule">${r.agents[i].matricule || ""}</span></td><td>${a.nom}</td><td>${a.poste}</td><td class="num">${fmt(a.salaire_base)}</td><td class="num">${fmt(a.cout_mensuel)}</td>
        <td class="petit">${a.visites.length ? a.visites.map(dateFr).join(", ") : html`<span class="doux">aucune${r.agents[i].derniere_visite ? " (dernière le " + dateFr(r.agents[i].derniere_visite) + ")" : ""}</span>`}</td></tr>`)}
    </tbody></table></div>
    <div class="grille g2">
      <div class="carte"><h2>Détail des charges</h2><table><thead><tr><th>Libellé</th><th class="num">Taux</th><th class="num">Total HT</th></tr></thead><tbody>
        ${pr.detail_charges.map((c, i) => html`<tr><td>${i + 1}/ ${c.libelle}</td><td class="num">${c.taux_pdm === null ? "" : pct(c.taux_pdm)}</td><td class="num">${fmt(c.total)}</td></tr>`)}
        <tr class="total"><td>Coût mensuel</td><td class="num">× ${(pr.coefficient_pdm / 10000).toLocaleString("fr-FR")}</td><td class="num">${fmt(pr.cout_mensuel_total)}</td></tr></tbody></table></div>
      <div class="carte"><h2>Mois par mois</h2><table><thead><tr><th>Mois</th><th class="num">Nb jours effectués</th><th class="num">Prorata</th><th class="num">Montant HT</th></tr></thead><tbody>
        ${pr.nb_visites ? html`<tr><td>Visite médicale</td><td class="num">${pr.nb_visites}</td><td class="num">× ${fmt(pr.visite_ht)}</td><td class="num gras">${fmt(pr.visites_ht)}</td></tr>` : ""}
        ${pr.mois.map((m) => html`<tr><td>${m.libelle}</td><td class="num gras">${m.jours}/${m.jours_mois}</td><td class="num">${m.complet ? "1" : m.prorata.toLocaleString("fr-FR", { maximumFractionDigits: 4 })}</td><td class="num gras">${fmt(Math.round(m.montant))}</td></tr>`)}
        <tr class="total"><td colspan="3">Cumul HT</td><td class="num">${fmt(pr.cumul_ht)}</td></tr>
</tbody></table></div>
    </div>
    <div class="carte"><div class="entete" data-style="margin-bottom:.5rem"><h2 data-style="margin:0">Factures du contrat</h2>
      <div class="actions">${d.statut !== "Annulé" ? html`<button class="vert" id="ds-gen">${nbFact ? "Mettre à jour les factures prévues" : "Générer les factures"}</button>` : ""}
      ${nbEmises ? html`<a class="bouton secondaire" href="#/imprimer/factures/${r.factures.filter((f) => f.numero && f.statut !== "Remplacée").map((f) => f.id).join(",")}">Toutes les factures en PDF</a>` : ""}</div></div>
      ${nbFact ? tableFactures(r.factures, false) : html`<p class="doux">Aucune facture encore. À réception du BC, cliquez sur « Générer les factures » : une facture de visite médicale (si due) et une facture par mois, au prorata. Les mois déjà écoulés seront émis en rattrapage.</p>`}
    </div>`);
  brancherTableFactures(page, () => pageDossier(page, id));

  $("#ds-statut").onchange = async (e) => {
    const s = e.target.value;
    if (s === "Annulé" && !(await confirmer("Annuler ce dossier ?", "Les factures prévues non émises seront supprimées.", "Annuler le dossier", "danger"))) { e.target.value = d.statut; return; }
    try { await action(() => api("POST", "/api/dossiers/" + id + "/statut", { statut: s }), "Statut : " + s); } catch (x) { /* affiché */ }
    pageDossier(page, id);
  };
  const fbc = $("#f-bc");
  if (fbc) {
    const majEcart = () => { const m = entierSaisi($("#bc-m").value); $("#bc-ecart").textContent = m === null ? "" : "Écart avec la proforma : " + fmt(m - pr.cumul_ht) + " XAF"; };
    $("#bc-m").oninput = majEcart; majEcart();
    $("#bc-m").onblur = () => { const v = entierSaisi($("#bc-m").value); if (v !== null) $("#bc-m").value = fmt(v); };
    fbc.onsubmit = async (e) => {
      e.preventDefault();
      const m = entierSaisi($("#bc-m").value);
      if (m === null) return toast("Montant du BC : chiffres uniquement.", true);
      const nbc = Number(etat.params.parametres.bc_chiffres) || 0;
      if (nbc && !new RegExp("^\\d{" + nbc + "}$").test($("#bc-n").value.trim()) && !(await confirmer("N° de BC inhabituel", "Les BC de ce client ont normalement " + nbc + " chiffres. Enregistrer quand même ?"))) return;
      try { const res = await action(() => api("POST", "/api/dossiers/" + id + "/bc", { bc_numero: $("#bc-n").value.trim(), bc_montant: m, bc_date: $("#bc-d").value })); toast(Math.abs(res.ecart) <= 1 ? "BC enregistré : montant conforme." : "BC enregistré, mais écart de " + fmt(res.ecart) + " XAF.", Math.abs(res.ecart) > 1); } catch (x) { return; }
      pageDossier(page, id);
    };
  }
  const gen = $("#ds-gen");
  if (gen) gen.onclick = async () => {
    let forcer = false;
    for (;;) {
      try {
        const res = await api("POST", "/api/dossiers/" + id + "/generer-factures", { forcer });
        toast(res.ajoutees + " facture(s) ajoutée(s) · " + res.total + " au total.");
        break;
      } catch (e) {
        if ((e.code === "SANS_BC" || e.code === "ECART_BC") && !forcer) {
          if (await confirmer("Générer quand même ?", e.message, "Générer quand même", "orange")) { forcer = true; continue; }
          return;
        }
        toast(e.message, true); return;
      }
    }
    pageDossier(page, id);
  };
}

// Tableau de factures commun (page Factures et détail de dossier)
function tableFactures(factures, avecDossier) {
  return html`<div class="tableau-wrap"><table id="t-fact"><thead><tr>
    <th><input type="checkbox" id="f-tout" title="Tout sélectionner"></th><th>Mois</th><th>Type</th>${avecDossier ? html`<th>Agent · proforma</th>` : html`<th>Agent</th>`}
    <th class="num">HT</th><th class="num">TTC</th><th>N° facture</th><th>Date · échéance</th><th>Statut</th><th></th></tr></thead><tbody>
    ${factures.length ? factures.map((f) => html`<tr class="${f.statut === "Remplacée" ? "barre" : ""}" data-id="${f.id}">
      <td><input type="checkbox" class="f-sel" value="${f.id}"></td>
      <td>${moisFr(f.mois)}${f.type === "MAD" && f.jours !== f.jours_mois ? html`<div class="doux petit">${f.jours} j / ${f.jours_mois}</div>` : ""}</td>
      <td class="petit">${TYPES[f.type]}</td>
      <td>${f.agent}${f.matricule ? html` <span class="matricule">${f.matricule}</span>` : ""}${avecDossier ? html`<div class="petit"><a href="#/dossier/${f.dossier_id}">${f.numero_proforma}</a>${f.bc_numero ? " · BC " + f.bc_numero : ""}</div>` : ""}</td>
      <td class="num">${fmt(f.montant_ht)}</td><td class="num">${fmt(f.ttc)}</td>
      <td class="petit gras">${f.numero || html`<span class="doux">—</span>`}${f.remarque ? html`<div class="doux">${f.remarque}</div>` : ""}</td>
      <td class="petit">${f.date_facture ? dateFr(f.date_facture) : ""}${f.echeance ? html`<div class="doux">éch. ${dateFr(f.echeance)}</div>` : ""}</td>
      <td>${badge(f.statut)}${f.paye_le ? html`<div class="doux petit">le ${dateFr(f.paye_le)}${f.ref_paiement ? " · " + f.ref_paiement : ""}</div>` : f.envoyee_le ? html`<div class="doux petit">envoyée le ${dateFr(f.envoyee_le)}</div>` : ""}${f.retard_jours ? html`<div class="petit" data-style="color:#b42318">${f.retard_jours} j de retard</div>` : ""}</td>
      <td class="actions-ligne">${f.numero && f.statut !== "Remplacée" ? html`<a class="bouton secondaire petit" href="#/imprimer/factures/${f.id}" title="Cette facture seule en PDF">PDF</a>${peut("admin", "gestion") ? html` <button class="secondaire petit" data-word="${f.id}" title="Cette facture seule en Word modifiable">Word</button>` : ""}` : ""}
        ${peut("admin", "gestion") && f.numero && f.type !== "BIS" && !f.paye_le && !f.remplacee_par_id ? html`<button class="secondaire petit" data-bis="${f.id}" title="Facture ajustée selon le PV">Bis (PV)</button>` : ""}
        ${peut("admin", "gestion") && f.paye_le ? html`<button class="lien petit" data-annpay="${f.id}">annuler paiement</button>` : ""}</td></tr>`) : html`<tr><td colspan="10" class="doux">Aucune facture.</td></tr>`}
    </tbody></table></div>
    ${peut("admin", "gestion") && factures.length ? html`<div class="actions" data-style="margin-top:.75rem"><span class="doux petit" id="f-nb">0 sélectionnée(s)</span>
      <button class="petit" data-act="emettre">Émettre (donner un n°)</button>
      <button class="petit secondaire" data-act="envoyee">Marquer envoyée(s)</button>
      <button class="petit vert" data-act="paiement">Enregistrer un paiement</button>
      <button class="petit secondaire" data-act="pdf">PDF de la sélection</button>
      <button class="petit secondaire" data-act="word">Word de la sélection</button></div>` : ""}`;
}

function brancherTableFactures(page, rafraichir) {
  const t = $("#t-fact", page);
  if (!t) return;
  const sel = () => $$(".f-sel:checked", t).map((c) => +c.value);
  const majNb = () => { const n = $("#f-nb", page); if (n) n.textContent = sel().length + " sélectionnée(s)"; };
  $$(".f-sel", t).forEach((c) => { c.onchange = majNb; });
  $("#f-tout", t).onchange = (e) => { $$(".f-sel", t).forEach((c) => { c.checked = e.target.checked; }); majNb(); };
  $$("[data-act]", page).forEach((b) => {
    b.onclick = async () => {
      const ids = sel();
      if (!ids.length) return toast("Cochez d'abord une ou plusieurs factures.", true);
      const a = b.dataset.act;
      if (a === "pdf") { location.hash = "#/imprimer/factures/" + ids.join(","); return; }
      if (a === "word") return exporterWord(ids);
      if (a === "emettre") return dialogueEmettre({ ids }, rafraichir);
      if (a === "envoyee") {
        try { const r = await api("POST", "/api/factures/envoyees", { ids, date: auj() }); toast(r.modifiees + " facture(s) marquée(s) envoyée(s)."); } catch (e) { return toast(e.message, true); }
        return rafraichir();
      }
      if (a === "paiement") {
        const m = ouvrirModale(html`<form id="f-pay"><h2>Paiement reçu</h2><p class="doux petit">${ids.length} facture(s) sélectionnée(s). Le montant payé est le TTC de chaque facture.</p>
          <div class="ligne-form lf2"><div class="champ"><label for="p-d">Date du paiement</label><input type="date" id="p-d" value="${auj()}" required></div>
          <div class="champ"><label for="p-r">N° / référence de confirmation</label><input id="p-r" maxlength="80"></div></div>
          ${ids.length === 1 ? html`<div class="champ"><label for="p-m">Montant reçu (si différent du TTC)</label><input id="p-m" class="montant" inputmode="numeric"></div>` : ""}
          <div class="pied"><button type="button" class="secondaire" data-fermer>Annuler</button><button type="submit" class="vert">Enregistrer</button></div></form>`);
        $("#f-pay", m).onsubmit = async (e) => {
          e.preventDefault();
          const corps = { ids, date: $("#p-d").value, reference: $("#p-r").value };
          if ($("#p-m") && $("#p-m").value.trim()) { const v = entierSaisi($("#p-m").value); if (v === null) return toast("Montant : chiffres uniquement.", true); corps.montant = v; }
          try { const r = await api("POST", "/api/factures/paiement", corps); toast(r.modifiees + " facture(s) marquée(s) payée(s)."); fermerModale(); rafraichir(); } catch (x) { toast(x.message, true); }
        };
      }
    };
  });
  $$("[data-word]", t).forEach((b) => { b.onclick = () => exporterWord([+b.dataset.word]); });
  $$("[data-bis]", t).forEach((b) => {
    b.onclick = () => {
      const id = +b.dataset.bis;
      const m = ouvrirModale(html`<form id="f-bis"><h2>Facture bis selon le PV</h2>
        <p class="doux petit">Le client a envoyé un PV avec un autre montant : une facture « bis » remplace celle-ci (même n° + « bis », montant et date du PV). L'ancienne n'est plus comptée.</p>
        <div class="ligne-form lf2"><div class="champ"><label for="b-m">Montant HT du PV</label><input id="b-m" class="montant" inputmode="numeric" required></div>
        <div class="champ"><label for="b-d">Date du PV</label><input type="date" id="b-d" value="${auj()}" required></div></div>
        <div class="pied"><button type="button" class="secondaire" data-fermer>Annuler</button><button type="submit" class="orange">Créer la facture bis</button></div></form>`);
      $("#f-bis", m).onsubmit = async (e) => {
        e.preventDefault();
        const v = entierSaisi($("#b-m").value);
        if (v === null) return toast("Montant : chiffres uniquement.", true);
        try { const r = await api("POST", "/api/factures/" + id + "/bis", { montant_ht: v, date_pv: $("#b-d").value }); toast("Facture " + r.numero + " créée."); fermerModale(); rafraichir(); } catch (x) { toast(x.message, true); }
      };
    };
  });
  $$("[data-annpay]", t).forEach((b) => {
    b.onclick = async () => {
      if (!(await confirmer("Annuler le paiement ?", "La facture redeviendra impayée."))) return;
      try { await api("POST", "/api/factures/" + b.dataset.annpay + "/annuler-paiement", {}); toast("Paiement annulé."); rafraichir(); } catch (x) { toast(x.message, true); }
    };
  });
}

function dialogueEmettre(cible, rafraichir) {
  const p = etat.params.parametres;
  const m = ouvrirModale(html`<form id="f-em"><h2>Émettre les factures</h2>
    <p class="doux petit">${cible.ids ? cible.ids.length + " facture(s) sélectionnée(s)" : "Factures de " + moisFr(cible.mois + "-01") + (cible.rattrapage ? " et des mois précédents non émis (rattrapage)" : "")}.
    Chaque facture reçoit le n° suivant (dernier n° utilisé : ${p.dernier_num_facture === null ? "non renseigné" : p.dernier_num_facture}). Les factures déjà émises ne changent pas.</p>
    <div class="champ"><label for="e-d">Date des factures</label><input type="date" id="e-d" value="${auj()}" required></div>
    <div class="pied"><button type="button" class="secondaire" data-fermer>Annuler</button><button type="submit">Émettre</button></div></form>`);
  $("#f-em", m).onsubmit = async (e) => {
    e.preventDefault();
    try {
      const r = await api("POST", "/api/factures/emettre", Object.assign({}, cible, { date_facture: $("#e-d").value }));
      etat.params = await api("GET", "/api/parametres");
      fermerModale();
      if (!r.emises) { toast("Aucune facture à émettre."); return rafraichir(); }
      toast(r.emises + " facture(s) émise(s).");
      location.hash = "#/imprimer/factures/" + r.ids.join(",");
    } catch (x) {
      if (x.code === "NUM_FACTURE_MANQUANT") { fermerModale(); toast(x.message, true); if (peut("admin")) location.hash = "#/parametres"; return; }
      toast(x.message, true);
    }
  };
}

// ---------------------------------------------------------------------------
// Factures (toutes)
// ---------------------------------------------------------------------------
const STATUTS_FACT = ["À émettre", "À envoyer", "Envoyée", "En retard", "Payée", "Remplacée"];

async function pageFactures(page) {
  const q = new URLSearchParams();
  if (filtres.factMois) q.set("mois", filtres.factMois);
  if (filtres.factStatut) q.set("statut", filtres.factStatut);
  const r = await api("GET", "/api/factures?" + q);
  const valides = r.factures.filter((f) => f.statut !== "Remplacée");
  const aEmettre = r.factures.filter((f) => f.statut === "À émettre").length;
  rendre(page, html`
    <div class="entete"><div><h1>Factures</h1><p>Une facture par agent et par mois, plus les visites médicales. Les montants viennent des dossiers.</p></div>
      ${peut("admin", "gestion") ? html`<div class="actions"><button id="fa-mois" ${filtres.factMois ? "" : "disabled"}>Émettre le mois ${filtres.factMois ? moisFr(filtres.factMois + "-01") : ""}</button>
        <label class="petit" data-style="display:flex;gap:.35rem;align-items:center;margin:0"><input type="checkbox" id="fa-ratt" checked> + rattrapage des mois précédents</label></div>` : ""}</div>
    <div class="carte">
      <div class="ligne-form lf4" data-style="margin-bottom:.75rem">
        <div><label for="fa-m">Mois facturé</label><input type="month" id="fa-m" value="${filtres.factMois}"></div>
        <div><label for="fa-s">Statut</label><select id="fa-s"><option value="">Tous</option>${STATUTS_FACT.map((s) => html`<option ${s === filtres.factStatut ? "selected" : ""}>${s}</option>`)}</select></div>
        <div data-style="align-self:end;display:flex;gap:.4rem;flex-wrap:wrap"><button class="secondaire" id="fa-tous">Tous les mois</button><button class="secondaire" id="fa-csv" title="Tableau pour Excel ou Numbers, avec les filtres choisis">Exporter (Excel)</button></div>
        <div data-style="align-self:end" class="doux petit">${valides.length} facture(s) · ${fmt(valides.reduce((s, f) => s + f.ttc, 0))} XAF TTC${aEmettre ? html` · <b>${aEmettre} à émettre</b>` : ""}</div>
      </div>
      ${tableFactures(r.factures, true)}</div>`);
  brancherTableFactures(page, () => pageFactures(page));
  $("#fa-m").onchange = (e) => { filtres.factMois = e.target.value; pageFactures(page); };
  $("#fa-s").onchange = (e) => { filtres.factStatut = e.target.value; pageFactures(page); };
  $("#fa-tous").onclick = () => { filtres.factMois = ""; pageFactures(page); };
  $("#fa-csv").onclick = async () => {
    try { const nom = await telecharger("/api/factures/export.csv?" + q); if (nom) toast("Tableau enregistré : " + nom); } catch (e) { toast(e.message, true); }
  };
  const bm = $("#fa-mois");
  if (bm) bm.onclick = () => dialogueEmettre({ mois: filtres.factMois, rattrapage: $("#fa-ratt").checked }, () => pageFactures(page));
}

// ---------------------------------------------------------------------------
// Documents imprimables : proforma et factures (Imprimer > Enregistrer en PDF)
// ---------------------------------------------------------------------------
function enteteEmetteur(p) {
  return html`<div class="emetteur"><b>${p.raison_sociale}</b><br>${p.adresse}<br>${p.ville}<br>${p.telephone}<br><span class="mail">${p.email}</span></div>`;
}
// Cachet + signature : servis par l'API seulement aux comptes connectés (jamais en fichier public)
const imgSignature = () => html`<img class="sig-img" src="/api/signature" alt="Cachet et signature">`;
// Montants des factures au format des factures existantes : 332.326
const fmtPt = (n) => fmt(n).replace(/[\s  ]/g, ".");
const dateLong = (iso) => (iso ? parseInt(iso.slice(8, 10), 10) + " " + MOIS[+iso.slice(5, 7) - 1] + " " + iso.slice(0, 4) : "");

function docProforma(p, d, pr, c) {
  const postes = [...new Set(pr.agents.map((a) => a.poste))].join(", ");
  const noms = pr.agents.map((a) => a.nom).join(", ");
  const valable = +p.validite_devis_jours === 30 ? "1 mois" : p.validite_devis_jours + " jours";
  const mad = pr.nb_agents > 1 ? "de " + pr.nb_agents + " " + postes : "d'un " + postes;
  return html`<div class="doc pf"><div class="pf-cadre">
    <div class="pf-tete"><div class="pf-logo"><img class="logo-doc" src="/static/logo.png" alt="${p.raison_sociale}"><div class="double-trait"></div></div>${enteteEmetteur(p)}</div>
    <div class="pf-bandeau"><div class="pf-titre">PROFORMA</div><div class="pf-num">${d.numero_proforma}</div></div>
    <div class="pf-infos"><div class="pf-gauche">
        <div class="pf-date">Date de devis : ${dateFr(d.date_proforma)}</div>
        <div class="pf-lieu">${String(d.lieu).toUpperCase()}</div>
        <div class="pf-gi">Service Demandeur :</div><div>${d.service}</div>
        <div class="pf-bi">Nombre d'agents ( ${postes} ) : ${pr.nb_agents}</div>
        ${d.imputation ? html`<div class="pf-b">Imputation : ${d.imputation}</div>` : ""}</div>
      <div class="pf-client">Nom du client : ${c.nom}<br>${c.adresse}<br>${c.ville}${c.telephone ? html`<br>Téléphone : ${c.telephone}` : ""}</div></div>
    <table class="pf-charges"><thead><tr><th class="g">Libellé</th><th class="d">Répartition</th><th>Nombre<br>Personnes</th><th>P.U. H.T.</th><th>Total H.T.</th></tr></thead><tbody>
      ${pr.detail_charges.map((x, i) => html`<tr><td>${i + 1}/ ${x.libelle}</td><td class="d">${x.taux_pdm === null ? "100%" : (x.taux_pdm % 100 ? (x.taux_pdm / 100).toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : x.taux_pdm / 100) + "%"}</td><td class="c">${x.nb}</td><td class="d">${fmt(x.pu)}</td><td class="d">${fmt(x.total)}</td></tr>`)}
    </tbody></table>
    <div class="pf-cout"><span>Coût mensuel ( ${p.heures} )</span><span>:</span><span class="pf-cout-val">${fmt(pr.cout_mensuel_total)}</span><span class="pf-xaf">XAF</span></div>
    <table class="pf-mois"><thead><tr><th class="pf-mad">Mise à disposition pour ${mad}_ ${noms} du ${dateLong(d.date_debut)} au ${dateLong(d.date_fin)}</th><th class="pf-j">Nb jours effectués</th><th class="pf-q">Quantité</th><th class="pf-t">Total HT</th><th class="pf-vide"></th></tr></thead><tbody>
      ${pr.nb_visites ? html`<tr><td class="i" colspan="2">Visite Médicale</td><td class="c b">${pr.nb_visites}</td><td class="c b">${fmt(pr.visites_ht)}</td><td class="pf-vide"></td></tr>` : ""}
      ${pr.mois.map((m) => html`<tr><td class="i">${m.libelle}</td><td class="c b">${m.jours}</td><td class="c">${m.complet ? "1" : m.prorata.toLocaleString("fr-FR", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</td><td class="c b">${fmt(Math.round(m.montant))}</td><td class="pf-vide"></td></tr>`)}
      <tr class="pf-cumul"><td class="pf-cumul-lib" colspan="3">CUMUL</td><td class="pf-cumul-val">${fmt(pr.cumul_ht)}</td><td class="pf-vide i">XAF</td></tr>
    </tbody></table>
    <div class="pf-valable">Devis valable ${valable}</div>
    <div class="pf-sign">Signature du client avec mention "bon pour accord" :</div>
    <div class="pf-resp">${imgSignature()}<div>Le responsable</div></div>
  </div>
  <div class="pf-pied">RCCM ${p.rccm} – NIF ${p.nif} – N° CNSS ${p.cnss}<br>Compte bancaire ${p.banque} ${p.compte}</div></div>`;
}

function docFacture(p, f) {
  // Désignation sans dates (demande de Luc) : le mois facturé est dans le titre
  let ligne;
  if (f.type === "MAD") ligne = html`<tr><td>MAD d'un ${f.poste}<br>${f.agent}</td><td>${String(f.jours).padStart(2, "0")}</td><td>Jours</td><td>${fmtPt(f.montant_ht)}</td><td>${fmtPt(f.montant_ht)}</td></tr>`;
  else if (f.type === "VISITE") ligne = html`<tr><td>Visite médicale<br>${f.agent}</td><td>1</td><td>1</td><td>${fmtPt(f.montant_ht)}</td><td>${fmtPt(f.montant_ht)}</td></tr>`;
  else ligne = html`<tr><td>Ajustement selon PV<br>${f.agent}</td><td>1</td><td>Forfait</td><td>${fmtPt(f.montant_ht)}</td><td>${fmtPt(f.montant_ht)}</td></tr>`;
  return html`<div class="doc fa">
    <div class="fa-tete"><div class="fa-logo"><img class="logo-doc" src="/static/logo.png" alt="${p.raison_sociale}"><div class="double-trait"></div></div>${enteteEmetteur(p)}</div>
    <div class="fa-infos"><div class="fa-gauche">
        <div>Date d'émission : ${dateFr(f.date_facture)}</div><div>Emis par : ${p.raison_sociale}</div>
        <div>Commande client N° : ${f.bc_numero}</div>
      </div>
      <div class="fa-client"><div>Nom du client : ${f.client_nom}</div><div>${f.client_adresse}</div><div>${f.client_ville}</div>${f.client_telephone ? html`<div>Téléphone : ${f.client_telephone}</div>` : ""}</div></div>
    <div class="fa-titre">Facture ${moisFr(f.mois)}<div class="fa-num">N° ${f.numero}</div></div>
    <table class="fa-table"><thead><tr><th>Désignation des produits ou des prestations</th><th>Quantité</th><th>Unité</th><th>Prix unitaire HT</th><th>TOTAL HT</th></tr></thead><tbody>${ligne}</tbody></table>
    <table class="fa-totaux"><tbody><tr><td>Total HT</td><td>${fmtPt(f.montant_ht)}</td></tr><tr><td>TVA (${pct(p.tva_pdm)})</td><td>${fmtPt(f.tva)}</td></tr>
      <tr class="fa-trait"><td colspan="2"></td></tr><tr><td>Total TTC</td><td>${fmtPt(f.ttc)}</td></tr></tbody></table>
    <div class="fa-sign"><b>Signature :</b>${imgSignature()}</div>
    <div class="fa-pied">RCCM ${p.rccm} – NIF ${p.nif} – N° CNSS ${p.cnss}<br>Compte bancaire ${p.banque} ${p.compte}</div></div>`;
}

async function pageImprimer(page, type, arg) {
  const p = etat.params.parametres;
  let docs, titre, retour, factures = null;
  if (type === "proforma") {
    const r = await api("GET", "/api/dossiers/" + (+arg));
    const d = r.dossier;
    titre = "Proforma_ANO_Services_" + d.nom_numero + "_" + dateFr(d.date_debut).replace(/\//g, "-");
    retour = "#/dossier/" + d.id;
    docs = docProforma(p, d, r.proforma, r.client);
  } else {
    const ids = String(arg || "").split(",").filter((x) => /^\d+$/.test(x));
    if (!ids.length) throw new Error("Aucune facture sélectionnée.");
    const r = await api("GET", "/api/factures?ids=" + ids.join(","));
    const fs = r.factures.filter((f) => f.numero);
    if (!fs.length) throw new Error("Ces factures n'ont pas encore de n° : émettez-les d'abord.");
    // nom du fichier : client d'abord, puis « Facture Mois Année »
    const propre = (t) => t.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[\/\\:*?"<>|]/g, "-").replace(/[^\x20-\x7e]/g, "");
    const clients = [...new Set(fs.map((f) => f.client_nom))].join(" + ");
    titre = propre(fs.length === 1 ? clients + " - Facture " + moisFr(fs[0].mois) + " - " + fs[0].agent + " - " + fs[0].numero
      : clients + " - Factures " + [...new Set(fs.map((f) => moisFr(f.mois)))].join(", ") + " (" + fs.length + ")");
    retour = "#/factures";
    docs = fs.map((f) => docFacture(p, f));
    factures = fs;
  }
  rendre(page, html`<div class="doc-barre"><a class="bouton secondaire" href="${retour}">← Retour</a>
    <button id="imp">Imprimer / Enregistrer en PDF</button>
    ${factures && peut("admin", "gestion") ? html`<button class="secondaire" id="imp-word">Word modifiable (.docx)</button>` : ""}
    <button class="secondaire" id="aide-pdf">Où sera-t-il enregistré ?</button></div>
    ${factures && factures.length > 1 ? html`<div class="carte pas-imprimer choix-factures"><b>Factures à exporter</b> <span class="doux petit">Décochez celles que vous ne voulez pas : seules les factures cochées seront imprimées / exportées.</span>
      <div class="choix-liste">${factures.map((f, i) => html`<label><input type="checkbox" class="imp-sel" data-i="${i}" value="${f.id}" checked> ${f.numero} · ${f.agent.split(" ")[0]} · ${fmt(f.ttc)}</label>`)}</div>
      <div class="actions"><button class="lien petit" id="imp-tout">tout cocher</button><button class="lien petit" id="imp-rien">tout décocher</button></div></div>` : ""}
    <div class="bandeau info cache pas-imprimer" id="aide-pdf-txt"><div><b>Vous choisissez le dossier à chaque enregistrement :</b><br><b>Safari</b> : menu Fichier > Exporter au format PDF… (ou Imprimer, puis en bas à gauche « PDF » > Enregistrer au format PDF). La fenêtre « Enregistrer » s'ouvre : choisissez le dossier (bouton ⌄ à droite du nom pour voir tous les dossiers), créez-en un au besoin (ex. Factures/2026-12), puis Enregistrer.<br><b>Chrome</b> : Imprimer, Destination « Enregistrer au format PDF », bouton Enregistrer, puis choisissez le dossier.<br>Le Mac retient le dernier dossier utilisé. Nom proposé : ${titre}.pdf</div></div>${docs}`);
  $("#aide-pdf").onclick = () => $("#aide-pdf-txt").classList.toggle("cache");
  document.title = titre;
  const cochees = () => (factures ? (factures.length > 1 ? $$(".imp-sel:checked").map((c) => +c.value) : [factures[0].id]) : []);
  const majChoix = () => {
    $$(".imp-sel").forEach((c) => { $$(".doc")[+c.dataset.i].classList.toggle("exclu", !c.checked); });
    const n = cochees().length;
    $("#imp").disabled = factures ? !n : false;
    if ($("#imp-word")) $("#imp-word").disabled = !n;
  };
  $$(".imp-sel").forEach((c) => { c.onchange = majChoix; });
  if ($("#imp-tout")) { $("#imp-tout").onclick = () => { $$(".imp-sel").forEach((c) => { c.checked = true; }); majChoix(); }; $("#imp-rien").onclick = () => { $$(".imp-sel").forEach((c) => { c.checked = false; }); majChoix(); }; }
  if ($("#imp-word")) $("#imp-word").onclick = () => exporterWord(cochees());
  $("#imp").onclick = () => window.print();
  window.addEventListener("hashchange", () => { document.title = etat.params.parametres.raison_sociale + " – ERP"; }, { once: true });
}

// ---------------------------------------------------------------------------
// Clients
// ---------------------------------------------------------------------------
async function pageInterimaires(page) {
  const r = await api("GET", "/api/interimaires");
  rendre(page, html`<div class="entete"><div><h1>Intérimaires</h1>
      <p>Chaque intérimaire reçoit un matricule fixe à sa première DA. Il le garde à chaque nouvelle DA (reconnu par son nom, sans tenir compte des accents ni des majuscules). Usage interne : le matricule n'est pas imprimé sur les proformas et factures.</p></div>
      <div class="actions"><button id="it-plus">+ Ancien intérimaire</button></div></div>
    <div class="carte"><div class="ligne-form lf3" data-style="margin-bottom:.75rem"><div><input id="it-q" placeholder="Rechercher : nom, matricule, poste…"></div><div></div><div class="doux petit" data-style="align-self:center">${r.interimaires.length} intérimaire(s), ${r.interimaires.filter((x) => x.en_contrat).length} en contrat aujourd'hui</div></div>
    <div class="tableau-wrap"><table><thead><tr><th>Matricule</th><th>Nom</th><th>Dernier poste · lieu</th><th class="num">Contrats</th><th>Depuis</th><th>Jusqu'au</th><th>Dossiers</th></tr></thead><tbody id="it-corps">
    ${r.interimaires.length ? r.interimaires.map((x) => html`<tr data-cherche="${(x.matricule + " " + x.nom + " " + x.poste + " " + x.lieu).toLowerCase()}">
      <td><span class="matricule">${x.matricule}</span></td><td class="gras">${x.nom}${x.en_contrat ? html` <span class="matricule nouveau">en contrat</span>` : ""}${x.ancien ? html` <span class="doux petit">(historique)</span>` : ""}<div><button class="lien petit" data-it="${x.id}">modifier la fiche</button></div></td>
      <td>${x.poste}<div class="doux petit">${x.lieu}</div></td><td class="num">${x.nb_contrats}</td>
      <td class="petit">${dateFr(x.premier_debut)}</td><td class="petit">${dateFr(x.derniere_fin)}</td>
      <td class="petit">${x.dossiers.map((d, i) => html`${i ? ", " : ""}<a href="#/dossier/${d.id}" class="${d.statut === "Annulé" ? "barre" : ""}">${d.numero_proforma}</a>`)}</td></tr>`)
      : html`<tr><td colspan="7" class="doux">Aucun intérimaire : ils apparaissent ici dès la première DA saisie.</td></tr>`}
    </tbody></table></div></div>`);
  const fiche = (x) => {
    const f = x ? Object.assign({ nom: x.nom }, x.fiche) : { nom: "", poste: "", lieu: "", hist_debut: "", hist_fin: "", derniere_visite: "", notes: "" };
    const m = ouvrirModale(html`<form id="f-it"><h2>${x ? "Fiche " + x.matricule : "Ajouter un ancien intérimaire"}</h2>
      <p class="doux petit">${x ? "" : "Pour les personnes déjà mises à disposition avant l'application : elles reçoivent un matricule, sans proforma ni facture. "}La dernière visite médicale est reprise automatiquement à sa prochaine DA (pas de nouvelle visite avant 1 an).</p>
      <div class="champ"><label for="it-nom">Nom et prénoms</label><input id="it-nom" value="${f.nom}" maxlength="120" required placeholder="NOM Prénoms"></div>
      <div class="ligne-form lf2"><div class="champ"><label for="it-poste">Poste</label><input id="it-poste" value="${f.poste}" maxlength="120"></div>
        <div class="champ"><label for="it-lieu">Lieu</label><input id="it-lieu" list="l-it-lieux" value="${f.lieu}" maxlength="80"></div></div>
      <datalist id="l-it-lieux">${etat.params.parametres.lieux.map((l) => html`<option value="${l}">`)}</datalist>
      <div class="ligne-form lf3"><div class="champ"><label for="it-d1">Début (ancien contrat)</label><input id="it-d1" type="date" value="${f.hist_debut || ""}"></div>
        <div class="champ"><label for="it-d2">Fin (ancien contrat)</label><input id="it-d2" type="date" value="${f.hist_fin || ""}"></div>
        <div class="champ"><label for="it-vm">Dernière visite médicale</label><input id="it-vm" type="date" value="${f.derniere_visite || ""}"></div></div>
      <div class="champ"><label for="it-notes">Notes</label><textarea id="it-notes" maxlength="500" rows="2">${f.notes}</textarea></div>
      <div class="actions"><button type="submit">Enregistrer</button><button type="button" class="secondaire" data-fermer>Annuler</button></div></form>`);
    $("#f-it", m).onsubmit = async (e) => {
      e.preventDefault();
      const corps = { nom: $("#it-nom").value, poste: $("#it-poste").value, lieu: $("#it-lieu").value, hist_debut: $("#it-d1").value || null,
        hist_fin: $("#it-d2").value || null, derniere_visite: $("#it-vm").value || null, notes: $("#it-notes").value };
      try {
        const r = await api(x ? "PUT" : "POST", "/api/interimaires" + (x ? "/" + x.id : ""), corps);
        toast(x ? "Fiche enregistrée." : "Ajouté avec le matricule " + r.matricule + ".");
        fermerModale(); pageInterimaires(page);
      } catch (err) { toast(err.message, true); }
    };
  };
  $("#it-plus").onclick = () => fiche(null);
  $$("[data-it]").forEach((b) => { b.onclick = () => fiche(r.interimaires.find((x) => x.id === +b.dataset.it)); });
  $("#it-q").oninput = (e) => { const t = e.target.value.trim().toLowerCase(); $$("#it-corps tr[data-cherche]").forEach((tr) => { tr.hidden = !!t && !tr.dataset.cherche.includes(t); }); };
}

async function pageClients(page) {
  const r = await api("GET", "/api/clients");
  rendre(page, html`<div class="entete"><div><h1>Clients</h1></div><div class="actions"><button id="cl-plus">+ Nouveau client</button></div></div>
    <div class="carte"><table><thead><tr><th>Code</th><th>Nom</th><th>Adresse</th><th>Ville</th><th>Téléphone</th><th>E-mail</th><th></th></tr></thead><tbody>
    ${r.clients.map((c) => html`<tr class="${c.actif ? "" : "barre"}"><td>${c.code}</td><td class="gras">${c.nom}</td><td>${c.adresse}</td><td>${c.ville}</td><td>${c.telephone}</td><td>${c.email}</td>
      <td class="actions-ligne"><button class="secondaire petit" data-edit="${c.id}">Modifier</button></td></tr>`)}</tbody></table></div>`);
  const form = (c) => {
    const m = ouvrirModale(html`<form id="f-cl"><h2>${c ? "Modifier " + c.code : "Nouveau client"}</h2>
      <div class="champ"><label for="cl-nom">Nom</label><input id="cl-nom" value="${c ? c.nom : ""}" required maxlength="120"></div>
      <div class="ligne-form lf2"><div class="champ"><label for="cl-adr">Adresse</label><input id="cl-adr" value="${c ? c.adresse : ""}" maxlength="120"></div>
      <div class="champ"><label for="cl-ville">Ville / pays</label><input id="cl-ville" value="${c ? c.ville : ""}" maxlength="80"></div></div>
      <div class="ligne-form lf2"><div class="champ"><label for="cl-tel">Téléphone</label><input id="cl-tel" value="${c ? c.telephone : ""}" maxlength="60"></div>
      <div class="champ"><label for="cl-mail">E-mail</label><input id="cl-mail" type="email" value="${c ? c.email : ""}" maxlength="120"></div></div>
      <div class="champ"><label for="cl-contact">Contact</label><input id="cl-contact" value="${c ? c.contact : ""}" maxlength="120"></div>
      ${c ? html`<label class="petit" data-style="display:flex;gap:.4rem;align-items:center"><input type="checkbox" id="cl-actif" ${c.actif ? "checked" : ""}> Client actif</label>` : ""}
      <div class="pied"><button type="button" class="secondaire" data-fermer>Annuler</button><button type="submit">Enregistrer</button></div></form>`);
    $("#f-cl", m).onsubmit = async (e) => {
      e.preventDefault();
      const corps = { nom: $("#cl-nom").value, adresse: $("#cl-adr").value, ville: $("#cl-ville").value, telephone: $("#cl-tel").value, email: $("#cl-mail").value, contact: $("#cl-contact").value };
      try {
        if (c) { corps.actif = $("#cl-actif").checked; await api("PUT", "/api/clients/" + c.id, corps); } else await api("POST", "/api/clients", corps);
        toast("Client enregistré."); fermerModale(); pageClients(page);
      } catch (x) { toast(x.message, true); }
    };
  };
  $("#cl-plus").onclick = () => form(null);
  $$("[data-edit]", page).forEach((b) => { b.onclick = () => form(r.clients.find((c) => c.id === +b.dataset.edit)); });
}

// ---------------------------------------------------------------------------
// Paramètres
// ---------------------------------------------------------------------------
async function pageParametres(page) {
  const r = await api("GET", "/api/parametres");
  etat.params = r;
  const p = r.parametres;
  const admin = peut("admin");
  const dis = admin ? "" : "disabled";
  const champ = (cle, lib, aide) => html`<div class="champ"><label for="p-${cle}">${lib}</label><input id="p-${cle}" data-p="${cle}" value="${p[cle] === null ? "" : p[cle]}" ${dis}>${aide ? html`<div class="aide">${aide}</div>` : ""}</div>`;
  rendre(page, html`<div class="entete"><div><h1>Paramètres</h1><p>${admin ? "Les changements de taux ne s'appliquent qu'aux nouvelles DA : les proformas existantes gardent leur barème." : "Lecture seule : seule la direction peut modifier."}</p></div></div>
    <form id="f-par">
    <div class="grille g2">
      <div class="carte"><h2>Entreprise</h2>
        ${champ("raison_sociale", "Raison sociale")}${champ("adresse", "Adresse")}${champ("ville", "Ville / pays")}${champ("telephone", "Téléphone")}${champ("email", "E-mail")}
        <div class="ligne-form lf3">${champ("rccm", "RCCM")}${champ("nif", "NIF")}${champ("cnss", "N° CNSS")}</div>
        <div class="ligne-form lf2">${champ("banque", "Banque")}${champ("compte", "Compte bancaire")}</div></div>
      <div class="carte"><h2>Taux de charges (sur le salaire de base)</h2>
        <table><thead><tr><th>Libellé</th><th class="num" data-style="width:120px">Taux %</th></tr></thead><tbody id="p-charges">
        ${r.charges.map((c) => html`<tr><td><input data-lib value="${c.libelle}" maxlength="80" ${dis}></td><td><input data-taux class="montant" value="${(c.taux_pdm / 100).toLocaleString("fr-FR")}" ${dis}></td></tr>`)}</tbody>
        <tfoot><tr class="total"><td>Coefficient coût mensuel</td><td class="num" id="p-coef">${(r.coefficient_pdm / 10000).toLocaleString("fr-FR")}</td></tr></tfoot></table>
        <h3>Facturation</h3>
        <div class="ligne-form lf2">
          <div class="champ"><label for="p-tva">TVA %</label><input id="p-tva" class="montant" value="${(p.tva_pdm / 100).toLocaleString("fr-FR")}" ${dis}></div>
          ${champ("visite_ht", "Visite médicale HT (par agent)")}</div>
        <label class="case"><input type="checkbox" id="p-tva-visite" ${p.tva_visite ? "checked" : ""} ${dis}> Appliquer la TVA sur la facture de visite médicale</label>
        <div class="ligne-form lf2">${champ("validite_visite_mois", "Validité visite (mois)")}${champ("delai_paiement_jours", "Délai de paiement (jours, puis fin de mois)")}</div>
        <div class="ligne-form lf2">${champ("modalite_reglement", "Modalité de règlement")}${champ("validite_devis_jours", "Validité du devis (jours)")}</div>
        ${champ("heures", "Heures (texte de la proforma)")}</div>
    </div>
    <div class="grille g2">
      <div class="carte"><h2>Numérotation</h2>
        <div class="ligne-form lf2">${champ("dernier_num_proforma", "Dernier n° de proforma utilisé", "La prochaine DA prendra ce n° + 1.")}
        ${champ("dernier_num_facture", "Dernier n° de facture utilisé", p.dernier_num_facture === null ? "À renseigner avant la 1re émission (ex. 152)." : "La prochaine facture prendra ce n° + 1.")}</div>
        <div class="ligne-form lf2">${champ("code_entreprise", "Code entreprise (n° de proforma)")}${champ("prefixe_facture", "Préfixe des factures")}</div>
        <div class="ligne-form lf2">${champ("code_mad", "Code facture mensuelle")}${champ("code_visite", "Code facture visite médicale")}</div>
        <p class="aide" id="p-exemples"></p>
        <div class="ligne-form lf2">${champ("bc_chiffres", "Chiffres d'un n° de BC client", "0 = pas de contrôle.")}<div></div></div>
        <div class="ligne-form lf2">${champ("alerte_fin_jours", "Alerte fin de contrat (jours avant)")}${champ("alerte_visite_jours", "Alerte visite médicale (jours avant)")}</div></div>
      <div class="carte"><h2>Listes</h2>
        <div class="champ"><label for="p-lieux">Lieux (un par ligne)</label><textarea id="p-lieux" rows="4" ${dis}>${p.lieux.join("\n")}</textarea></div>
        <div class="champ"><label for="p-services">Services demandeurs (un par ligne)</label><textarea id="p-services" rows="4" ${dis}>${p.services.join("\n")}</textarea></div></div>
    </div>
    <div class="carte"><h2>Logo et cachet sur les documents</h2>
      <div class="grille g2">
        <div><p class="doux petit">Logo (en-tête de la proforma et des factures)</p><img class="apercu-image" id="p-img-logo" src="/static/logo.png" alt="Logo">
          ${admin ? html`<div><label class="bouton secondaire petit" for="p-f-logo">Changer le logo (PNG)</label><input type="file" id="p-f-logo" accept="image/png" hidden></div>` : ""}</div>
        <div><p class="doux petit">Cachet et signature (au-dessus de « Le responsable »)</p><img class="apercu-image" id="p-img-signature" src="/api/signature" alt="Aucun cachet enregistré">
          ${admin ? html`<div><label class="bouton secondaire petit" for="p-f-signature">Changer le cachet (PNG)</label><input type="file" id="p-f-signature" accept="image/png" hidden></div>` : ""}</div>
      </div><p class="aide">Le cachet n'est jamais public : il n'est montré qu'aux comptes connectés.</p></div>
    ${admin ? html`<div class="actions"><button type="submit" class="vert">Enregistrer les paramètres</button><button type="button" class="secondaire" id="p-sauve">Faire une sauvegarde maintenant</button></div>` : ""}
    </form>`);
  if (!admin) return;
  const majCoef = () => { let s = 10000; $$("#p-charges [data-taux]").forEach((i) => { s += pdmSaisi(i.value) || 0; }); $("#p-coef").textContent = (s / 10000).toLocaleString("fr-FR"); };
  $$("#p-charges [data-taux]").forEach((i) => { i.oninput = majCoef; });
  // exemples de n° calculés en direct depuis les codes saisis
  const majEx = () => {
    const v = (k) => $("#p-" + k).value.trim();
    const an = new Date().getFullYear(), mm = String(new Date().getMonth() + 1).padStart(2, "0");
    const nf = (Number(v("dernier_num_facture")) || 0) + 1;
    $("#p-exemples").textContent = "Exemples : proforma " + ((Number(v("dernier_num_proforma")) || 0) + 1) + "-" + mm + "-" + v("code_entreprise").toUpperCase() + "-NOM/" + an
      + " · facture " + (v("prefixe_facture") + " " + nf + "/" + mm + "-" + v("code_mad") + "/" + an).trim()
      + " · visite " + (v("prefixe_facture") + " " + nf + "/" + mm + "-" + v("code_visite") + "/" + an).trim();
  };
  ["code_entreprise", "prefixe_facture", "code_mad", "code_visite", "dernier_num_proforma", "dernier_num_facture"].forEach((k) => { $("#p-" + k).oninput = majEx; });
  majEx();
  for (const quoi of ["logo", "signature"]) {
    $("#p-f-" + quoi).onchange = (e) => {
      const f = e.target.files[0];
      if (!f) return;
      if (f.type !== "image/png") return toast("Choisissez une image PNG.", true);
      if (f.size > 600000) return toast("Image trop lourde (600 Ko au plus).", true);
      const lecteur = new FileReader();
      lecteur.onload = async () => {
        try {
          await api("PUT", "/api/images/" + quoi, { png: lecteur.result });
          $("#p-img-" + quoi).src = (quoi === "logo" ? "/static/logo.png" : "/api/signature") + "?v=" + Date.now();
          toast(quoi === "logo" ? "Logo enregistré." : "Cachet enregistré.");
        } catch (x) { toast(x.message, true); }
      };
      lecteur.readAsDataURL(f);
    };
  }
  $("#p-sauve").onclick = async () => { try { const s = await api("POST", "/api/sauvegarde", {}); toast("Sauvegarde créée : " + s.fichier.split(/[\\/]/).pop()); } catch (x) { toast(x.message, true); } };
  $("#f-par").onsubmit = async (e) => {
    e.preventDefault();
    const par = {};
    $$("[data-p]").forEach((i) => { par[i.dataset.p] = i.value; });
    const tva = pdmSaisi($("#p-tva").value);
    if (tva === null) return toast("TVA : nombre attendu (ex. 18).", true);
    par.tva_pdm = tva;
    par.tva_visite = $("#p-tva-visite").checked;
    if (par.dernier_num_facture === "") par.dernier_num_facture = null;
    par.lieux = $("#p-lieux").value.split("\n");
    par.services = $("#p-services").value.split("\n");
    const charges = [];
    for (const tr of $$("#p-charges tr")) {
      const t = pdmSaisi($("[data-taux]", tr).value);
      if (t === null) return toast("Taux invalide : " + $("[data-lib]", tr).value, true);
      charges.push({ libelle: $("[data-lib]", tr).value, taux_pdm: t });
    }
    try { await api("PUT", "/api/parametres", { parametres: par, charges }); toast("Paramètres enregistrés."); pageParametres(page); } catch (x) { toast(x.message, true); }
  };
}

// ---------------------------------------------------------------------------
// Utilisateurs et journal (direction)
// ---------------------------------------------------------------------------
async function pageUtilisateurs(page) {
  const r = await api("GET", "/api/utilisateurs");
  rendre(page, html`<div class="entete"><div><h1>Utilisateurs</h1><p>Direction : tout. Gestion : DA, proformas, factures (pas les utilisateurs ni les paramètres). Lecture : tableau de bord et factures, sans les salaires.</p></div>
    <div class="actions"><button id="u-plus">+ Nouvel utilisateur</button></div></div>
    <div class="carte"><table><thead><tr><th>Identifiant</th><th>Nom</th><th>Rôle</th><th>Dernière connexion</th><th>État</th><th></th></tr></thead><tbody>
    ${r.utilisateurs.map((u) => html`<tr class="${u.actif ? "" : "barre"}"><td class="gras">${u.identifiant}</td><td>${u.nom}</td><td>${ROLES[u.role]}</td><td class="petit">${u.dernier_login || "jamais"}</td>
      <td>${u.actif ? (u.doit_changer_mdp ? badge("À envoyer") : badge("Payée")) : badge("Annulé")}<div class="doux petit">${u.actif ? (u.doit_changer_mdp ? "mot de passe provisoire" : "actif") : "désactivé"}</div></td>
      <td class="actions-ligne"><button class="secondaire petit" data-u="${u.id}">Modifier</button></td></tr>`)}</tbody></table></div>`);
  const form = (u) => {
    const m = ouvrirModale(html`<form id="f-u"><h2>${u ? "Modifier " + u.identifiant : "Nouvel utilisateur"}</h2>
      ${u ? "" : html`<div class="champ"><label for="u-id">Identifiant</label><input id="u-id" required maxlength="40" pattern="[A-Za-z0-9._\\-]{3,40}"></div>`}
      <div class="champ"><label for="u-nom">Nom</label><input id="u-nom" value="${u ? u.nom : ""}" required maxlength="80"></div>
      <div class="champ"><label for="u-role">Rôle</label><select id="u-role">${Object.keys(ROLES).map((k) => html`<option value="${k}" ${u && u.role === k ? "selected" : ""}>${ROLES[k]}</option>`)}</select></div>
      <div class="champ"><label for="u-mdp">${u ? "Nouveau mot de passe provisoire (laisser vide pour ne pas changer)" : "Mot de passe provisoire"}</label><input id="u-mdp" type="password" ${u ? "" : "required"} minlength="12" maxlength="128" autocomplete="new-password"><div class="aide">12 caractères minimum. La personne devra le changer à sa première connexion.</div></div>
      ${u ? html`<label class="petit" data-style="display:flex;gap:.4rem;align-items:center"><input type="checkbox" id="u-actif" ${u.actif ? "checked" : ""}> Compte actif</label>` : ""}
      <div class="pied"><button type="button" class="secondaire" data-fermer>Annuler</button><button type="submit">Enregistrer</button></div></form>`);
    $("#f-u", m).onsubmit = async (e) => {
      e.preventDefault();
      try {
        if (u) {
          const c = { nom: $("#u-nom").value, role: $("#u-role").value, actif: $("#u-actif").checked };
          if ($("#u-mdp").value) c.mot_de_passe = $("#u-mdp").value;
          await api("PUT", "/api/utilisateurs/" + u.id, c);
        } else await api("POST", "/api/utilisateurs", { identifiant: $("#u-id").value.trim(), nom: $("#u-nom").value, role: $("#u-role").value, mot_de_passe: $("#u-mdp").value });
        toast("Utilisateur enregistré."); fermerModale(); pageUtilisateurs(page);
      } catch (x) { toast(x.message, true); }
    };
  };
  $("#u-plus").onclick = () => form(null);
  $$("[data-u]", page).forEach((b) => { b.onclick = () => form(r.utilisateurs.find((u) => u.id === +b.dataset.u)); });
}

async function pageJournal(page) {
  const r = await api("GET", "/api/journal");
  rendre(page, html`<div class="entete"><div><h1>Journal d'activité</h1><p>Les 500 dernières actions (connexions, créations, émissions, paiements…).</p></div></div>
    <div class="carte"><div class="tableau-wrap"><table><thead><tr><th>Quand</th><th>Qui</th><th>Action</th><th>Objet</th><th>Détails</th></tr></thead><tbody>
    ${r.journal.map((j) => html`<tr><td class="petit">${j.quand}</td><td>${j.identifiant}</td><td>${j.action.replace(/_/g, " ")}</td><td class="petit">${j.objet}</td><td class="petit">${j.details}</td></tr>`)}</tbody></table></div></div>`);
}

// ---------------------------------------------------------------------------
// Démarrage
// ---------------------------------------------------------------------------
async function demarrage() {
  try {
    const e = await api("GET", "/api/etat");
    if (e.installation_requise) return afficherInstallation();
  } catch (x) { $("#app").textContent = x.message; return; }
  try {
    const r = await api("GET", "/api/moi");
    etat.user = r.utilisateur; etat.csrf = r.csrf;
    if (etat.user.doit_changer_mdp) return afficherChangerMdp(true);
    demarrerApp();
  } catch (x) { afficherConnexion(); }
}
document.addEventListener("DOMContentLoaded", demarrage);

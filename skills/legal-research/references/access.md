# Reaching the official texts

How to open each official source and what to look at. The list of sources and their weight is in
`<legal-workflow>/references/sources.md`; this file adds the practical routes. Access changes: the notes below
were observed in autumn 2026. Before writing "unavailable", try again and record the result.

Never get around a CAPTCHA, a "verifying your browser" page or any other access barrier. Such a page is not the
text of the act: the point is `not_verified`, the work goes on with a working conclusion (`version-check.md`).
Read an official page in this order: the Firecrawl tools if they are connected in this session (scrape the
official URL, no cache: `maxAge` 0); else the Firecrawl CLI if `tools/doctor.py` shows it logged in
(`firecrawl scrape <url> --format markdown --max-age 0 -o <matter>/work/sources/<act>-<date>.md`); else the host's
web tools; else the user's own browser after their yes. Each Firecrawl page costs the user one credit. Only public
official URLs go to Firecrawl, never document text or personal data. A page that is still an anti-bot check stays
"not verified". Firecrawl reads public pages; a page it returns as a challenge is not the act. A local
browser the user installed (for example Playwright with the system Chrome) also counts as the user's browser, or the
user opens the page and pastes the text. Firecrawl is connected by the user through its own sign-in; this skill
never reads, asks for, prints or stores a key.

## Moldova

| What | Where | Notes |
| --- | --- | --- |
| Consolidated texts, list of versions | [legis.md](https://www.legis.md/) — `cautare/getResults?doc_id=<id>&lang=ro` | Often refuses scripts (HTTP 403); a real browser usually works. Each `doc_id` is **one version**, not the act: a saved link keeps returning the old text. Versions are listed by date; the newest may be future |
| Official journal | [monitorul.gov.md](https://monitorul.gov.md/ro) — issue `/ro/monitor/<id>` | Plain HTTP usually works. The issue contents list amending laws (Part I), government decisions (II), authorities' acts (III). Scan the issues "held version → today" |
| Constitutional Court | [constcourt.md](https://www.constcourt.md/) | Decisions on constitutionality; also published in the journal |
| Supreme Court of Justice | [csj.md](https://csj.md/) | Explanatory decisions, advisory opinions, appeals in the interest of the law: check the binding force of each instrument in the procedure codes |
| Data protection authority | [datepersonale.md](https://datepersonale.md/) | Its normative decisions are also in the journal |
| Tax service, IT Park, consumer agency | [sfs.md](https://www.sfs.md/), [mitp.md](https://mitp.md/), [apc.gov.md](https://apc.gov.md/) | Orders and guides; a guide is not a normative act |

## Romania

| What | Where | Notes |
| --- | --- | --- |
| Consolidated texts | [legislatie.just.ro](https://legislatie.just.ro/) — `Public/DetaliiDocument/<id>` | "Istoric consolidări" and "Acte modificatoare". Was unreachable for weeks in autumn 2026; try again, then other routes |
| Archived copies of the portal | [Wayback Machine](https://web.archive.org/) — `web/<timestamp>id_/https://legislatie.just.ro/Public/DetaliiDocument/<id>`; lookup `https://archive.org/wayback/available?url=…` | Confirms the text on the copy date only; older than 14 days cannot prove the current version |
| Acts as published (official web service) | `http://legislatie.just.ro/apiws/FreeWebService.svc` (SOAP: `GetToken` → `Search` by year, number, text or title; 10 results a page; plain http) | Original form without consolidation. Good for finding amending acts: the text must say "… se modifică …"; a mere mention is not an amendment |
| Official journal | [monitoruloficial.ro](https://monitoruloficial.ro/) | Free access only to the last days of Part I; older issues through the portal |
| Legislative procedure | [senat.ro](https://www.senat.ro/), [cdep.ro](https://www.cdep.ro/) | Bills, approval laws of emergency ordinances (OUG), promulgation |
| Constitutional Court | [ccr.ro](https://www.ccr.ro/) | May show an anti-bot page; decisions are also in the official journal Part I |
| High Court (ÎCCJ) | [iccj.ro](https://www.iccj.ro/), [scj.ro](https://www.scj.ro/) | Appeals in the interest of the law (RIL) and preliminary rulings (HP) bind courts from publication in the journal |
| Authorities | [dataprotection.ro](https://www.dataprotection.ro/), [anpc.ro](https://anpc.ro/), [anaf.ro](https://www.anaf.ro/) | Decisions and orders; guides are not law |

## European Union

| What | Where | Notes |
| --- | --- | --- |
| Act record and consolidations | [EUR-Lex](https://eur-lex.europa.eu/) — `legal-content/RO/ALL/?uri=CELEX:<celex>`; consolidated `CELEX:0<year><type><number>-<YYYYMMDD>` | "Current consolidated version", "All consolidated versions", "Amended by", "Corrected by", "Date of effect". Scripts sometimes get an empty page (HTTP 202); a browser works. Consolidations have no legal force: the Official Journal text is authentic |
| The same data for scripts | [Cellar SPARQL](https://publications.europa.eu/webapi/rdf/sparql) (GET, `Accept: application/sparql-results+json`, no key) | Amendments, corrections, repeals, entry into force, case law interpreting the act; query below |
| Texts from Cellar | the `xhtml`/`html` manifestation of the language you need → `…/DOC_1` | Official Journal texts, consolidations and CJEU judgments |
| Court of Justice | [curia.europa.eu](https://curia.europa.eu/) | Judgments and ECLI; search by the cited article; quote the operative part verbatim |
| EDPB | [edpb.europa.eu](https://www.edpb.europa.eu/) | Guidelines: not law |

Amendments of an EU act (replace the CELEX number):

```sparql
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?p ?celex ?date ?eif WHERE {
  ?w cdm:resource_legal_id_celex "32016R0679"^^<http://www.w3.org/2001/XMLSchema#string> .
  ?s ?p ?w . ?s cdm:resource_legal_id_celex ?celex .
  OPTIONAL { ?s cdm:work_date_document ?date }
  OPTIONAL { ?s cdm:resource_legal_date_entry-into-force ?eif }
  FILTER(?p IN (cdm:resource_legal_amends_resource_legal, cdm:resource_legal_corrects_resource_legal,
                cdm:resource_legal_repeals_resource_legal, cdm:resource_legal_implicitly_repeals_resource_legal,
                cdm:resource_legal_derogates_resource_legal, cdm:resource_legal_completes_resource_legal))
} ORDER BY ?date
```

A correction (`…R(01)`) may concern one language only: check that it touches the language you cite.

## Related acts and case law: where to look

| Kind (`related[].kind`) | Moldova | Romania | EU |
| --- | --- | --- | --- |
| `government_decision` | HG in the journal; legis.md | HG in the journal Part I | — |
| `order` | ministries, tax service, agencies | ministries, ANAF, ANPC | — |
| `authority_decision` | data protection, consumer, central bank, IT Park | ANSPDCP, ANPC, BNR, ANCOM | Commission decisions (adequacy, standard clauses), implementing and delegated acts |
| `constitutional_court` | constcourt.md, journal | ccr.ro, journal Part I | — |
| `supreme_court` | CSJ: binding force per instrument (check the procedure codes) | ÎCCJ RIL and HP (binding from publication) | — |
| `cjeu` | guidance only (Moldova is not an EU member) | interpretation of transposed rules | interpretation of directives and regulations |
| `guidance` | guides, recommendations (`binding: false`) | the same | EDPB guidelines (`binding: false`) |

# Procedures

Each procedure is a checklist with an outcome. The outcome is one or more of: **D** — a document in `output/`
(through [documents.md](documents.md)); **M** — a measure the user takes (who, what, by when); **Q** — one question
to the user, options with the recommended one first. Working notes go to `<matter>/work/` and carry no personal
data: categories, counts, dates and channels only. Article references follow [law-map.md](law-map.md) and are read
on the task date before they carry a conclusion.

## 1. New website, form or channel

- [ ] Which firm runs it (a firm, not a brand) — it is the controller for what it collects.
- [ ] What is collected: form fields, hidden fields (campaign tags, click ids), chat and quiz text, payment data,
      recordings.
- [ ] Where it goes: hosting, e-mail, CRM, payment provider, analytics, advertising pixels, video calls. Each
      recipient's role (procedure 2) and country (procedure 3).
- [ ] The site is the user's: confirm the domain belongs to their firm before reading it (a typo or an example
      domain is someone else's site).
- [ ] Trackers before consent: load the page and each embedded frame with plain GET requests only (not through
      Firecrawl or any rendering service: it runs JavaScript and changes what loads; never submit a form, never
      click the banner) and look for tag managers, analytics and advertising scripts. Non-essential
      ones need consent first (Romania: Law 506/2004; Moldova: the rule found per the law map). This is a static
      screening: a script in the source may be blocked by the consent logic, and one loaded later by JavaScript
      is not seen. What really loads before consent, and whether refusal and withdrawal work, stays "not
      verified" unless the user gives evidence (screenshots, the browser's network log) or runs, or lets the agent
      run, a check in their own browser in a fresh session with no real data.
- [ ] The banner: accept and refuse equally easy, no pre-ticked boxes, the choice can be changed later (runtime
      behaviour: same evidence rule as above).
- [ ] A working link to the firm's current privacy notice near each form.

**Outcome:** D (notice, cookie text, banner wording) · M (remove a tracker, block scripts until consent; the user
or their web developer makes the change) · Q (who the operator is, when unclear).

## 2. Processor or DPA

- [ ] Role by fact: processor (hosting, e-mail, CRM, LMS), independent controller (bank, payment provider,
      accountant in their own capacity) or joint controller (an advertising pixel that serves both).
- [ ] The provider's legal entity and country (the contracting party, not the website), storage region, remote
      access.
- [ ] Where the DPA is: accepted in the account, part of the terms (version and date), signed, or none. None →
      write it as an open question with its risk.
- [ ] Content against art. 28(3): subject, duration, nature and purpose, data and people, documented instructions,
      confidentiality, security, sub-processors with authorisation, help with rights and breaches, deletion or
      return, audits.
- [ ] Sub-processors outside the EEA (or outside MD for a Moldovan exporter) → procedure 3.

**Outcome:** D (a DPA from model M06, or a list of edits to the provider's DPA) · M (accept the provider's DPA in
the account) · Q (a role that depends on how the user actually uses the service).

## 3. Transfer abroad

- [ ] Exporter (which firm, under which regime), recipient, country, whether the recipient decides itself.
- [ ] Is it a transfer at all? A foreign controller that collects directly from the person is first a question of
      who is covered (art. 3), not of the transfer chapter; the link between the two is to be checked, not assumed.
- [ ] GDPR exporter: an adequacy decision on the task date (for the US: is the recipient certified under the
      framework?) · else SCC 2021/914 with the module for the roles (model M07) and a transfer assessment · else an
      art. 49 derogation, which fits one-off or contract-necessary transfers, not a regular flow.
- [ ] Importer itself under GDPR by art. 3(2) (for example an EU processor sending data back to a Moldovan
      controller that sells to people in the EU): SCC 2021/914 are not meant for that case (recital 7 of the
      decision, *reported*); check the Commission's current position on the task date, do not conclude by default.
- [ ] L195 exporter: EEA recipient — free; else an adequacy decision of the Center · Commission or Center SCC
      without authorisation · other clauses only with authorisation.
- [ ] Transfer assessment: the recipient country's access-by-authorities law and practice, extra measures
      (encryption with keys kept by the exporter, pseudonymisation). Proportionate: short for low-risk data.
- [ ] One wording for the same transfer in every text (notice, DPA, assessment).

**Outcome:** D (SCC annexes, a transfer assessment, the transfer sentence of the notice) · M (switch the region,
encrypt) · Q (a fact about the recipient only the user can get).

## 4. DPIA screening

- [ ] Art. 35(3) criteria: systematic evaluation with profiling and decisions · special data or criminal data on a
      large scale · systematic monitoring of a public area.
- [ ] Other signs: children's data, health data, new technology (AI features of a provider), large-scale tracking.
- [ ] The authority's list (RO, MD) checked when found; it refines, it does not replace the criteria.
- [ ] A DPO question on the same facts (art. 37).

**Outcome:** a short screening note in `output/`: required · not required · not enough facts, with the reasons;
"required" → D (a DPIA proportionate to the risk) and Q (who carries it out, by when).

## 5. Data subject request

- [ ] Which firm is the controller for this person. Received as a processor → pass it to the controller, do not
      answer in its name.
- [ ] Which right: access, rectification, erasure, restriction, portability, objection, withdrawal of consent.
- [ ] Identity: ask for confirmation only when in reasonable doubt, and no more than needed.
- [ ] Deadline: received on day X → answer within one month; an extension of two more months is notified with the
      reason within the first month. Compute the dates and write them.
- [ ] Erasure is limited by legal retention (accounting, tax): name the rule after checking it; never promise
      "we delete everything".

**Outcome:** a request log in `work/` (date received, controller, right, deadline, status — no name or contact) ·
D (the reply) · the user sends it.

## 6. Data breach

The first message, before anything else: when the firm became aware (date and hour), the deadline (awareness +
72 hours, computed), and one question that decides the next step — usually "is it a risk to the people
affected?" with options.

- [ ] What happened, when it became known, which systems, which categories of data, roughly how many people and
      records. No personal data in the notes.
- [ ] Controller or processor. A processor informs the controller without undue delay (art. 33(2)); a deadline in
      the DPA is a contract term, not the law's.
- [ ] Controller: notify the authority within 72 hours of awareness unless the breach is unlikely to result in a
      risk; later only with the reasons for the delay. Moldova → the Center; Romania → ANSPDCP (lead authority by
      art. 56 only for a controller with an EU establishment). A controller with no EU establishment (a Moldovan
      firm under GDPR by art. 3(2)) has no lead authority: it notifies the authority of each Member State whose
      residents are affected, through its art. 27 representative where there is one (EDPB guidance, *reported*).
      Notification may be given in phases (art. 33(4)).
- [ ] People affected: only at high risk, unless art. 34(3) applies (encryption, later measures, disproportionate
      effort → public communication).
- [ ] Document every breach, notified or not (art. 33(5)).

**Outcome:** a breach note in `work/` · D (the notification text with art. 33(3) content, the message to people
when needed) · M (contain: passwords, access, recall the e-mail) · the user files and sends. Checking which
authority is competent never delays the 72-hour notification.

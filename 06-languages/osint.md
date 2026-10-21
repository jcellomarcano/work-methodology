# OSINT conventions: official baseline + typical house rules

## 1. Source and hierarchy

There is no single official OSINT style guide. The closest methodological standard is the Berkeley
Protocol on Digital Open Source Investigations (OHCHR and UC Berkeley Human Rights Center, 2022),
written for international criminal and human rights work, not for commercial analytics. Above it sits
binding law: the GDPR (Regulation (EU) 2016/679) for any personal data, and for Spanish property work
the Cadastre law (Real Decreto Legislativo 1/2004), which defines which cadastral data is protected.
RFC 9309 (Robots Exclusion Protocol) governs crawler behaviour, and it is a request from the site
owner, not a permission. Order when they collide: binding law, then the site's own rules
(robots.txt, terms of service), then the Berkeley Protocol for method, then the house rules below.

## 2. What the official guide says, verbatim

| Rule | Official text | Reading |
|---|---|---|
| Every step documented | "The steps of an open source investigation – from identification of relevant material through collection, analysis and reporting – should be consistently and clearly documented" (Berkeley Protocol, para. 25); "investigators should track their searches and record the pathways to relevant material, including the terms, operators and the search engines that led to that content" (Berkeley Protocol) | the search path is part of the evidence, not a scratch note |
| Minimum capture | "the first three items (uniform resource locator (URL), Hypertext Markup Language (HTML) source code and full-page capture) serve as a minimum standard for providing evidence in court" (Berkeley Protocol) | a finding without URL, raw HTML and a full-page capture is a lead, not evidence |
| Hash at collection | "At the point of collection, open source investigators should manually add – or the collection tool should automatically add – a hash value" (Berkeley Protocol) | integrity is fixed when the bytes arrive, never later |
| Data minimisation | "This principle favours itemized, manual collection over bulk, automated collection" (Berkeley Protocol, para. 31); "adequate, relevant and limited to what is necessary in relation to the purposes for which they are processed" (GDPR, Art. 5(1)(c)) | collect the fields the question needs, not the whole portal |
| Storage limitation | "kept in a form which permits identification of data subjects for no longer than is necessary for the purposes for which the personal data are processed" (GDPR, Art. 5(1)(e)) | identifying data has an expiry date set at design time |
| Location data is personal data | "an identifier such as a name, an identification number, location data, an online identifier" (GDPR, Art. 4(1)) | an exact address tied to a person is personal data, even when inferred |
| Public is not exempt | "from which source the personal data originate, and if applicable, whether it came from publicly accessible sources" (GDPR, Art. 14(2)(f)) | publicly accessible data still carries GDPR duties |
| Verification has three axes | "Verification is broken down into three separate considerations: the source, the digital item or file, and the content, which should be looked at collectively and compared for consistency" (Berkeley Protocol, para. 176) | a trusted portal does not make one listing's photo authentic |
| Source grading | "Source analysis is the process of assessing a source’s credibility and reliability" (Berkeley Protocol, para. 177) | the source is graded on its own, separately from the claim |
| No overstatement | "Analytical conclusions should not be exaggerated or overstated" (Berkeley Protocol, para. 30) | stated confidence never exceeds the evidence |
| robots.txt binds, but does not authorize | "If the crawler successfully downloads the robots.txt file, the crawler MUST follow the parseable rules"; "These rules are not a form of access authorization" (RFC 9309) | obey disallow; an allowed path is still subject to terms and law |
| Protected cadastral data | "tienen la consideración de datos protegidos el nombre, apellidos, razón social, código de identificación y domicilio de quienes figuren inscritos en el Catastro Inmobiliario como titulares, así como el valor catastral" (RDL 1/2004, Art. 51) | owner identity and cadastral value are off-limits without a legal basis; parcel and building data are not |

## 3. What the official guide does NOT say

- The Berkeley Protocol names no hash algorithm: it only says to choose "based on the currently
  accepted standard". The algorithm is a house decision.
- RFC 9309 defines no crawl rate, no `crawl-delay` and no request budget. Politeness limits are house
  rules.
- RFC 9309 says nothing about terms of service; the Berkeley Protocol notes (fn. 11) that breaching
  them "may result in being barred from using the website", which is a contract matter, not a crawler one.
- The GDPR does not say that scraping public personal data is lawful by default: a basis under Art. 6
  (typically legitimate interests, Art. 6(1)(f), with its balancing test) is still required.
- The Berkeley Protocol gives no numeric grading scale for sources or information. The two-axis
  NATO/Admiralty matrix (A-F, 1-6) is common practice, but no primary text of it was read for this
  document, so here it is a house rule, not a citation.
- None of these sources sets a confidence threshold for image geolocation, OCR or model-based
  inference, or says when a match is "confirmed". That threshold is the project's decision.
- The Cadastre law does not say a listing's surface, age or use must match the Cadastre: listing and
  Cadastre often disagree, and the disagreement is data, not an error to hide.

## 4. Typical house rules (labeled as such)

- **Every finding carries provenance**: URL, retrieval time in UTC, SHA-256 of the raw bytes, an
  archived copy (WARC or a public archive snapshot), tool name and version. No provenance, no finding.
- **Raw captures are immutable and append-only**: parsed and derived records reference the raw
  capture by hash; a re-parse creates a new record, it never edits the old one.
- **Observation and inference are separate fields**: "the map pin sits at the corner of two streets"
  is an observation; "the building is at number 12" is an inference that cites observation ids.
- **Two independent grades, not one score**: source reliability and information credibility are graded
  separately (an A-F / 1-6 style matrix, adopted as a house convention).
- **Corroboration before fact**: a claim becomes `confirmed` only with at least two independent
  sources. The same listing syndicated across several portals is one source, not three.
- **Confidence is explicit and closed**: a small enum (`confirmed`, `probable`, `candidate`,
  `unresolved`) plus the evidence ids behind it; never a bare float with no meaning attached.
- **Never invent a value**: when evidence is missing, the result is `unresolved` with a reason. No
  interpolated address, guessed cadastral reference or "most likely" street without its evidence.
- **Competing hypotheses stay ranked**: keep candidate locations with evidence for and against until
  one is confirmed; do not collapse to the first plausible answer.
- **PII minimisation by schema**: no owner names, phone numbers or protected cadastral data in storage;
  key on cadastral reference or building, not person. Faces and plates in facade images are blurred.
- **Purpose and retention in the run manifest**: each run declares its purpose and a retention period;
  a purge job enforces it, and the purge itself is logged.
- **Polite, honest crawling**: fetch and honor robots.txt, cache it at most 24 hours, treat an
  unreachable robots.txt as full disallow (RFC 9309, 2.3.1.4); fixed per-host rate limit with backoff;
  a truthful User-Agent; no login-walled content and no fake accounts.
- **Official open data before scraping**: when the Cadastre or an EU open data portal publishes the same
  fact through a documented service, use the service and record its version or download date.
- **Passive collection only**: no contacting advertisers or owners under a pretext to confirm a location.
- **Reproducible pipeline**: network access only at the capture stage; everything after runs from
  frozen snapshots, with pinned model versions and fixed seeds, so a rerun gives the same bytes.
- **Evidence over claims in reports**: every reported value links to its evidence ids; a value that
  cannot be traced back to a capture is removed, not softened.

## 5. How it's checked

| Rule | Cheap detector | Better detector |
|---|---|---|
| Provenance on every finding | schema check: non-null `url`, `retrieved_at`, `sha256`, `archive_ref` | `pydantic`/`jsonschema` gate in CI over every output record |
| Capture integrity | `sha256sum` recomputed over stored raw bytes | WARC files (`warcio`) plus RFC 3161 trusted timestamps (`openssl ts`) |
| Observation vs inference | grep of inference records without cited observation ids | test that rejects any inference whose evidence list is empty |
| Corroboration and independence | count of distinct sources per `confirmed` claim | dedup of syndicated listings by image hash before counting sources |
| No invented values | test with a fixture missing evidence, expecting `unresolved` | golden set of real cases with known locations, scored per release |
| PII minimisation | grep for owner, phone and DNI-like fields in schemas and dumps | Microsoft Presidio scan over stored text in CI |
| Retention | purge job dry-run listing expired rows | scheduled purge with an audit log and an alert on failure |
| robots.txt and rate limits | `urllib.robotparser` check before each fetch | Google's open-source `robotstxt` parser plus per-host rate metrics |
| Reproducibility | rerun from snapshot and diff the output bytes | versioned golden outputs compared in CI |

## Sources

- https://www.ohchr.org/sites/default/files/2024-01/OHCHR_BerkeleyProtocol.pdf
- http://publications.europa.eu/resource/celex/32016R0679 (official GDPR text, EU Publications Office)
- https://www.rfc-editor.org/rfc/rfc9309.txt
- https://www.boe.es/buscar/act.php?id=BOE-A-2004-4163

## Verdict

OSINT has a method standard (the Berkeley Protocol) and a legal frame (GDPR, the Cadastre law, RFC
9309), but no single guide tells an analytics pipeline what a "confirmed" location is. That gap is
closed by house rules: provenance and hashes on every capture, observation kept apart from inference,
two-axis grading, corroboration by independent sources, and `unresolved` instead of an invented value.

# Study CERT-V2: certificate format version 2, designed

STATUS: a design study, 2026-10-02. This is parcel CV2 of the step-6 round
(docs/ROADMAP.md, "Step 6: the math library, revision 8 and programs past
one tile (plan of record, 2026-10-02)", its bullet "Certificate format
version 2"). **Nothing here is built, and no format is fixed.** The
design goes to the lead, and through the lead to Logan, before version 2
is built. [CERTIFICATES.md](../CERTIFICATES.md) is unchanged: version 1
stays the contract until version 2 is approved and built. This file and
its row in docs/README.md are the only changes the study made.

Every statement below is one of four kinds, and says which:
- **READ**: from this tree, with the file named; or from a public page,
  with the page and the clause or section named (section 2 says what was
  read and how);
- **MEASURED**: from one of the two read-only probes run for this study
  on 2026-10-02 (sections 8.2 and 8.4);
- **PROPOSED**: this study's design. Every line, word, rule and refusal
  name of version 2 is a proposal for the lead and Logan, not a decision;
- **BELIEVED**: reasoning not tested here, marked where it stands.

Revision 8's names come from parcel R8's design. It is committed as
59b19e6 on branch s6-r8, unmerged and under the lead's review (R8's
ledger, 2026-10-02 10:56). The lead asked this design to use its
encodings:
- control codes 12 to 14 (`QUIET`, `ENDQUIET`, `RAISE`);
- CAPS2[13] for the per-lane block, and CAPS2[14] for flag control;
- MODE[24] asks for the block;
- STATUS[6] is `CFT_STATUS_MARKED`;
- ABI 0.17 appends `lane_flags` and `lane_flags_bytes` to
  `cft_run_args`;
- PROG_RUN_EX's word `want` carries the block's request over the remote
  protocol;
- the model's `Result.lane_flags` is computed for every run.

If those change, the names below change with them. The design does not
depend on their values.

The lead decided version 1's part on 2026-10-02 (R8's question 3). A run
with a marked lane is certified under version 1 as its STATUS says:
STATUS[6] set, and re-derived by the audit. It is not refused. A
version-1 certificate records what the image computed.

## Contents

1. Why, in the plan's words
2. The survey: what certificates and provenance records carry
3. What version 1 already carries, in those terms
4. Four rules for deciding a field
5. The field table
6. Item 1: the per-lane flags
7. Item 2: a marked lane and its replay
8. Item 3: a source, and a wider run compiled from it
9. The provenance lines
10. The detached signature
11. Version 2's lines, in order
12. The audit in version 2
13. Compatibility, and what each implementation needs
14. The controls
15. What version 2 still does not do
16. Questions for Logan, with recommendations
17. Sources

---

## 1. Why, in the plan's words

The plan of record (READ, ROADMAP.md, step 6, part 1) has version 2
"designed once, with R8L, for everything this step needs of it". It
names four needs:

1. **The per-lane flags.** R23 (SEQUENCER.md) gives a run one byte a
   lane, and says "a run that asked for the block has an output its
   certificate must cover, as it covers the counts, or name as absent".
   Version 1 records one flag word and one STATUS word for each segment.
2. **A marked lane.** R8F's raise carries "the mark for a lane whose last
   bit a routine could not decide". M1 makes "An in-lane test of whether
   the last bit is decided. A lane that is not is marked through R8F's
   raise and replayed, as certificate version 2's design says." The plan
   asks "where it is replayed (the golden model on the host, or a slower
   image) and how the replay is recorded".
3. **Format-specific images.** Version 1's wider run must have "the same
   instruction words" as the main run (CERTIFICATES.md, "Auxiliary runs",
   `aux-image`). A routine's words differ by format: divfull is 210 to 216
   instructions across the four formats (part D of the round's survey,
   1.3). cft-orbits already refuses `--cert-accuracy wider` for this
   reason: "Kepler fp128's image is 47 instructions to fp64's 39"
   (ORBITS.md, "Certified runs"). With this need comes the question of
   whether a certificate names its source. Step 3 left out "a certificate
   that names its source" (ROADMAP.md, step 3, "What it is not").
4. **Scientific provenance.** Logan, 2026-10-02, verbatim: "In regards to
   the V2 certificate, also include more 'scientific provenance' areas,
   things typical certificates in the field carry for traceability etc".

## 2. The survey: what certificates and provenance records carry

Everything here was read on 2026-10-02, through a web search tool or a
page fetch. Nothing was downloaded or kept. **Page** means I read the
page itself. **Search** means I read only the text a search result
returned; those pages were PDFs, and I did not open them. ISO/IEC
17025:2017 is not public, so every clause of it below comes through a
secondary source, and is marked as such. Section 17 lists every page.

### 2.1 Calibration and test certificates: ISO/IEC 17025:2017, and PTB's DCC

**7.8.2.1, what every report carries** (test report, calibration
certificate, sampling report). Each item was read by its letter in Heather
A. Wade, "How to Read & Interpret ISO/IEC 17025 Calibration
Certificates", Quality Magazine, 2024-09-03 (page), which paraphrases
them:
- a) a title;
- b) the laboratory's name and address;
- c) the location where the activity was performed;
- d) "unique identification that all its components are recognized as a
  portion of a complete report and a clear identification of the end"
  (search);
- e) the customer;
- f) the method;
- g) the item, unambiguously identified, and its condition;
- h) the date of receipt;
- i) the date(s) of performance;
- j) "the date of issue of the report" (search);
- k) is not among the items the article gives;
- l) "a statement to the effect that the results relate only to the items
  tested" (European co-operation for Accreditation, FAQ 42.1, page);
- m) the results, with units;
- n) additions to, deviations from or exclusions from the method;
- o) "identification of the person(s) authorizing the report" (search);
- p) results from external providers, identified as such.

**Other 17025 clauses:**
- **7.8.2.2** (search only): information supplied by the customer is
  identified as such, with a disclaimer where it can affect the
  validity of the results.
- **7.8.4.1, what a calibration certificate adds** (Quality Magazine,
  page, by letter):
  - a) the measurement uncertainty;
  - b) "the conditions (e.g., environmental) under which the calibrations
    were made that have an influence on the measurement results"
    (wording: search);
  - c) a statement identifying how the measurements are metrologically
    traceable;
  - d) the results before and after any adjustment or repair;
  - e) conformity;
  - f) opinions and interpretations.
- **6.5, metrological traceability**, after the VIM (JCGM's International
  Vocabulary of Metrology), entry 2.41: "Property of a measurement result
  whereby the result can be related to a reference through a documented
  unbroken chain of calibrations, each contributing to the measurement
  uncertainty" (jcgm.bipm.org, page). CASRAI's guide gives 6.5 the same
  chain (page).
- **7.8.8, amendments:**
  - 7.8.8.1: "When an issued report needs to be changed, amended or
    re-issued, any change of information shall be clearly identified
    and, where appropriate, the reason for the change included in the
    report" (EA, FAQ 45.2, page);
  - 7.8.8.3: a complete new report "shall be uniquely identified and
    shall contain a reference to the original that it replaces"
    (search).
- **7.8.1.3** (search only): when agreed with the customer, results may
  be reported in a simplified way. Any information of 7.8.2 to 7.8.7
  left out of the report "shall be readily available".

**PTB's Digital Calibration Certificate (DCC)** is a 17025 certificate
written as data: "a flexible, machine-readable, modular and standardized
XML schema developed to support the digitalization of calibration
processes according to ISO/IEC 17025" (dmet.ptb.de/dcc, page). Its schema,
version 3.0.0 (the schema's generated documentation, page):
- **The top level.** `administrativeData` holds `dccSoftware`, `coreData`,
  `items`, `calibrationLaboratory`, `respPersons`, `customer` and
  `statements`. `measurementResults` sits beside it.
- **`coreData`** holds:
  - country and language codes;
  - a `uniqueIdentifier`;
  - `identifications`;
  - `receiptDate`, `beginPerformanceDate` and `endPerformanceDate`;
  - `performanceLocation`;
  - `previousReport`, typed `dcc:hashType`. The amendment link is a hash.
- **A responsible person** carries `cryptElectronicSeal`,
  `cryptElectronicSignature` and `cryptElectronicTimeStamp`.
- The children of one measurement result were not in the part of the
  schema I read, so I do not cite them.

**What they carry, together:**
- who issued and who authorised;
- one identifier for the whole, and a marked end;
- when the work was performed, and when the report was issued;
- where the work was done;
- the method and the item;
- the results with their uncertainty, and the conditions that influence
  them;
- the traceability chain;
- a before and after for an adjustment;
- an amendment that names the report it replaces, by identifier (and, in
  the DCC, by hash);
- a rule that anything left out of a simplified report stays available.

### 2.2 W3C PROV

**PROV-DM** (W3C Recommendation, 30 April 2013; page). Its core
structures are in 2.1, and its three core types are defined in 5.1.1,
5.1.2 and 5.3.1:
- an **Entity** is "a physical, digital, conceptual, or other kind of
  thing with some fixed aspects";
- an **Activity** is "something that occurs over a period of time and
  acts upon or with entities";
- an **Agent** is "something that bears some form of responsibility for
  an activity taking place, for the existence of an entity, or for
  another agent's activity".

Its relations:
- Generation (5.1.3), Usage (5.1.4), Communication (5.1.5), and Start and
  End (5.1.6, 5.1.7);
- Derivation (5.2.1), and Revision (5.2.2);
- Attribution (5.3.2);
- Association (5.3.3), which may carry a **Plan**, "an entity that
  represents a set of actions or steps intended by one or more agents to
  achieve some goals";
- Delegation (5.3.4).

A **Bundle** (5.4) "is a named set of provenance descriptions, and is
itself an entity, so allowing provenance of provenance to be expressed".

**PROV-O** (the same date; page). Section 3.1, "Starting Point Terms",
lists:
- the classes `prov:Entity`, `prov:Activity` and `prov:Agent`;
- the properties `wasGeneratedBy`, `used`, `wasInformedBy`,
  `startedAtTime`, `endedAtTime`, `wasDerivedFrom`, `wasAttributedTo`,
  `wasAssociatedWith` and `actedOnBehalfOf`.

Section 3.3, "Qualified Terms", holds `prov:hadPlan`.

PROV also carries a place:
- Section 3.2 of PROV-O, "Expanded Terms", holds the class
  `prov:Location`: "A location can be an identifiable geographic place
  (ISO 19112), but it can also be a non-geographic place such as a
  directory, row, or column" (page).
- It also holds the property `prov:atLocation`, for an Activity, Entity,
  Agent or InstantaneousEvent (page).
- PROV-DM's attribute `prov:location` (5.7.2.2) is "an optional attribute
  of Entity, Activity, Agent, Usage, Generation, Invalidation, Start,
  and End" (search; the page fetch stopped before section 5.7).

**What it carries:** a graph. It records which entities each activity
used and generated, which entity was derived from which, which agent was
responsible and under which plan, when each activity started and ended,
and where, as a location.

### 2.3 Build provenance: SLSA, in-toto, DSSE, and reproducible builds' build-info

**SLSA provenance v1.0** (slsa.dev, page). Its `predicateType` is
`https://slsa.dev/provenance/v1`.
- `buildDefinition` holds:
  - `buildType`, required: "the template for how to perform the build and
    interpret the parameters and dependencies";
  - `externalParameters`, required: parameters "under external control";
  - `internalParameters`;
  - `resolvedDependencies`: "artifacts needed at build time".
- `runDetails` holds:
  - `builder.id`, required: "URI indicating the transitive closure of the
    trusted build platform";
  - `builderDependencies`: "Dependencies used by the orchestrator that
    are not run within the workload and that do not affect the build,
    but might affect the provenance generation or security guarantees";
  - `version`: "Map of names of components of the build platform to
    their version";
  - `metadata`: `invocationId`, `startedOn` and `finishedOn`;
  - `byproducts`.
- Its "Migrating from 0.2" table maps v0.2's `invocation.parameters` to
  `externalParameters`, `invocation.environment` to `internalParameters`,
  `materials` to `resolvedDependencies`, and `buildStartedOn` and
  `buildFinishedOn` to `startedOn` and `finishedOn`. It removes
  `completeness` and `reproducible`.
- `externalParameters` "MUST be complete at SLSA Build L3".

**SLSA provenance v0.2** (page) had two claims that v1.0 removed:
- `metadata.completeness`: "If true, the builder claims that
  invocation.parameters is complete";
- `metadata.reproducible`: "If true, the builder claims that running
  invocation on materials will produce bit-for-bit identical output".

**The in-toto attestation framework v1** (the in-toto/attestation
repository, `spec/v1`: its README, `statement.md` and `envelope.md`;
pages):
- its layers: an Envelope, a Statement and a Predicate, and a Bundle
  that groups attestations;
- the Statement has `_type` (`https://in-toto.io/Statement/v1`),
  `subject` (each "MUST have `digest` set"), `predicateType` and
  `predicate`;
- for the envelope, DSSE is "RECOMMENDED".

**DSSE** (`protocol.md`, page) signs PAE(type, body) = "DSSEv1" SP
LEN(type) SP type SP LEN(body) SP body. The payload's type is signed with
the payload.

**deb-buildinfo(5)** (Debian's manual page, page) records:
- the source and the binaries, with their checksums;
- `Build-Origin`, `Build-Architecture` and `Build-Date`;
- `Build-Kernel-Version` and `Build-Path`;
- `Build-Tainted-By`, as reason tags;
- `Installed-Build-Depends`;
- `Environment`: "environment variables that are known to affect the
  package build process".

Two of its fields are written only on request, "to avoid leaking
possibly sensitive information": `Build-Kernel-Version`, and `Build-Path`
by the vendor's pattern.

**SOURCE_DATE_EPOCH**, revision 1.1 (reproducible-builds.org, page):
"Build processes MUST use this variable for embedded timestamps in place
of the 'current' date and time". A wall-clock time embedded in an output
makes the output unreproducible.

**What they carry:**
- who built, as a builder identity;
- how, as a build type;
- from what: parameters complete enough to rebuild, and resolved
  dependencies with their digests;
- in what environment;
- when: start and finish;
- the outputs, by digest;
- a claim (v0.2) or a level (v1.0) about completeness and
  reproducibility;
- a signature envelope;
- where privacy asks for it, fields left out unless requested.

### 2.4 Research objects and identifiers: RO-Crate, CodeMeta, DataCite, SWHID

**RO-Crate 1.1** (pages):
- the root data entity carries `datePublished`, which "MUST be a string
  in ISO 8601 date format", and a `license`, which "SHOULD link to a
  Contextual Entity";
- "Provenance of entities": the software that made a file is the
  `instrument` of a `CreateAction`. The action has `object`, `result`,
  `agent`, `startTime`, `endTime` and `actionStatus`.

**The Workflow Run Crate profiles, version 0.6** (pages):
- **Process Run Crate.** In a `CreateAction`:
  - `instrument` MUST be given;
  - `agent`, `result` and `endTime` SHOULD be;
  - `object`, `startTime`, `actionStatus` and `error` MAY be.

  The software has a `softwareVersion`. Environment variables are given
  through an `environment` property that points to `PropertyValue`s.
- **Workflow Run Crate.** The workflow is a `ComputationalWorkflow`. Its
  inputs are `FormalParameter`s, with `name`, `description` and
  `additionalType`. A value used in a run refers to the parameter it
  fills by `exampleOfWork`.
- **Provenance Run Crate** adds the execution of each step.

**CodeMeta** (its terms page, versions 2 and 3; page) defines:
- `identifier`, `version` and `softwareVersion`, `codeRepository` and
  `license`;
- `author`, `contributor` and `maintainer`, with an ORCID "ideally" for a
  person;
- dates, `programmingLanguage`, `runtimePlatform` and
  `softwareRequirements`;
- `referencePublication`, `funding` and `citation`.

**The DataCite Metadata Schema, version 4.6** (pages):
- mandatory properties: Identifier, Creator, Title, Publisher,
  PublicationYear and ResourceType;
- recommended: Subject, Contributor, Date, RelatedIdentifier, Description
  and GeoLocation;
- optional: Rights, Version, FundingReference and others.

Its relation types include:
- `IsCompiledBy` and `Compiles`: "B is used to compile or create A";
- `IsDerivedFrom` and `IsSourceOf`;
- `Obsoletes` and `IsObsoletedBy`;
- `Reviews` and `IsReviewedBy`.

**SWHID**, the SoftWare Hash IDentifier, specification version 1.2,
published on 2025-04-23 as ISO/IEC 18670:2025 (swhid.org, and its Clause
5, "Core Identifiers"; pages):
- SWHIDs are "persistent, intrinsic identifiers for software source code
  artifacts";
- a content's identifier is the SHA-1 of "blob", a space, its length in
  decimal, a NUL and its bytes. That is git's blob id, a compatibility
  the specification calls "practical, but incidental".

**What they carry:**
- identifiers: intrinsic (a SWHID), or registered (a DOI);
- creators, with persistent identifiers for persons;
- a publication date and a licence;
- the software and its version, as the instrument of a run;
- the run's inputs, linked to the parameters they fill;
- the run's environment variables, start and end;
- typed relations between objects: compiled by, derived from, replaces.

### 2.5 Reproducibility certificates and badges: cascad, CODECHECK, ACM

**cascad** (cascad.tech, page) is "the first certification agency for
scientific code and data". A reviewer "executes your code" in a clean
environment, blinded from the authors, and grades the result (for example
"RRR"). The page does not say what the published certificate records, so
I do not cite it for that.

**CODECHECK's configuration file 1.0** (its specification, page) is
`codecheck.yml`. It records:
- a `manifest` of the output files that were checked;
- the `codechecker`, by name and ORCID;
- `report`: a URL or DOI identifying the published certificate;
- the `paper`, a `summary` and the `repository`;
- `check_time`;
- a `certificate` identifier;
- the `source` of the checked material.

**ACM's "Artifact Review and Badging"**, version 1.1. SIGIR's copy dates
it 20 August 2020, and ETAPS's 24 August 2020. acm.org refused the fetch
(HTTP 403, twice), so I read its badges through copies:
- **Results Reproduced** (SIGIR's reproduction of the policy, page): the
  main results "obtained in a subsequent study by a person or team other
  than the authors, using, in part, artifacts provided by the author";
- **Results Replicated** (the same page): the same "without the use of
  author-supplied artifacts";
- **Artifacts Available**, in ACM's words: "Author-created artifacts
  relevant to this paper have been placed on a publicly accessible
  archival repository. A DOI or link to this repository along with a
  unique identifier for the object is provided." This is from search
  results, reproduced on conference pages that give it as ACM's; the
  WNS3 2024 artifacts page (page) is one. ACM asks for a DOI or a link.

Two copies differ from ACM here:
- SIGIR has no standalone Artifacts Available badge. It says "we can
  merge the Artifacts Evaluated - Reusable and Artifacts Available into
  a single badge" (page).
- ETAPS's badges are "based on the ACM Artifact Review and Badging
  recommendations (version 1.1 of August 24, 2020)". Its own Available
  criterion is stricter: a repository that "assigns DOIs to its
  entries" (page).

ACM swapped the two Results terms in August 2020 to align with NISO
(search). NISO's RP-31-2021, "Reproducibility Badging and Definitions",
was published on 2021-01-28 (search).

**What they carry:**
- who checked, and when;
- the manifest of outputs that were compared;
- the outcome;
- a certificate identifier, with a citable report;
- a graded vocabulary for how independent the check was.

### 2.6 Signatures and time

**RFC 8032** (January 2017, page) defines EdDSA:
- "The use of a unique random number for each signature is not required"
  (section 1);
- section 7.1, "Test Vectors for Ed25519";
- keys are 32 octets, and signatures 64.

**OpenSSH's `PROTOCOL.sshsig`** (page) defines detached signatures made
with SSH keys:
- the signed blob is "SSHSIG", a namespace, a reserved string, a hash
  algorithm (sha256 or sha512) and H(message);
- the namespace "prevents cross-protocol attacks".

**RFC 3161** (August 2001, page): "A time-stamping service supports
assertions of proof that a datum existed before a particular time"
(section 1). Its TSTInfo (2.4.2) holds a `messageImprint`, a `genTime`, a
`serialNumber` and the time-stamping authority's name.

**RFC 3339** (July 2002, page) defines `date-time` as a full date, `T`,
and a full time with an offset that may be `Z` (5.6). "T" and "Z" "may
alternatively be lower case", and a second may be 60 at a leap second
(5.7).

### 2.7 What such records carry, side by side

| what | 17025 / DCC | PROV | SLSA / in-toto / build-info | RO-Crate / CodeMeta / DataCite | cascad / CODECHECK / ACM |
|---|---|---|---|---|---|
| an identifier for the record | 7.8.2.1 d); `uniqueIdentifier` | an entity's identifier | `invocationId`; subject digests | Identifier; `@id` | certificate id; report DOI |
| who is responsible | b), o); `respPersons` | Agent; Attribution | `builder.id` | author; Creator | codechecker |
| when | i), j); `beginPerformanceDate`, `endPerformanceDate` | `startedAtTime`, `endedAtTime` | `startedOn`, `finishedOn`; `Build-Date` | `startTime`, `endTime`; `datePublished` | `check_time` |
| where | c); `performanceLocation` | `prov:atLocation`, `prov:Location`; `prov:location` | `Build-Origin`, `Build-Architecture` | (none) | (none) |
| the method, the plan | f) | Plan; Association | `buildType` | `ComputationalWorkflow` | (none) |
| the inputs | g), the item | Usage | `externalParameters`, `resolvedDependencies` | `object`; `FormalParameter` | the manifest |
| the environment, the conditions | 7.8.4.1 b) | (none) | `internalParameters`; `Environment` | `environment` | a clean environment |
| the tools and their versions | `dccSoftware` | Agent (software) | `builder.version`, `resolvedDependencies`; `Installed-Build-Depends` | `instrument` with `softwareVersion` | (none) |
| the results and their uncertainty | m); 7.8.4.1 a) | Generation | subject; `byproducts` | `result` | the outcome; the grade |
| traceability | 7.8.4.1 c); VIM 2.41 | Derivation | dependencies by digest | `IsDerivedFrom`, `IsCompiledBy` | (none) |
| before and after an adjustment | 7.8.4.1 d) | Revision | (none) | (none) | (none) |
| amendments | 7.8.8; `previousReport` (a hash) | Revision | (none) | `Obsoletes` | (none) |
| a signature | `cryptElectronicSignature` | a Bundle, attributed | DSSE envelope | (none) | (none) |
| a licence, a contact | e), the customer | (none) | (none) | `license`; `contactPoint` | (none) |
| left out for privacy | 7.8.1.3, "readily available" | (none) | written only on request | (none) | (none) |

## 3. What version 1 already carries, in those terms

Version 1 (READ, CERTIFICATES.md) is strong where these records are weak.
It is silent where they are strong.

- **The entities and their chain, checked.**
  - The certificate names the image, the bank, the streams and every
    boundary state by digest. Each segment is an activity that used a
    start state and generated an end state, and continuity makes the
    chain unbroken. In PROV's terms that is Usage, Generation,
    Communication (segment to segment) and Derivation.
  - An audit re-derives all of it by re-running segments on an
    implementation the producer does not control. That is more than
    SLSA asks. SLSA requires `externalParameters` to be "complete at
    SLSA Build L3", and trusts the build platform for it. Here
    completeness is shown: a re-run reproduces the bits from what the
    certificate names and nothing else, segment by segment.
  - SLSA v0.2's `reproducible`, "bit-for-bit identical output", is a
    claim there. Here it is the audit.
- **The method,** as the program. The image digest is the plan the device
  carried out: PROV's `hadPlan`, SLSA's `buildType` together with
  `externalParameters`.
- **The results, and the kind of their uncertainty.** States by hash,
  flags and STATUS, and accuracy entries labelled measurement, estimate
  or bound. The kinds are 7.8.4.1 a)'s uncertainty, stated honestly.
- **The tools and the equipment, as statements:** build-id, backend, the
  device image's digest, VERSION, CAPS and the tile count. Each is
  "stated, not checked, or unknown". One of them, CAPS2's scratch depth,
  is read by the re-runs.
- **Nothing about agents, times or places.** Version 1 records no issuer,
  time, host or environment, no identifier but the body's hash, no
  signature (one is reserved), no amendment and no source.

So version 2 adds agents, times, places, the source, the compiler and the
environment. It keeps every addition that cannot change the bits outside
what the audit checks, and makes checks of the few that can be
re-derived.

## 4. Four rules for deciding a field

PROPOSED.

1. **Checked, read or reported.** A field is:
   - **CHECKED** when an auditor can re-derive it from what it is handed:
     by a re-run, a recompile, a regeneration or a signature check;
   - **READ** when the audit's arithmetic takes it as given, so a false
     value fails its own re-run. Version 1's CAPS2 depth is the
     precedent;
   - **REPORTED** otherwise: "stated, not checked".

   Every field says which.
2. **Absence has three words.** Version 1 has two:
   - `unknown`: not recorded;
   - `none`: the field does not exist for this backend.

   Version 2 adds a third:
   - `withheld`: the producer has the value and chose not to publish it.

   Precedents: 17025's simplified report, whose unreported information
   "shall be readily available" (7.8.1.3, search), and deb-buildinfo's
   fields written only on request (page).
3. **Identify the run, not the person.** Some fields cannot change the
   bits, and identify a person or a person's machine:
   - some are written only if the owner asks: the issuer, and the
     device's serial;
   - others are not carried at all: the host name, the user name, the
     CPU model, and paths.

   The keyed mode protects states, as in version 1. It protects no
   provenance line: each one is either published or withheld.
4. **Reproducible bytes stay reproducible.** SOURCE_DATE_EPOCH's lesson
   is that a time inside an output makes the output unreproducible.
   - In version 1, a run block is a function of what ran. The conformance
     rule and the writer gates compare run blocks byte for byte.
     build-id is the one statement that varies from build to build, and
     the corpus check normalizes it.
   - Version 2 puts every statement in the header, before `runs`: the
     identity, the provenance, the definition's version, and how the
     replays were made (the `replay-method` lines). Some of these two
     writers of one run make differently; the rest they must make alike.
   - A run block holds only three kinds of thing: what ran, what the
     definition computes, and what every writer is handed alike. The
     source's name is one of the last kind: it is the name of the file
     both writers are handed.
   - The gates follow: the corpus check and the writer gates
     (segrun_check, and the corpus check's remake by cft-segrun)
     normalize only the lines that must differ, as they normalize
     build-id today. Those are `build-id`, `writer`, `writer-runtime`,
     `compiler-build`, the `replay-method` lines, the three times,
     `host-os`, `host-arch` and the environment.
   - The gates hold every other line byte for byte:
     - `mode` and `salt-commitment`, as version 1's check does;
     - `profile` and `language`, so that each writer's definition is
       held to the golden model's;
     - `initial`, `supersedes`, the identifier, and the issuer and its
       key, which both writers are handed alike;
     - the device lines, which the gates fix to the software backend;
     - everything from `runs` on.
   - So a replay certificate written in C (`replay-method 0 image
     <digest>`) is held to the golden writer's (`replay-method 0
     golden`) by its run blocks, which must agree.

## 5. The field table

PROPOSED, field by field. The columns:
- **carried**: whether version 2 carries the field;
- **line**: the line that carries it (section 11 gives the order);
- **audit**: CHECKED, READ or REPORTED (section 4);
- **absent as**: the words allowed when there is no value;
- **privacy**: what publishing it costs.

**Version 1's own fields, and their changes.**

| field | from the survey | carried | line | audit | absent as | privacy |
|---|---|---|---|---|---|---|
| the certificate's own name: the body's hash | 17025 7.8.2.1 d); an intrinsic id, like a SWHID | yes, as in version 1 | `hash` | CHECKED (integrity), and printed in the verdict as the certificate's name | never absent | none |
| the image, bank, streams and states; flags and STATUS | SLSA subject and parameters; PROV usage and generation | yes, as in version 1 | the run block | CHECKED (re-runs) | (none) | as version 1 |
| the steps in a segment | SLSA `externalParameters` | yes, as in version 1 | `steps` | REPORTED; CHECKED when a compiler is named or a definition re-run is made | (none) | none |
| the library build | SLSA `resolvedDependencies`; CodeMeta `softwareVersion` | yes, as in version 1 | `build-id` | REPORTED | `unknown` | none |
| the backend; the device image, VERSION, CAPS and tiles | DCC `measuringEquipments` | yes, as in version 1 | `backend`, `device-*` | REPORTED; CAPS2's depth READ | `none`, `unknown` | none |
| the results' uncertainty | 17025 7.8.2.1 m), 7.8.4.1 a) | yes, as in version 1, plus `wider-source` | the accuracy entries, with their kinds | CHECKED | (none) | as version 1 |

**Version 2's new fields.**

| field | from the survey | carried | line | audit | absent as | privacy |
|---|---|---|---|---|---|---|
| an issuer-assigned identifier | DCC `uniqueIdentifier`; CODECHECK `certificate`; DataCite Identifier | yes | `certificate-id` | REPORTED | `none` | the owner's choice |
| the issuer | 17025 b), o); DCC `respPersons`; PROV Attribution; CODECHECK codechecker | yes, opt-in | `issuer` | REPORTED; CHECKED with a signature and a keyring | `none`, `withheld` | personal data: written only if the owner asks |
| the signing key | DCC `cryptElectronicSignature`; DSSE; SSHSIG | yes | `issuer-key`, and the detached file | CHECKED (the signature) | `none` | a public key is a pseudonym |
| when the runs started and finished | 17025 i); DCC performance dates; SLSA `startedOn`, `finishedOn`; PROV; RO-Crate | yes | `started`, `finished` | REPORTED | `unknown` | low |
| when it was issued | 17025 j) | yes | `issued` | REPORTED (an RFC 3161 token could bound it from above; not in version 2) | `unknown` | low |
| where: the host's OS and architecture | 17025 c); deb-buildinfo `Build-Architecture` | yes | `host-os`, `host-arch` | REPORTED | `unknown`, `withheld` | low |
| the host name, the user name, the CPU model, paths | deb-buildinfo (`Build-Path` and the kernel only on request) | **no** | (none) | (none) | (none) | personal data, or a fingerprint; none of them can change the bits |
| the writer, and its runtime | SLSA builder; RO-Crate `instrument` with `softwareVersion` | yes | `writer`, `writer-runtime` | REPORTED | `unknown`; `none` | none |
| the mpmath version | transcend.py decides every non-exact transcendental through mpmath's interval context | yes, where the definition was evaluated | in `writer-runtime` (the writer's); in the verdict's header (the auditor's) | REPORTED | `none`: the definition was not evaluated | none |
| the definition's version: the conformance profile, extended to the program model, and the language | CONFORMANCE.md, "Versioning"; 17025 f), the method | yes | `profile`, `language` | REPORTED, and used to name a failure's cause: the audit compares them with its own (section 7.6) | `unknown`; `none` for `language` where no run names a source | none |
| the compiler's name, output version and target | DataCite `IsCompiledBy`; SLSA `buildType` | yes, per run | `compiler` | CHECKED (a recompile) | `none` (not compiled) | none |
| the compiler's build | SLSA `resolvedDependencies`: "artifacts needed at build time" (the compiler runs, and its output is the image) | yes | `compiler-build` | REPORTED | `none`, `unknown` | none |
| the source | SLSA's `source` parameter; SWHID; PROV Derivation | yes, per run | `source`, `source-name` | CHECKED: the digest and the language; the name REPORTED | `none` | the digest is unkeyed, so it confirms a guessed source |
| the system's identity: the step graph | PROV Plan | yes, with a source | `graph` | CHECKED (the language) | (none) | as the source |
| the run values of the source's params | Workflow Run Crate `FormalParameter` with `exampleOfWork`; SLSA `externalParameters` | yes, with a source | `source-param` | CHECKED (a recompile, or the definition) | a count of 0 | as the source |
| what the params mean, as text | Workflow Run Crate `description` | **no**: the source carries it | (none) | (none) | (none) | (none) |
| how the initial state was made | SLSA `externalParameters`; version 1's `parameter members` lines, used informally | yes | `initial` | CHECKED where the auditor knows the generator, else REPORTED | `given` | a generator publishes boundary 0, even in a keyed certificate |
| the device's platform, XRT version and clock | 17025 7.8.4.1 b), the conditions; deb-buildinfo `Installed-Build-Depends` | yes | `device-platform`, `device-xrt`, `device-clock` | REPORTED | `none`, `unknown` | none |
| the device's serial number | DCC `items` and `identifications`; 17025 g) | yes, opt-in | `device-serial` | REPORTED | `none`, `unknown`, `withheld` (the default) | a hardware id that can be linked to its owner |
| the environment variables | deb-buildinfo `Environment`; SLSA `internalParameters`; Process Run Crate `environment` | yes | `environment`, `env` | REPORTED | an empty list | low: libcft's variables carry no paths |
| an amendment's link | 17025 7.8.8.3; DCC `previousReport` (a hash); DataCite `Obsoletes` | yes | `supersedes` | CHECKED when the superseded certificate is handed, else REPORTED | `none` | none |
| the per-lane flags | R23 | yes (item 1) | `lane-flags`, and `lanes` on each segment line | CHECKED | `lane-flags no` | hashed, keyed in a keyed certificate |
| a value before and after an adjustment | 17025 7.8.4.1 d) | yes (item 2) | `replay` lines | CHECKED | a count of 0 | the counts in the clear; the raw state and block hashed, keyed in a keyed certificate |
| how the producer made its replays | 17025 n), deviations from the method | yes (item 2) | `replay-methods` and a `replay-method` line for each run with replays, in the header | REPORTED | `replay-methods 0`: no replays | none |
| a traceability statement | 17025 7.8.4.1 c); VIM 2.41 | by construction: the audit's chain to the golden model | the verdict | (none) | (none) | (none) |

**Fields left to the verdict, or not carried.**

| field | from the survey | carried | line | audit | absent as | privacy |
|---|---|---|---|---|---|---|
| the auditor, the time of the audit, what it was handed | CODECHECK codechecker and `check_time`; ACM's badges | in the verdict, not the certificate | (none) | (none) | (none) | the auditor's choice |
| a licence | CodeMeta; DataCite Rights; RO-Crate `license` | **no**: the publication record carries it | (none) | (none) | (none) | (none) |
| a contact | 17025 e); RO-Crate `contactPoint` | **no**: the publication record carries it | (none) | (none) | (none) | personal data |
| a trusted time | RFC 3161 | **no** (section 15) | (none) | (none) | (none) | (none) |
| the MPFR version | (none) | **no**: no writer, auditor or golden computation calls MPFR | (none) | (none) | (none) | (none) |

**Why mpmath's version is carried, and MPFR's is not** (READ,
transcend.py):
- **The golden model decides through mpmath.** Every non-exact
  transcendental is decided by an enclosure from mpmath's interval
  context (`_iv` and `_ziv`), accepted only when its two ends round
  alike. mpmath's interval once excluded the true value, at 514 bits, so
  each end is moved out by 256 units first (`ENCLOSURE_MARGIN_ULPS`).
  Without mpmath, `_iv` raises `ZivEscalation`.
- **A replay reaches it.** A replay (section 7) evaluates a routine's
  node by transcend.py. So the writer that replays by the golden model
  evaluates through mpmath, and so does every auditor that replays.
- **So its version is reported.** It is a dependency of the definition's
  implementation, recorded to diagnose a disagreement: the writer's in
  `writer-runtime`, and the auditor's in the verdict's header.
- **It is not bound.** The certificate binds the definition's version
  (section 7.6). Under that definition a correct evaluator gives the same
  answer with any mpmath. transcend.py says the margin's sufficiency
  rests on "The independent checks - GNU MPFR, and libcft's own
  error-tracked evaluator".
- **MPFR is not carried.** libcft's sources name it in comments only.
  Its callers are tools, tests and a binding (grep):
  - the `mpfr` stage's `host/tools/mpfr_check.c` and
    `host/tests/mp_err_check.c`;
  - the benchmark `host/tools/cft_bench_peers.c`;
  - `python/tests/test_transcend.py`, through gmpy2 when it is
    installed;
  - the Python binding `bindings/python/cftmpfr`, through gmpy2;
  - `docs/studies/ext-a/mpfr_scale.c`, the EXT-A study's instrument,
    which its own header says "is not built by any Makefile and no gate
    runs it".

  None of them is on a certificate's making or audit.

## 6. Item 1: the per-lane flags

**What a run gives** (READ, R23; R8's names):
- one byte a lane:
  - [4:0]: the five IEEE flags the lane raised outside every quiet
    region, in FLAGS's order;
  - [5]: deposit overflow;
  - [6]: the strict-scratch fault;
  - [7]: the mark.

  [7:5] are STATUS[6:4], moved up one place.
- A run asks for the block with MODE[24]. Over the remote protocol,
  PROG_RUN_EX's `want` word asks for it.
- A run split across tiles places each tile's block at its lanes'
  offsets. A segmented run yields one block a segment.
- The identities, over the lanes the run owns: the OR of [4:0] is FLAGS,
  the OR of [6:5] is STATUS[5:4], and the OR of [7] is STATUS[6].

**The lines** (PROPOSED):
- Each run block gains `lane-flags yes` or `lane-flags no`, after its
  parameters and before `segments`. It says whether the run asked for
  the block. `no` is version 1's run exactly: the block is "named as
  absent", in R23's words.
- With `yes`, every segment line ends in two more tokens, `lanes
  <digest>`: the hash of that segment's certified block.
  - The hash is of the tag `cft-certificate 2 lane-flags`, a NUL, then
    the n bytes, lane i's at byte i.
  - It is an HMAC under the salt in a keyed certificate, and plain
    SHA-256 in an open one: version 1's rule for states.
- No lane's byte is in the clear. The flag word and STATUS stay in the
  clear, as in version 1.

**What the body hash and the chain cover.** The body hash covers each
block's hash, and through it the block. The chain does not change. A
block is an output of its segment, not an input to the next one, so
continuity stays a property of states.

**The files beside the certificate.** cft-segrun writes each segment's
block into the states directory as `run-<r>-segment-<k>.flags` (n
bytes), as it writes the boundaries. These files are what a person reads
to find which lane raised invalid. An auditor need not be handed them,
because a re-run recomputes each block.

**What the audit checks:**
- **At step 7 (states handed),** for each block it is handed:
  - its size is the run's `lanes` bytes (`lane-flags-shape`);
  - its hash is the segment's (`lane-flags-hash`);
  - R23's identities hold against the segment line, which needs no
    re-run (`lane-flags-identity`):
    - the OR of the bytes' [4:0] is the flag word;
    - the OR of [6:5] is STATUS[5:4];
    - no byte carries [7]. A certified block's marks are resolved by
      item 2.

  So a sampled audit handed the blocks checks every segment's block,
  re-run or not.
- **At step 9 (re-runs),** each re-run segment's block is computed with
  the segment, one block of lanes at a time, as the end state is. This
  works because a lane's byte is "a function of its own inputs and the
  program alone" (R23). The block must hash to the certified value
  (`segment-lane-flags`).
- **A run that says `no`, and whose re-run marks a lane,** is refused
  `replay-missing` (item 2): the producer could not have found the lane.

**Why a hash, and not the bytes.** A block is n bytes a segment. 65,535
lanes over 100 segments is 6.5 MB of blocks, which would be 13 MB of hex
in the certificate. The hash costs 71 bytes a segment (` lanes `, then
64 hex digits), and version 1 already covers states that way. A run of
few lanes loses nothing, since its block files sit beside the
certificate.

**Counts.** R23 says a certificate covers the block "as it covers the
counts". A segment deposits nothing, so no certificate covers counts
(part D of the round's survey, its disagreements; CERTIFICATES.md, "The
chain"). Version 2 covers the block as it covers the states. R8's design
restates R23's sentence to match (59b19e6).

## 7. Item 2: a marked lane and its replay

### 7.1 What happens on the machine

READ: ROADMAP.md's plan; R8's design; part M of the round's survey, 4.4.

- **A routine marks a lane it could not decide.** A correctly rounded
  routine runs inside a quiet region and tests in-lane whether its last
  bit is decided. It then raises its operation's flags, with bit 7 set
  where the test failed. The mark sets the lane byte's [7] and STATUS[6].
  A quiet region never silences it.
- **The marked lane's value is the routine's best guess,** not
  necessarily the correctly rounded one.
- **How often lanes are marked depends on the routine.**
  - M1's in-lane test fails rarely: part M estimates about 2^-46 a call
    at fp64 with double-word arithmetic (the surveyor's estimate).
  - M2 at fp256 marks by design. The plan has "a stated range, beyond
    which a lane is marked and replayed" (ROADMAP.md, step 6, part 5).
    Every lane whose argument leaves the range is marked, on every call.
  - Some programs leave any range in time. A forcing term sin(t), with
    t growing in the state as T1 carries it, is one; T1's forcing "waits
    for M2" (ROADMAP.md, step 6, part 4). Such a run marks those lanes
    in every segment from then on.
  - How wide M2's range is decides how often that happens, and what the
    range costs. gen_2opi.py's rule: 2/pi must reach (the largest e) - 1
    + the window, with e the exponent of the argument's integer
    significand (READ, host/tools/gen_2opi.py). For a range up to 2^E at
    fp256, e is E - 237. A window of 237 + 245 bits (the significand,
    and the cancellation part M sampled) plus a guard then makes about
    E + 244 bits and the guard. So 2^1024 needs about 1,300 bits: five or
    six fp256 constants in each lane's scratch. gen_2opi.py makes
    270,336 bits for fp256's whole range. That is my estimate (EST);
    M2's window decides it. The copy also costs instructions:
    - the STLs that fill it from the bank each segment (part M, 4.3);
    - the LDX that picks the window by the argument's exponent. The plan
      says "choosing the window by the exponent needs a copy in each
      lane's scratch, read by LDX" (ROADMAP.md, step 6, M2).
- **The definition decides.** LANGUAGE.md makes the reference
  interpreter on the step graph "the definition of correct for every
  compiled image". The language refuses `exp` today (`transcendental`).
  In the plan, `cft_golden/transcend.py` is the golden definition of
  every function of the math library, and part M (5.2) has "an `exp`
  node's golden function would be `transcend.exp`". That function
  decides wherever mpmath is installed and its enclosure stays below the
  precision cap. Otherwise it raises `ZivEscalation`: a cap that
  transcend.py calls "a backstop against a mistake in the reasoning
  above", and loud by design.

### 7.2 What a segment line means

PROPOSED: in version 2 a segment line is the DEFINITION's segment: what
the source's reference interpreter computes.
- For a segment where no lane was marked, that is the machine's own run,
  so the line means what it meant in version 1.
- For a segment with a marked lane, the certificate certifies the
  corrected segment:
  - each marked lane's end values are replaced by its replay;
  - the segment's flag word, STATUS and block are the corrected ones;
  - the machine's raw result for the segment goes on a replay line, one
    for the segment however many lanes it marked.

Why this reading:
- The chain holds the definition's states throughout. Continuity keeps
  version 1's rule (segment k starts where segment k-1 ended), and an
  accuracy entry reads correct states.
- A lane marked once returns to the fast image at the next segment. It
  is not replayed to the end of the run.

The alternative, rejected: certify the raw chain and keep the replays
beside it. A marked lane's raw value would then feed every later segment,
so its replay would have to run from the marking to the end of the run,
and the certified output would not be the definition's.

**Version 1 is the format for the machine's own values.** The lead
decided (R8's question 3, 2026-10-02) that a version-1 certificate
records a marked run as its STATUS says: STATUS[6] set, with no replay,
which is true of the image. Version 1 says what the machine did, and
version 2 says what the program means. So version 2's reader refuses a
segment line whose STATUS carries the mark (`marked`): a certified
segment's marks are always resolved. Section 7.6 gives the reasons.

### 7.3 Where the replay is made

PROPOSED.
- **The arbiter is the golden model on the host.** The replay is
  `lang.run` of the source's step graph, at the run's format, with its
  source params and the run's h (h/2 for a half-step run), on the lane's
  start values (state, tangents and lane params), for the segment's
  steps.
  - Where it decides, its answer is the definition's, by definition.
  - It cannot decide without mpmath, or where an enclosure reaches its
    precision cap (section 7.1). Then the writer refuses
    `replay-undecided`, and an audit refuses `definition-unavailable`
    (section 7.6).
  - Lanes do not interact, so a lane replayed alone is the lane as it is
    in the run. LANGUAGE.md: "running lane by lane is the lockstep run".
- **A slower image is a producer's shortcut.** This is an image of the
  same source, compiled with a more accurate routine (its routines are
  C4's and M1's to define). It runs on the same device, over just the
  marked lanes: packed into a run of their own, or under R17's lane mask.
  - A C producer has no interpreter of the language, so cft-segrun
    replays this way (`--replay-image`, an option of each run). A main
    run and its wider-source run are at two formats, so each can name
    its own replay image.
  - If the slower image marks the lane too, cft-segrun refuses,
    `replay-undecided`. The golden writer is the fallback.
  - For marks that come by design (M2 past its range, section 7.1), a
    slower image is how a producer keeps its replays on the tile. Such
    an image needs a reduction that covers every argument: part M
    estimates a copy of 2/pi in about 1,141 of a lane's 2,048 scratch
    slots for fp256's full range (the surveyor's estimate).
- **The audit always replays by the definition,** whatever the producer
  used. The method is recorded in the header, as provenance (the
  `replay-method` lines, section 7.4), and the value is checked against
  the definition. So a slower image needs no relation of its own to the
  source, and no auditor is handed it.
- **Refusing instead of replaying** is open for marks past a range,
  at a cost. The routine's own range test is what makes it mark, so in
  the lane the routine knows which marks are past its range. R23's byte
  is full, and R24's raise reads only `ra[4:0]` and `ra[7]` (R8's
  design), so neither carries the difference out of the lane. Two
  carriers do:
  - **a word in scratch-out**, which part M (4.4) lists as a per-lane
    carrier for a refusal, and which R23 and R24 leave free. The
    routine writes a code into a slot the language defines, and a writer
    refuses, by name, a run whose lane carries one. Its cost is a
    scratch slot in every lane, the instructions that write it, and a
    language rule that names the slot;
  - **a writer's own test.** A writer that replays recomputes each
    marked lane, its arguments among them, and can refuse a mark past
    the range by name instead of replaying it. Its cost is the routine's
    stated range carried from the routine's generator to every writer,
    the C writer included, which replays by a slower image.

  Either way, such a run is not certified as version 2. Version 1 still
  records it, mark and all.

### 7.4 The lines

PROPOSED.
- After a run's segment lines comes `replays <m>`, then m lines, one for
  each segment in which the machine marked a lane:

      replay <k> marked <n> changed <c> raw-end <digest> raw-lanes <digest>

  - `k` is the segment. The lines' segments increase strictly.
  - `marked` is how many lanes the machine marked in that segment: at
    least 1.
  - `changed` is how many of those the replay changed: how often the
    routine's undecided guess was in fact wrong. It is for a person, and
    for measuring routines, and it is at most `marked`.
  - `raw-end` is the hash of the segment's raw end state: the machine's,
    before any replay. It is a state, so it takes version 1's state tag:
    an HMAC in a keyed certificate, plain SHA-256 in an open one.
  - `raw-lanes` is the hash of the segment's raw block, under the block's
    tag (section 6). The marked lanes are its bytes with bit 7 set, and
    each one's raw byte is in it.
  - One line covers a segment however many lanes it marked. So a run
    whose lanes are marked in every segment (M2 past its range, section
    7.1) has one replay line a segment, not one a lane, and its
    certificate stays the size of its segments.
- How the producer made its replays is in the header (section 9.2):
  `replay-methods <n>`, then one line for each run that has replays,
  `replay-method <r> golden` or `replay-method <r> image <digest>`. A
  main run and its wider-source run are at two formats, so each names
  its own method and image. The lines are REPORTED, and they sit in the
  header because two writers of one run make them differently (rule 4).
- The segment line of a segment with replays carries the corrected
  values:
  - the end: the raw end, with each marked lane's values the
    definition's;
  - the block: the raw block, with each marked lane's byte its corrected
    byte: the definition's five flags in [4:0], the raw [6:5], and [7]
    clear;
  - the flag word: the OR of the corrected bytes' [4:0];
  - STATUS: the raw STATUS with STATUS[6] cleared.
- Form rules, which the reader checks with no inputs:
  - a segment line's STATUS never carries STATUS[6] (`marked`);
  - a run with replays has `lane-flags yes` (`replay-lane-flags`);
  - a run with replays names a source (`replay-source`);
  - `changed` is at most `marked` (`malformed`);
  - the runs with replay lines are exactly the runs the header's
    `replay-method` lines name (`replay-method`). A run with replays and
    no method line, or a method line for a run with none or for no run,
    is refused by that name.
- A run whose image can mark must ask for the block. The writers ask for
  it whenever the image needs flag control (CAPS2[14]), since a mark
  alone does not say which lane.

**What the body hash and the chain cover.** The body hash covers every
replay line: its counts, and through its two hashes the raw end state
and the raw block. The chain is the corrected chain. Boundary k is the
definition's state, and raw states are never boundaries.

**The files beside the certificate.** For each segment with a replay,
the writer writes the raw end state and the raw block, as
`run-<r>-segment-<k>-raw.bin` and `run-<r>-segment-<k>-raw.flags`. They
are what a person reads to see which lanes were marked and how the
replay moved them. A re-run recomputes both, so an audit needs neither.

### 7.5 What the audit checks

At step 9, for each re-run segment, in this order:
1. Re-run the image from the segment's start: the raw end, the raw flag
   word, the raw STATUS and the raw block.
2. Check whether a replay line is due:
   - a segment whose raw block marks a lane must have one
     (`replay-missing`);
   - a segment that marked no lane must have none (`replay-unmarked`).
3. The line's `raw-end` must be the raw end's hash, its `raw-lanes` the
   raw block's, and its `marked` the count of marked lanes
   (`replay-raw`).
4. Replay each marked lane by the definition (section 7.3). The number
   of lanes whose values change must be the line's `changed`
   (`replay-changed`).
5. The corrected end, block, flag word and STATUS must be the segment
   line's: `segment-end`, `segment-lane-flags`, `segment-flags` and
   `segment-status`, version 1's names now against the corrected values.

A segment with no line and no mark gets version 1's check, plus its
block.

**What it needs.** Steps 1 to 3 need only the image, so a mark with no
replay line is `replay-missing` whatever the audit was handed. Step 4
needs the source, handed and checked at step 4a (section 8.7), and a
definition the auditor can evaluate (section 7.6).
- An audit not handed the source refuses `source-missing` at step 4 of
  the first re-run segment that has a replay line.
- cft-audit is never handed a source (section 13). So a certificate with
  a replay in a re-run segment is audited by the golden auditor. Its
  other segments, and every certificate without replays, cft-audit
  audits as before.

**What it proves.** For each re-run segment where the machine marked a
lane: the certified end is the definition's, lane by lane, and the
machine's raw end and block before the replay are what it computed.

**What it costs** (BELIEVED). One replay is one lane for one segment
through the interpreter. Each routine call is one `transcend.py` call,
which part M measured at 0.06 to 0.14 ms at fp64 and fp256. So the cost
is the marked lanes of the re-run segments:
- with M1's rare marks, a few lanes, or none;
- with M2's marks by design, every lane past the range, in every re-run
  segment. The golden auditor replays them all on the host, and cft-audit
  can audit none of those segments. The producer pays the same, unless a
  slower image replays them on the tile (section 7.3).

Section 16 asks Logan what M2 should do past its range.

### 7.6 The lead's question: an unreplayed mark, and what binds a replay

The lead asked: in version 2, may a certificate stand with a marked lane
that has no replay record, or is that refused by name? And how does a
replay record bind the replayed lane's value to the golden model's
answer, so that an audit can check it?

**An unreplayed mark is refused, by name, twice** (PROPOSED):
- **by the reader, `marked`:** a segment line whose STATUS carries
  STATUS[6]. A producer who wrote the raw segment as the certified one is
  caught from the certificate alone, with no inputs;
- **by the audit, `replay-missing`** (exit 6): a re-run segment whose
  image marks a lane that no replay line names. This catches a producer
  who cleared STATUS[6] to pass the reader, because the re-run's raw byte
  shows the mark. A sampled audit catches it with the sample's escape
  probability, as it catches any wrong segment.

The reasons:
1. **A version-2 segment line is the definition's** (section 7.2). A
   marked lane's value is the routine's best guess. The guess may well be
   right (a replay line counts those, `marked` less `changed`), but it
   was not shown to be correctly rounded. A certificate that stood with
   it would certify, as the definition's, a value that may not be. The
   project refuses by name what it cannot do, rather than approximate
   it.
2. **Refusing loses nothing.** Version 1 certifies the machine's own
   values, STATUS[6] and all (the lead's decision above). A producer who
   cannot replay, because it has no source to name or no replay route,
   writes version 1, and that certificate's reader sees the mark.
3. **One format, one meaning.** If a certificate's segments were
   sometimes the definition's and sometimes the machine's, every reader
   would have to look for the mark before trusting any value. With the
   refusal, a version-2 chain is the definition's wherever it stands, and
   a version-1 chain is the machine's.
4. **The design does not rest on marks being rare.** One replay line
   covers a segment, however many lanes it marked (section 7.4). So a
   certificate stays small even when marks come by design (M2 past its
   range, section 7.1). What grows with the marks is the cost:
   - of the replays, for the producer and for the golden auditor;
   - in the number of segments cft-audit cannot audit (section 7.5).

   Section 16 asks Logan what M2 should do past its range.

**A replay is bound to the golden model's answer by recomputation from
named inputs,** not by a stored copy of that answer:
1. **The definition is named.** The run names its source by SHA-256
   (`source`) and its step graph by SHA-256 (`graph`). The certificate
   names the definition's version: the conformance profile and the
   language (`profile`, `language`; below, and section 9.2). The audit,
   handed the source, holds it to both digests (step 4a: `source-digest`,
   `source-graph`). So the definition the audit evaluates is the one the
   certificate names, wherever the auditor's versions cover the
   certificate's.
2. **A routine's node is evaluated by the golden function.** The plan
   says, of the math library: "The golden definition is
   `cft_golden/transcend.py` for every function" (ROADMAP.md, step 6,
   part 5). Part M (5.2) gives the shape: "an `exp` node's golden
   function would be `transcend.exp`, which already returns bits and
   flags". The reference interpreter evaluates the node by that
   function.
3. **Each marked lane is replayed from its certified start.** The
   replay record names the segment. Its marked lanes are the raw block's
   lanes with bit 7 set, which the re-run finds and `raw-lanes` binds.
   The audit runs each one through the interpreter for the segment, from
   the lane's certified start values (which the segment's start hash
   binds), with the run's source params and h.
4. **The result must be the certified one.** The values it gets are
   spliced into the re-run's raw end, and the result must hash to the
   segment line's `end` (`segment-end`). The corrected block must hash to
   the segment's `lanes` (`segment-lane-flags`), which binds each marked
   lane's corrected byte.

So the certified value of a replayed lane is its slice of the segment's
end state, bound by the end hash. The audit checks that it is exactly
what the golden functions, through the interpreter, compute from the
certified start.

**What the binding is to: the definition the certificate names**
(PROPOSED). Correct rounding makes a value unique only under one
contract:
- **Two correct implementations can disagree.** transcend.py's `powr`
  gives a quiet NaN for powr(1, qNaN), where MPFR 4.2.2's `mpfr_powr`
  gives 1, and transcend.py holds its row to be the standard's (READ, its
  `powr`). Special values, tininess, NaN results and pole flags are a
  contract's choices, not consequences of correct rounding.
- **The definition moves across commits.** `tangent` became a keyword on
  2026-10-02, and a source written before then that names a value
  `tangent` is refused now (LANGUAGE.md, "The text"). A special-value
  row, a flag convention, or a function's name in the language can move
  the same way.

**So a certificate names its definition,** in two header lines (section
9.2): `profile` and `language`.

**`profile`: the conformance profile, extended to the program model.**
- **What CONFORMANCE.md versions today** (READ, "Versioning"): "The
  profile version is the vectors", and "A change to any recorded bit or
  flag is a new profile number". An addition that changes no recorded
  case is a minor step (1.1, 1.2).
- **Its record holds no program.** The record is the vector sets: 168
  elementwise sets of opcodes, transcendentals, conversions and the
  like. Yet the program model is normative. CONFORMANCE.md's "The
  program model" says "A conforming implementation runs an image bit for
  bit as the model does, or refuses it by name before running anything",
  and every load check and re-run of an audit runs that model.
- **So today's number does not version what an audit re-derives.**
  ee78152 (2026-10-01) made seq.py refuse images whose header carries
  more than 512 constants (513, 600 and 70,000), which it had loaded and
  run at 575a819. The profile stayed 1, rightly by its rule: no recorded
  case moved (READ, the commit's message). Under the rule as it stands,
  an auditor after ee78152 covers a certificate made before it, and
  would refuse such an image `program-image`, blaming an honest
  certificate.
- **The fix I propose: the profile versions the program model too.** The
  rule: any change to what an accepted image computes, or to whether an
  image loads, steps the profile.
  - A change to an accepted image's result or acceptance is a major
    step. ee78152 was one by this rule: images with 513, 600 and 70,000
    constants loaded before it and are refused after.
  - A feature that loads images refused before only because their
    encoding was unclaimed (an unknown control code, say), and leaves
    every accepted image as it was, is a minor step. Those refusals were
    of encodings held for later, and become acceptances. R24's codes 12
    to 14 would be one.
- **The record is a backstop for the rule, not its definition.** The
  profile's record gains program sets, so that a gate catches what it
  can:
  - the golden corpus's images, initial states and every boundary state,
    which `certificates/MANIFEST` already holds;
  - load cases, generated from seq.py as the vectors are. For each of
    the loader's rules: an image at its edge, accepted, and one past it,
    refused by name. For each header field, acceptance at its
    encoding's extremes: the field's maximum where an image that size
    can be built, and otherwise the largest that can. Also acceptance at
    the values around any limit a field could gain, such as the
    capacities tiles publish.

  The extremes are what would have caught ee78152:
  - Its rule was new. Before it, seq.py's comment said "`n_consts` above
    this is not refused", so no per-rule case sat at or past 512.
  - The corpus's images carry at most 7 constants (verifier-VCV2,
    measured).
  - So per-rule cases alone would only have gained new cases, and the
    gate would have passed. A recorded acceptance of 513 or 70,000
    constants moves instead.

  A change the record still does not reach steps the profile by the rule
  alone, at its committer's word, which is how CONFORMANCE.md's number
  is kept today.
- **The other way was a separate version for the program model.** I do
  not propose it. It would name one contract with two numbers that can
  drift apart, while CONFORMANCE.md's profile already holds the program
  model in its text. Either way, CONFORMANCE.md's versioning rule
  changes, and that is a contract change (question 6).

**`language`: the language's version.** None exists today. I propose
one, kept in the golden model, under the same rule:
- a major step whenever an accepted source is refused, or computes
  another thing. `tangent`'s reservation would have been one;
- a minor step for an addition that changes no accepted source.

**How often majors step.** Under these rules a major step is any change
that refuses or recomputes something accepted before. Counted from L1
(dd27ed7), the language would already have taken about four majors in
its first two days: the step-size-sign refusal and D2's `unused` and
`too-deep` (2026-10-01), then `tangent` (2026-10-02). That is
verifier-VCV2's count, which I have not redone. What it means:
- **Majors will step often while the language and the model are
  young.** Each one leaves every older certificate uncovered by a newer
  auditor.
- **An uncovered certificate still passes wherever it does not touch the
  change.** Coverage decides only who is blamed for a failure.
- **Deciding a `definition-differs` needs the named definition:** a
  checkout of the golden model at a commit that implements it. So
  auditors keep old definitions at hand, as cft-orbits' resume already
  needs the build its checkpoint names.
- **The numbering starts with version 2's build,** so none of those four
  ever appears in a certificate.
- **The language can lower its own rate.** A source could declare its
  language version, as it declares its format, so that a new keyword
  refuses only the sources that ask for the new version. That is the
  language's to decide, not version 2's.

**Who is blamed when a re-derivation fails:**
- **Coverage.** An auditor's definition covers a certificate's when, for
  each version, the majors are equal and the auditor's minor is at least
  the certificate's.
  - `language none` (no run names a source) is covered by every
    language, since no check reads one.
  - A certificate that writes `unknown` is never covered.
- **The auditor's definition covers the certificate's.** The failure is
  the certificate's, under its own name.
- **It does not.** Any re-derivation that fails is refused
  `definition-differs`, naming both versions. That covers a load check
  at step 4, a language check or a recompile at step 4a, a re-run, a
  replay, and a definition re-run. Like `compiler-differs`, it is the
  auditor's own limit, not a verdict on the certificate. Hand the audit
  the named definition, and it decides.
- **Exit 78 is not new for this.** It is the code version 1 already gives
  a tool's own limits:
  - `build-width` and `build-format` (CERTIFICATES.md, "The audit tool");
  - cft-orbits' `identity`, a resume on another build or device than the
    certificate names (ORBITS.md, "Certified runs").

  `compiler-differs`, `definition-differs` and `definition-unavailable`
  join that family, by version 1's rule that a code names a family and
  the name is the report.
- **A false certificate is refused either way.** `definition-differs` is
  a refusal too, so claiming an old definition gains a producer nothing.
- **An auditor that cannot evaluate the definition** refuses
  `definition-unavailable` (exit 78). That is an auditor without mpmath,
  or one whose enclosure reached its cap (section 7.1).
- **Where every check passes,** the verdict accepts, and names both
  definitions: the bits hold under the auditor's too.

The replay record still carries no golden value. The source and the
definition's version fix the function, and correct rounding under that
profile fixes the answer. That correctness is held in the tree, not
assumed: the 39 functions are "held by the `transcend` and `mpfr`
stages" (ROADMAP.md, step 6, "What the surveys found"), and transcend.py
decides through mpmath's enclosures (section 5).

**What the binding does not need** is the producer's replay method. The
header's `replay-method` lines are reported. A slower image's answer is
accepted exactly when it equals the definition's, lane by lane.

**A cheaper check, for an auditor handed the states and the raw
blocks:**
- a marked lane's slice of the handed end state is its certified value;
- the raw block handed, held to `raw-lanes`, says which lanes were
  marked;
- so the interpreter, run on each marked lane's start slice, must
  reproduce its slice of the end state, with no re-run of the image.

That checks the replays' values. `changed` needs the raw end state too,
handed and held to `raw-end`; without it, the re-run.

## 8. Item 3: a source, and a wider run compiled from it

### 8.1 What version 1 cannot relate

READ.
- **Version 1's wider run** must be "the main image one format wider:
  the same instruction words, `max_deposits`, flags, constant count and
  scratch word, the precision code one rung up, and any constants the
  image carries exactly widened", with the bank exactly widened
  (CERTIFICATES.md, "Auxiliary runs").
- **A routine's words differ by format** (part D, 1.3 and 1.11), so a
  program with a routine has no version-1 wider run. cft-orbits refuses
  its wider runs for the same reason.
- **A binary image keeps no constant names,** so version 1 cannot show
  "that the bank slots a half-step run names are the ones that carry the
  step" ("What an audit proves").

### 8.2 Two claims a source can carry

MEASURED (probe 1, scratchpad `cv2/probe_cv2.py`, niced, about 1 s at 2%
CPU load):
- `cftc.compile_file` of programs/systems/lorenz63-rk4-fp64.cftl, at 100
  steps, gives the same image (ff422cc9...) and the same bank
  (c91cc547...) at targets `sw`, `u50-rev7` and `u50-rev7-quad`, and
  under another `--stem`.
- With `--param rho=29` it gives the same image and another bank.
- So an image is a function of the source, `--steps` and the compiler,
  and the bank is also a function of `--param`. The target decides only
  whether an image is accepted. That is cftc's own rule: "one image, the
  same bytes, serves every target that accepts it" (python/cftc).

MEASURED (sha256sum, and probe 2's first line):
- The corpus's Lorenz-63 image (`certificates/images/lorenz63-rk4-fp64.cftp`,
  a4f98313...) is gen_odes' hand-written program, 115 lines of `.cfta`.
- The compiled image (ff422cc9...) has 85.
- Both carry the classic bank, and the step graph's run equals the
  corpus's chain.

So a source can stand in two relations to an image (PROPOSED):
- **compiled from:** the image and bank are what the compiler makes of
  the source. This is CHECKED by recompiling, since compilation is byte
  for byte deterministic. Three things show it:
  - cftc's manifest writer promises "the same bytes for the same source
    on every machine" (python/cftc/manifest.py);
  - the `acceptance` stage compiles ten workloads and holds each image
    and bank to a committed SHA-256, and it passed on amd-arc-box, under
    Linux, against digests made on the Windows desktop (READ, the
    round's lead ledger, 2026-10-02 09:25);
  - probe 1, above.
- **defined by:** the run computes what the source's reference
  interpreter computes. This is CHECKED by running the interpreter (a
  definition re-run, section 12). It holds for a hand-written image too,
  if that image is right.

### 8.3 The lines

PROPOSED. After `program-digest`, a run block gains:
- `source <digest>`, the SHA-256 of the source file's bytes; or `source
  none`, which is version 1's run.
- With a source, these lines follow:
  - `source-name <text>` (or `none`): its file name, without
    directories (REPORTED);
  - `graph <digest>`: the SHA-256 of its step graph's canonical bytes at
    the run's format (CHECKED by the language). This is the SYSTEM's
    identity. Comments, spelling and the order of equations do not reach
    it (LANGUAGE.md, "What makes the bytes canonical");
  - `compiler none`, where the image is not claimed to be the source's
    compile; or `compiler <name> <output-version> <target>`, the version
    a decimal and the target a text (a target can be `sw:2048`), for
    example `compiler cftc 1 u50-rev7-quad` (CHECKED by a recompile);
  - `source-params <p>`, then p lines `source-param <name> <literal>`:
    the run values given for the source's params, which are cftc's
    `--param`.
    - The names increase strictly.
    - Each value is in the language's canonical spelling of its exact
      value: the canonical form's spelling, from LANGUAGE.md's "The
      intention-out".
    - These are CHECKED through the recompile's bank, or through the
      definition.
- `steps` becomes CHECKED where a compiler is named (the image's REPEAT
  count is the compile's `--steps`), or where a definition re-run is
  made.

**The format.** The source is taken at the run's `program-format`:
- a main run's format must be the source's own (`source-format`);
- a wider-source run's is one rung up.

This needs a format override in the language and in cftc: the source
with its format statement's value replaced (section 13).

**The compiler's build** (its commit) is provenance, so it goes in the
header as `compiler-build` (section 9). It varies with the producer's
checkout, and no run block may vary that way (rule 4).

### 8.4 The wider-source run, and why its estimate is a different one

PROPOSED:
- **A run `run <i> wider-source`** is the main run's source compiled at
  the next rung, with the same steps, source params and target. Both
  runs name the source and a compiler.
- **Its relation** is checked in version 1's order:
  - `aux-format`: the next rung;
  - `aux-lanes`: the main run's lanes;
  - `aux-source`, a new check: the same source digest and source params,
    and the same compiler name, output version and target, as the main
    run;
  - `aux-image`: its image and bank are the recompile at the next rung
    (step 4a checked that compile), and its depth is the main run's;
  - `aux-segments`: the main run's segment count;
  - `aux-streams` and `aux-start`: exactly widened, as for version 1's
    wider run.
- **An entry `entry <j> wider-source`** is of kind estimate and uses a
  wider-source run. Its value is version 1's wider function: the largest
  absolute difference over the slots between the two runs' final states.
- **Version 1's `wider` stays.** It is a different relation, estimating
  a different error.

MEASURED (probe 2): the corpus case lorenz63-rk4-fp64 (3 lanes, 3
segments of 100 steps, t = 3).
- The fp64 step graph, run by `lang.run` from the corpus's boundary 0,
  equals the main run's boundary 3.
- Run 2's boundary 0 is boundary 0 exactly widened.
- The same source with its format line replaced by fp128 was run by
  `lang.run` from the widened initial state. Against it:

| lane | version 1's wider E | the wider-source E | the two fp128 runs apart |
|---|---|---|---|
| 0 | 1.7587e-15 | 2.7066e-15 | 3.5390e-15 |
| 1 | 8.9822e-15 | 9.5124e-15 | 3.5348e-15 |
| 2 | 2.6003e-14 | 2.5455e-14 | 3.5305e-15 |

Version 1's column equals ACC-A's rho: lane 0's shift over rho is 2.00
there, which gives rho = 1.757e-15. The two fp128 runs differ by about
3.5e-15 on every lane, which is the time shift ACC-A measured at t = 3
(3.5146e-15, 3.5182e-15 and 3.5216e-15;
[ACC-A-estimates.md](ACC-A-estimates.md), section 4). The bank's h/6
rounds with relative error +6.418e-17 at fp64 and +5.567e-35 at fp128
(MEASURED).

**Reading** (BELIEVED, from the measurement):
- Version 1's wider run carries the main bank's constants exactly
  widened. So it estimates the rounding of the arithmetic on those
  constants.
- The wider-source run rounds h, h/2 and h/6 once at fp128. So it
  estimates the rounding relative to the system as written, the
  constants' rounding included. ACC-A calls that "an error neither
  estimate sees"; this estimate sees it.
- Neither is a bound.
- For a program with a routine, only the wider-source run exists.

### 8.5 The half-step run, with a source

Version 1's half-step relation is unchanged: the same image, with its
h-slots halved. A named source strengthens it.
- When the main run is compiled from a named source, the recompile's
  manifest names its h-slots. For Lorenz-63, MEASURED, `h_slots` is [0,
  1, 2]. The audit requires the run's h-slots to be exactly those
  (`aux-h-slots`): the step halved, all of it, and nothing else. That
  turns version 1's "not proved" into a check.
- A half-step run's source lines are the main run's (`aux-source`).
- Its definition is the interpreter at h/2. LANGUAGE.md: "a run at an h
  of the same sign is the graph compiled at that h".

### 8.6 Whether a certificate names its source

PROPOSED.
- **Naming is optional for each run.** It is required where a check needs
  the source: for replays (item 2), and for a wider-source run.
- **The source's digest is unkeyed in both modes,** as the program
  digests are in version 1 ("the program: its digests are unkeyed"). A
  reader can confirm a guessed source. The keyed mode protects neither
  the program nor its source. A producer who wants the source unnamed
  writes `source none`, and gives up replays and wider-source runs.
- **The source travels with the certificate** as an input to the audit,
  as images do. The writer may copy it into the states directory as
  `run-<r>.cftl`.

**What the body hash and the chain cover, and the files beside.**
- The body hash covers every source line: the source's digest and name,
  the graph, the compiler, its target, and the params. All of them are
  part of the certificate's bytes.
- The chain does not change. A source is an input to the program, as the
  image is, and no state depends on it beyond what the image computes.
- Beside the certificate: the source file, which an auditor needs to
  check any of this. A wider-source run needs nothing more beside it:
  its image and bank are the recompile's, and the auditor makes its own.

### 8.7 What the audit checks: step 4a, the sources

For each run that names a source the audit was handed:
1. its SHA-256 is the run's `source` (`source-digest`);
2. the language accepts it at the run's format (`source-refused`, with
   the language's own refusal named in the sentence);
3. a main run's format is the source's own (`source-format`);
4. its step graph's SHA-256 is the run's `graph` (`source-graph`);
5. each source param names one of its params, and its literal is the
   canonical spelling of a constant (`source-param`);
6. where a compiler is named, the auditor's compiler compiles the source
   with the run's steps, source params, format and target. The image and
   bank must hash to `program-image` and `program-digest`. If they do
   not:
   - `source-image`, when the auditor's compiler has the named name and
     output version: the claim is false;
   - `compiler-differs` (exit 78) otherwise. This is the auditor's own
     limit, as `build-format` is in version 1. Hand the audit the named
     compiler, and it can decide.

Checks 2, 4 and 5 are the language's, and check 6 goes through it. So
any of them that fails, where the auditor's definition does not cover the
certificate's (section 7.6), is refused `definition-differs` instead of
its own name. Where both the definition and the compiler differ,
`definition-differs` is named, since the compiler reads the language.

A source that is named but not handed is reported as "named, not handed:
stated, not checked". A later step that needs it refuses `source-missing`.

The recompile costs the compiler's time. That grows faster than the
step does (cftc's known limit: 58 s for a 16,796-node ring, READ), and
it is bounded by the source handed. That is version 1's rule: an audit
spends what it is handed.

## 9. The provenance lines

PROPOSED.

### 9.1 The new encodings

- **A time** is `YYYY-MM-DDTHH:MM:SSZ`, 20 characters: UTC, a real
  Gregorian date and time, seconds 00 to 59. The word `unknown` may stand
  instead. It is one spelling of RFC 3339's `date-time` (July 2002,
  section 5.6, page), narrowed to one spelling:
  - `T` and `Z` in upper case, where RFC 3339 also allows lower case;
  - no fraction of a second;
  - the offset always `Z`.

  RFC 3339 allows a second of 60 at a leap second (5.7). Version 2 does
  not, as SOURCE_DATE_EPOCH counts none.
- **A text** is a value's bytes, percent-encoded as URIs encode them.
  - Each byte from 0x21 to 0x7E, other than `%`, stands as itself.
  - Every other byte is `%` and two uppercase hex digits: a space, `%`
    itself, a control character, or a byte of a non-ASCII character.
  - One spelling: a byte that may stand as itself is never encoded.
  - 1 to 255 characters once encoded.
  - A writer refuses a text equal to one of the words `none`, `unknown`,
    `withheld` or `given` (`malformed`), so a word is never a value.

  So a person's name, a platform string with spaces and a file name all
  have one spelling: `Logan%20W.` is the text of "Logan W.".
- **A name** is version 1's: a lowercase letter, then lowercase letters,
  digits and `-`, at most 64 in all. Used for a writer, a compiler and a
  generator.
- **A key** is 64 lowercase hex digits: an Ed25519 public key.
- **A version** is a major in decimal, then `.` and a minor in decimal
  where the minor is not 0: `1`, `1.2`. There are no leading zeros. It
  spells CONFORMANCE.md's profile numbers ("1.1, 1.2"), and the language
  version that section 7.6 proposes.
- **An env name** is an uppercase letter, then uppercase letters, digits
  and `_`, at most 64 in all.
- **An env value** is a text. A variable set to the empty string counts
  as unset. That is libcft's own rule: "The empty string is the variable
  unset", since cmd and PowerShell remove a variable set empty
  (CERTIFICATES.md, "The audit tool"). (Restated 2026-10-05: that
  sentence is the audit tool's rule for its own instrument, and
  cft-segrun's for its own. libcft reads most of the writer's list the
  same way, but not all of it; CERTIFICATES.md, "Version 2's
  encodings", says which variables differ. The writers still record a
  variable set empty as unset.)
- **`withheld`** is rule 2's word.

### 9.2 The header's new lines

They come after version 1's identity lines, in this order:

| line | values | audit |
|---|---|---|
| `profile <version>` | the conformance profile the bits are claimed under, extended to version the program model (section 7.6); `unknown` | REPORTED; compared with the auditor's own, to name a failure's cause |
| `language <version>` | the language's version; `none` where no run names a source, which every language covers; `unknown` | REPORTED; compared with the auditor's own, to name a failure's cause |
| `device-platform <text>` | the card's platform (shell) name as XRT reports it, for example `xilinx_u50_gen3x16_xdma_5_202210_1`; `none` for the software backend; `unknown` | REPORTED |
| `device-xrt <text>` | XRT's version, for example `2.19.194`; `none`; `unknown` | REPORTED |
| `device-clock <n>` | the kernel clock in Hz, as a decimal, for example `135000000`; `none`; `unknown` | REPORTED |
| `device-serial <text>` | the card's serial; `none`; `unknown`; `withheld`, the default | REPORTED |
| `writer <name> <id>` | the program that wrote the certificate (`cft-segrun`, `cft-orbits`, `golden`), and its build in the build-id grammar, or `unknown` | REPORTED |
| `writer-runtime <text>` | the golden writer's Python, and its mpmath's version wherever it evaluated the definition, for example `python-3.12.9,mpmath-1.3.0` (this desktop's); `none` for a C tool | REPORTED |
| `compiler-build <id>` | in the build-id grammar, the build of the compiler that made the images whose runs name one; `none`; `unknown` | REPORTED |
| `replay-methods <n>`, then n lines `replay-method <r> golden` or `replay-method <r> image <digest>` | how the producer made each run's replays: by the golden model, or by a replay image (its SHA-256), one line for each run that has replays, runs strictly increasing; `replay-methods 0` where no run has a replay | REPORTED |
| `certificate-id <text>` | an identifier the issuer assigns before writing; `none` | REPORTED |
| `issuer <text>` | who issues it: a name, an ORCID or an organisation's id, as the issuer chooses; `none`; `withheld` | REPORTED; CHECKED with a signature and a keyring |
| `issuer-key <key>` | the Ed25519 key it is to be signed with; `none` | CHECKED by the signature |
| `host-os <text>` | the OS's name, `linux` or `windows`; its version (`linux-6.8`, for Linux the kernel's) only on request (question 9); `unknown`; `withheld` | REPORTED |
| `host-arch <text>` | for example `x86_64`; `unknown`; `withheld` | REPORTED |
| `started <time>` | when the first run began | REPORTED |
| `finished <time>` | when the last run ended | REPORTED |
| `issued <time>` | when the certificate was written | REPORTED |
| `supersedes <digest>` | the body hash of a certificate this one replaces; `none` | CHECKED when the superseded certificate is handed |
| `environment <n>`, then n lines `env <name> <value>` | the variables, of the writer's list, that were set; names strictly increasing | REPORTED |
| `initial given`, or `initial generator <name> <text> ...` | how run 0's initial state was made: handed as data, or by a named generator and its arguments, at most 16 | CHECKED where the auditor knows the generator, else REPORTED |

A form rule: where the times are known, `started` is no later than
`finished`, and `finished` no later than `issued` (`provenance-order`).

### 9.3 Notes, field by field

**The environment.** The writer's list is every variable libcft and the
tool read (READ: `getenv` in `host/src` and `host/tools`):
- **those that change where a run ran:**
  - `XCL_EMULATION_MODE`: XRT's own variable. It means an emulated run,
    whose only other trace is its xclbin's digest;
  - `CFT_XRT_TILES`: which tiles ran it;
- **the instruments:**
  - `CFT_XRT_TILE_ORDER` and `CFT_XRT_PROGRAM_CUTS` reorder a run
    without changing its bits;
  - `CFT_XRT_WITNESS`, `CFT_XRT_BIND`, `CFT_XRT_CAPS` and
    `CFT_SEGRUN_PLANT` make a run refuse;
- **the operational ones:** `CFT_TIMEOUT_MS`, `CFT_XRT_TRACE`,
  `CFT_XRT_REDUCE_BC` and `CFT_XRT_MASK_ADDR_OVERRIDE`;
- **the elementwise routes,** which no program run reaches:
  `CFT_DIVSQRT_SEQ`, `CFT_DIVSQRT_FULL` and `CFT_TRANSCEND_MINPREC`.

None of these carries a path. A gate check holds the list to the code's
`getenv` calls, so a new variable cannot be missed.

**The initial-state generator.**
- **Today's informal record.** The corpus's Lorenz-63 case states
  `parameter members 3` and `parameter ensemble-spread 64`
  (`certificates/MANIFEST`, READ). Integer parameters are already used
  to say how the lanes were made.
- **What a generator adds.** It makes that record a check. An auditor
  that knows the generator regenerates boundary 0 and compares its hash
  (`initial-state`), so it needs no initial state handed.
- **Where generators are defined.** In the golden model, each by name.
  The first candidate is A1's (`programs/acceptance.py`): values drawn
  from SHAKE-256 of the entry's name, the lane and the component, within
  a box, and rounded once.
- **In a keyed certificate,** a generator publishes boundary 0, which
  the salt otherwise protects. The verdict says so.

**The device's extra lines** need the library:
- `cft_image_id` grows additively, through its `struct_size` handshake
  (HOSTAPI.md), with the platform name, the XRT version, the clock and
  the serial. That is an ABI step (section 13).
- Through a remote handle they are `unknown`, as version 1's xclbin
  digest is.

**`certificate-id`** is the issuer's own name for the certificate, chosen
before it is written.
- The body's hash stays the certificate's intrinsic name, as a SWHID is
  a content's, and the verdict prints it.
- A DOI is minted when something is published, after the bytes exist. It
  belongs to the publication's record (section 15), never to the body.

**Not carried** (decided, rule 3):
- **the host name, the user name, the CPU model and paths:** each is
  personal data or a fingerprint, and none can change the bits;
- **a licence and a contact:** they belong to a publication, not to a
  run. They can change while the run does not, and a contact is personal
  data. The gallery's publication record carries them, as DataCite
  Rights and RO-Crate's `license` and `contactPoint`;
- **free text,** the params' meanings included: the source carries
  those, and the certificate names the source by digest;
- **the auditors' builds and the audit's time:** these exist only after
  the certificate does, so the verdict carries them (section 12).

## 10. The detached signature

Version 1 reserved it: "It signs the body's hash, the 32 bytes the hash
line carries. It lives in a file of its own, beside the certificate ...
Version 1 defines no scheme." PROPOSED: version 2 defines one, and it
signs a certificate of either version.

**The scheme** is Ed25519 (RFC 8032), for three reasons:
- **It is deterministic.** "The use of a unique random number for each
  signature is not required." One key and one certificate give one
  signature, byte for byte, so a gate can hold a signature to a
  committed value as it holds hashes.
- **It has test vectors.** RFC 8032's 7.1 holds an implementation to
  them.
- **It is small:** 32-byte keys and 64-byte signatures.

**The message** is the tag `cft-signature 1`, a NUL, then the 32 bytes of
the body hash. This is version 1's tagged-hash rule, so a signature over
a certificate is a signature over nothing else. DSSE's PAE and SSHSIG's
namespace serve the same end.

**The file** is `<certificate>.sig`. It follows the certificate's byte
rules, and has five lines:

    cft-signature 1
    scheme ed25519
    key <64 hex>
    certificate <64 hex>
    signature <128 hex>

**The key's identity** is the public key itself, 64 hex digits.
- A certificate names the key it is to be signed with, by `issuer-key`.
- Which person holds a key is not in any certificate. An auditor may be
  handed a keyring (lines `key <64 hex> <text>`), and the verdict then
  names the key's holder from it.

**The audit** (step 2a):
- the file follows its form (`signature-format`);
- its `certificate` line is the body hash, and the signature verifies
  (`signature`);
- the key is the certificate's `issuer-key`, where it names one
  (`signature-key`);
- in a keyring handed, the key's name is the certificate's `issuer`
  (`signer`).

Without a keyring the verdict says: "signed by key K, which no keyring
handed names".

**What it proves:** the key's holder vouched for these bytes. It proves
neither when (section 15) nor that the bits are right. The audit proves
the bits.

**The alternative** is OpenSSH's SSHSIG with an existing SSH Ed25519 key
(`ssh-keygen -Y sign`), with a namespace such as `cft-certificate`. Its
format is OpenSSH's: armored, with more to parse, and not writable from
this page alone. It is a question for Logan (section 16).

## 11. Version 2's lines, in order

PROPOSED. Lines marked (K) appear in a keyed certificate only. Groups
repeat as their count says.

**The header:**

| line | values |
|---|---|
| `cft-certificate 2` | the magic line |
| `mode <m>` | as in version 1 |
| `salt-commitment <digest>` (K) | as in version 1, with its tag unchanged |
| `build-id`, `backend`, `device-xclbin`, `device-version`, `device-caps`, `device-tiles` | as in version 1 |
| `profile` through `initial` | section 9.2, in its order |
| `runs <R>` | as in version 1 |

**A run block,** R of them:

| line | values |
|---|---|
| `run <i> main`, `run <i> half-step h-slots <n> <slot> ...`, `run <i> wider` or `run <i> wider-source` | `wider-source` is new (section 8.4) |
| `program-format`, `program-image`, `program-digest` | as in version 1 |
| `source <digest>` or `source none` | section 8.3 |
| `source-name <text>` | with a source only |
| `graph <digest>` | with a source only |
| `compiler none` or `compiler <name> <n> <text>` | with a source only |
| `source-params <p>`, then p lines `source-param <name> <literal>` | with a source only |
| `lanes`, `steps`, `stream-a`, `stream-b`, `stream-c`, `parameters`, `parameter` | as in version 1 |
| `lane-flags <yes or no>` | section 6 |
| `segments <S>` | as in version 1 |
| `segment <k> start <h> end <h> flags <n> status <n> [lanes <h>]` | the `lanes` pair exactly when `lane-flags yes` |
| `replays <m>`, then m lines `replay <k> marked <n> changed <c> raw-end <digest> raw-lanes <digest>` | section 7.4: one line for each segment that marked a lane |
| `output <digest>` | as in version 1 |

**The accuracy block** is version 1's, with `wider-source` as a fourth
method: its kind is `estimate`, and it uses a wider-source run. **The
end** is version 1's: `end`, then `hash`.

Two relation rules:
- A `wider` run names no source: its relation is to the main image, not
  to a source.
- A half-step run's source lines are the main run's (`aux-source`).

**An example, for shape only.** Every `<...>` stands for a value, and
none was computed:

    cft-certificate 2
    mode open
    build-id commit=<40 hex> tracked=clean untracked=none
    backend xrt
    device-xclbin <64 hex>
    device-version <8 hex>
    device-caps <8 hex> <8 hex>
    device-tiles 4
    profile 1
    language 1
    device-platform xilinx_u50_gen3x16_xdma_5_202210_1
    device-xrt 2.19.194
    device-clock 135000000
    device-serial withheld
    writer cft-segrun commit=<40 hex> tracked=clean untracked=none
    writer-runtime none
    compiler-build commit=<40 hex> tracked=clean untracked=none
    replay-methods 0
    certificate-id none
    issuer withheld
    issuer-key none
    host-os linux
    host-arch x86_64
    started <time>
    finished <time>
    issued <time>
    supersedes none
    environment 0
    initial given
    runs 2
    run 0 main
    program-format fp64
    program-image <64 hex>
    program-digest <64 hex>
    source <64 hex>
    source-name lorenz63-rk4-fp64.cftl
    graph <64 hex>
    compiler cftc 1 u50-rev7-quad
    source-params 0
    lanes 256
    steps 100
    stream-a <64 hex>
    stream-b <64 hex>
    stream-c <64 hex>
    parameters 0
    lane-flags yes
    segments 3
    segment 0 start <64 hex> end <64 hex> flags 16 status 0 lanes <64 hex>
    segment 1 start <64 hex> end <64 hex> flags 16 status 0 lanes <64 hex>
    segment 2 start <64 hex> end <64 hex> flags 16 status 0 lanes <64 hex>
    replays 0
    output <64 hex>
    run 1 wider-source
    program-format fp128
    ... the same source and params, its own graph, the same compiler ...
    accuracy 1
    entry 0 wider-source
    kind estimate
    uses 1
    scope max-lanes
    value enclosed fp64 <element> <element>
    end
    hash <64 hex>

## 12. The audit in version 2

PROPOSED.

**What an auditor is handed, beyond version 1:**
- the sources, run by run;
- the lane-flag blocks, in the states directory;
- a signature file, and a keyring;
- the certificate this one supersedes;
- the auditor's own choice of a definition re-run.

**The order.** Version 1's ten steps, with these inserted or extended:
- **1. Integrity.** As in version 1.
- **2. Form.** The strict reader, with the new lines' spellings and form
  rules (`marked`, `replay-lane-flags`, `replay-source`,
  `replay-method`, `provenance-order`, and `changed` at most `marked`,
  `malformed`). Then the auditor's choice (`choice`).
- **2a. The signature,** when one is handed: `signature-format`,
  `signature`, `signature-key`, `signer`.
- **3. Salt.** As in version 1.
- **3a. The superseded certificate,** when one is handed: its body hash
  must be the one named (`supersedes`).
- **4. Programs.** As in version 1.
- **4a. Sources:** section 8.7.
- **5. Streams, and 6. Continuity.** As in version 1. Continuity runs on
  the certified, corrected chain.
- **7. States handed.** As in version 1, plus:
  - the lane-flag blocks handed (`lane-flags-shape`, `lane-flags-hash`,
    `lane-flags-identity`);
  - the initial state regenerated, where the generator is known
    (`initial-state`).
- **8. Relations.** As in version 1, plus the wider-source run's, and
  `aux-source`. `aux-h-slots` is strengthened where the source is
  handed. A wider-source relation without its source refuses
  `source-missing`.
- **9. Re-runs.** As in version 1, plus the lane flags and the replays
  (section 7.5).
- **9a. The definition re-run.** Only where the auditor chooses it: each
  chosen segment is run by the source's interpreter too, and must end on
  the certified state with the certified flags and block
  (`definition-end`, `definition-flags`). This is the check for a
  hand-written image that a source defines.
- **10. Accuracy.** As in version 1, with `wider-source` entries.

At every step that re-derives through the definition, a failure is
refused `definition-differs` wherever the auditor's definition does not
cover the certificate's (section 7.6), and by its own name otherwise.
Those steps are:
- 4's load checks (`program-image`, `program-format`, `program-shape`),
  which run the program model's loader;
- 4a's language checks and recompile;
- 8's wider-source relation;
- 9's re-runs and replays, and 9a.

An auditor that cannot evaluate the definition refuses
`definition-unavailable` where it first needs it.

**The new refusals:**

| name | exit | when |
|---|---|---|
| `marked` | 2 | a segment line's STATUS carries STATUS[6] |
| `replay-lane-flags` | 2 | a run with replay lines says `lane-flags no` |
| `replay-source` | 2 | a run with replay lines names no source |
| `replay-method` | 2 | a run with replay lines that no `replay-method` line names, or a `replay-method` line for a run with none, or for no run |
| `provenance-order` | 2 | `started` is after `finished`, or `finished` after `issued` |
| `signature-format` | 4 | the signature file handed breaks its form |
| `signature` | 4 | the signature names another certificate, or does not verify |
| `signature-key` | 4 | the signing key is not the certificate's `issuer-key` |
| `signer` | 4 | a keyring handed names the signing key under another name than the `issuer` |
| `supersedes` | 4 | the superseded certificate handed is not the one named |
| `source-digest` | 4 | a source handed is not the one its run names |
| `source-refused` | 4 | the language refuses a source handed, at the run's format |
| `source-format` | 4 | a main run's format is not its source's own |
| `source-graph` | 4 | the source's step graph is not the one named |
| `source-param` | 4 | a source param names no param, or its literal is not a canonical constant |
| `source-image` | 4 | the source, compiled by the named compiler and output version, is not the run's image or bank |
| `source-missing` | 4 | a check needs a source that was not handed: a replay, a wider-source relation, a definition re-run |
| `lane-flags-shape` | 4 | a block handed is not the run's lanes long, or belongs to a segment or run that has none |
| `lane-flags-hash` | 4 | a block handed is not the certified one |
| `initial-state` | 4 | the named generator does not regenerate boundary 0 |
| `lane-flags-identity` | 5 | a block handed disagrees with its segment line's flag word or STATUS[5:4], or a byte carries [7] |
| `aux-source` | 5 | an auxiliary run's source lines are not its relation's |
| `segment-lane-flags` | 6 | a re-run segment's corrected block is not the certified one |
| `replay-missing` | 6 | a re-run segment marked a lane, and has no replay line |
| `replay-unmarked` | 6 | a replay line names a segment whose re-run marked no lane |
| `replay-raw` | 6 | a replay line's `raw-end`, `raw-lanes` or `marked` is not the re-run's |
| `replay-changed` | 6 | `changed` is not the number of marked lanes the replay changed |
| `definition-end` | 6 | (the auditor's choice) the definition's run of a segment does not end on its certified state |
| `definition-flags` | 6 | (the auditor's choice) it does not raise the certified flags or block |
| `definition-differs` | 78 | a re-derivation failed, and the auditor's definition does not cover the certificate's `profile` and `language` (section 7.6) |
| `definition-unavailable` | 78 | the auditor cannot evaluate the definition: no mpmath, or an enclosure at its precision cap |
| `compiler-differs` | 78 | a recompile differs, and the auditor's compiler is another name or output version |

Version 1's names are reused where they fit:
- `aux-format`, `aux-lanes`, `aux-image`, `aux-segments`, `aux-streams`
  and `aux-start` for the wider-source relation;
- `aux-h-slots`, strengthened;
- `segment-end`, `segment-flags` and `segment-status`, against the
  corrected values;
- `accuracy-run`, for a wider-source entry on a run of the wrong kind;
- `malformed`, `line-missing`, `line-order`, `line-unexpected` and
  `count`, for the new lines.

**What the verdict adds:**
- the certificate's name, its body hash;
- each header statement: stated and not checked, unknown, none, or
  withheld;
- the signature: verified, and by whom if a keyring was handed;
- each source: checked by recompiling with the named compiler, or named
  and not handed;
- the replays: how many lanes in how many segments were replayed, each
  checked against the definition;
- the definition: the certificate's `profile` and `language`, and the
  auditor's own;
- the blocks: re-run and matched, or handed and consistent;
- the initial state: regenerated, or handed;
- what the audit was handed, as three levels, after ACM's and NISO's
  vocabulary:
  - **re-run**, from states handed;
  - **re-run from the start**, from the initial states alone;
  - **rebuilt**, from the source, the initial generator and nothing
    binary of the producer's: no image, bank or state. This is the
    nearest a certificate comes to ACM's "without the use of
    author-supplied artifacts".

The auditor's own identity and the audit's time go in a header above the
verdict's lines, with its mpmath version wherever it evaluated the
definition (section 5). The comparison between auditors leaves that
header out, as the corpus check leaves out build-id.

## 13. Compatibility, and what each implementation needs

PROPOSED.

**Readers.** A version-1 reader already refuses version 2, by `version`
at step 4 of the strict reader (exit 2). Both auditors should read both
versions, choosing by the magic line:
- version 1 goes to version 1's reader and audit, unchanged. Its
  verdicts stay byte for byte as they are today, and the corpus holds
  them;
- version 2 goes to version 2's.

Two version-1 controls change their expected verdict. A version-1 body
under `cft-certificate 2` now reaches version 2's reader, so it is
`line-missing` where it was `version` (section 14 names both).

Certificates of version 1 exist and keep being written: the corpus's
twelve, cft-orbits' certificates, and every marked run whose producer
wants the machine's own values (section 7.2).

**Hash tags.** Version 1's tags are kept in version 2:
`cft-certificate 1 salt`, `cft-certificate 1 state` and the three stream
tags. A state then has the same hash in both versions, so a version-1
and a version-2 certificate of one run carry the same run hashes, and
the corpus can hold both to one set of boundary files. A replay line's
raw end is a state, so it takes the state tag too. New objects get new
tags: the block's `cft-certificate 2 lane-flags`, and the signature's
`cft-signature 1`.

**What each implementation needs:**
- **The golden writer** (`cert.py`):
  - version-2 objects and their encoding;
  - lane flags from `Result.lane_flags` (R8's model);
  - replays by `lang.run` on the marked lanes, spliced into the chain,
    with `replay-method <r> golden` for each run that has them. Where
    transcend.py raises `ZivEscalation`, it refuses `replay-undecided`;
  - the source lines, computed by the language and cftc and held to the
    image it runs;
  - `profile` and `language`, from the golden model's own versions;
  - the rest of the header, handed to it as the identity lines are
    today;
  - Ed25519, in pure Python and held to RFC 8032's 7.1 vectors.
- **cft-segrun:**
  - `--lane-flags`: it asks for the block (ABI 0.17), and writes it to
    `run-<r>-segment-<k>.flags`. Through a remote handle the block
    travels by PROG_RUN_EX's `want` word, and a server without the
    feature is refused by name (R8's design);
  - `--replay-image IMG`, an option of each run, writing `replay-method
    <r> image <digest>`, with `replay-missing` and `replay-undecided` as
    its refusals. A main run and its wider-source run, at two formats,
    each name their own;
  - `--source SRC --manifest M`, taking the source and compile lines
    from cftc's manifest, `language` among them, and holding the
    manifest's image and bank digests to the files it runs. cftc's
    manifest is fixed-layout JSON, so a strict reader of it in C is
    small;
  - `profile` from the library's own constant;
  - options for the header's statements: issuer, identifier, issuer-key,
    initial and supersedes;
  - measuring the rest itself: the UTC times, the host's OS and
    architecture, its environment list, and the device's extra lines
    through the library;
  - `--format-version 1`, kept for the corpus and for marked runs that
    stay version 1.
- **cft-audit:**
  - both readers;
  - block files in `--states DIR`;
  - re-runs that ask for the block when the run says `yes`;
  - its library's profile, compared with the certificate's. A re-run
    depends on the profile, so a failed re-run under a profile that does
    not cover the certificate's is `definition-differs`;
  - `--signature`, `--keyring` and `--superseded`;
  - Ed25519 in C, held to the same vectors;
  - it takes no source. Section 7.5 and step 8 then refuse
    `source-missing` exactly where the golden auditor, handed no source,
    does, so the gate's rule of one verdict for both auditors holds.
    The gate counts and names each golden call made with a source, as
    it counts version 1's 39 calls that no file spells.
- **The golden audit:** everything above, with `sources`, `signature`,
  `keyring` and `superseded` as arguments, and the definition re-run as
  a choice.
- **cft-orbits** stays on version 1. Its checkpoint, version 3, embeds
  version-1 certificate lines, so moving it is its own parcel.
- **libcft:**
  - `cft_image_id` grows additively with the platform name, the XRT
    version, the clock and the serial. That is an ABI step. The lead's
    call (2026-10-02): it follows as ABI 0.18, with version 2's build;
  - the library states the profile it implements, a constant in cft.h,
    for cft-segrun to write and cft-audit to compare.
- **The definition's versions** (section 7.6):
  - **the profile,** stated by the golden model and by libcft, and
    extended to the program model (section 7.6). A gate would hold both
    to the profile's record, so that no recorded case could move unless
    the profile did. That record is CONFORMANCE.md's vectors
    (`vectors/SHA256SUMS`) and the program sets: the golden corpus's
    states, and the load cases at each loader rule's edge and each
    header field's extremes. The record is a backstop: the rule, not
    the record, defines when the profile steps. The extension changes
    CONFORMANCE.md's versioning rule (question 6);
  - **the language's version,** kept in the golden model and written
    into cftc's manifest, so that cft-segrun can state it. A gate would
    hold it to the language's committed graphs and its refusal tables,
    which could not change unless the version did.
- **cftc and the language:**
  - **a format override** (`--format FMT`): the source with its format
    statement's value replaced. MEASURED: probe 2 compiled Lorenz-63 at
    fp128 that way. The probe used a text replacement; the build defines
    it in the checker.
  - **an output version.** cftc's `VERSION` (1 today, in every manifest)
    would be bumped whenever the bytes it writes for some source can
    change. Nothing reads it today (VCV2: unchanged since cftc's first
    commit). So the `lang` stage must gain the check that the committed
    compiled files cannot change unless `VERSION` does; `source-image`
    against `compiler-differs` depends on it.
  - **`--compiler-id`**, printing the build-id grammar for the
    repository it runs from.
- **R8:**
  - STATUS[6] must reach the host from a tile. The XRT backend's
    `ST_REPORTS` is 0x30, which drops it. R8's design adds bit 6 (R8's
    ledger, MEASURED).
  - R23's "as it covers the counts" is restated by R8 (59b19e6).

**The corpus.** Version 1's cases stay, byte for byte. Version 2 cases to
add:
- flagstep with lane flags, its lanes raising different flags;
- Lorenz-63 compiled from `programs/systems`, with a wider-source run
  and its entry: the case that shows the time shift;
- a replay case, `markstep`:
  - a hand-written program that marks one lane in one segment through
    R24's `RAISE`, and writes a wrong last bit there;
  - a source in `certificates/programs/` defines what it computes;
  - the golden writer makes the case (`replay-method 0 golden`), and
    cft-segrun remakes it with a replay image, the source's compile
    (`replay-method 0 image <digest>`). The two differ only in header
    lines the check normalizes, and everything else must agree byte for
    byte (rule 4). That holds the C writer's replay to the definition;
  - it needs only R8's model, so it can exist before M1;
- every header line spelled out, with a signature under a published test
  key. Like the example salt, that key is printed, so it is never an
  owner's;
- a `supersedes` pair.

## 14. The controls

PROPOSED.

**Carried over.** Every control CERTIFICATES.md counts, applied to version
2's grammar:
- a byte flipped, at every byte;
- every line dropped, an unknown line at every position, every line
  repeated, every adjacent pair exchanged, blocks moved;
- every count one more and one less;
- the encodings' non-canonical spellings, each limit at its edge, every
  allowed word read back as itself;
- the width rule, the decimals and the identity spellings;
- the mode and the salt;
- the inputs' shapes, the chain, the re-runs and the relations;
- accuracy;
- the audit's order, the seed, sampling and what an audit spends.

The census then runs as before: each refusal of version 2's reader and
audit is disabled alone, in a fresh copy, and a named control must go
red.

**New: one planted fault for each check, each caught by name:**

| check | planted fault | caught as |
|---|---|---|
| lane flags present | a `lanes` pair dropped from one segment of a `yes` run; one added in a `no` run (each with the hash line remade) | `malformed` |
| a block's size | a block one byte short, and one byte long | `lane-flags-shape` |
| a block's hash | a block with one byte changed | `lane-flags-hash` |
| R23's identities | a block whose OR lacks the flag word's invalid bit, its hash remade; a byte with [6] set beside STATUS[5] clear; a byte with [7] set | `lane-flags-identity` |
| a re-run block | the certified hash of another block (one lane's inexact cleared) | `segment-lane-flags` |
| the mark at the reader | a segment's STATUS with STATUS[6] set | `marked` |
| replay structure | replay lines in a `lane-flags no` run; in a run with `source none`; out of order; a count one off; `changed` above `marked` | `replay-lane-flags`, `replay-source`, `line-order`, `count`, `malformed` |
| the method lines | a run with replays and no `replay-method` line; a method line for a run without replays; one for a run past the last | `replay-method`, each |
| whether a replay is due | a replay line dropped (the re-run still marks a lane); a line for a segment that marked none | `replay-missing`, `replay-unmarked` |
| raw values | `raw-end` the hash of another state; `raw-lanes` of a block with [7] cleared; `marked` one off | `replay-raw` |
| `changed` | one more, and one fewer, than the replay changes | `replay-changed` |
| the corrected segment | the raw end certified as the segment's end; the raw block as its block; the raw flag word | `segment-end`, `segment-lane-flags`, `segment-flags` |
| the method in the header | the golden writer's certificate (`replay-method 0 golden`) and cft-segrun's (`replay-method 0 image <digest>`) of one marked run; then cft-segrun's with one replayed value changed; then cft-segrun's with another `profile` | equal once the normalized lines are set aside; then not equal, by the gate's name, twice |
| two replay images | a main run and its wider-source run that both mark, replayed by two images at two formats | two `replay-method` lines, each run's own image; the golden audit accepts, and cft-audit refuses `source-missing`, as with one image |
| the definition's version | a certificate naming `language 2` (or `profile 2`) under an auditor at 1, made to fail one replay; the same failure under an auditor at 2 | `definition-differs`; `segment-end` |
| the definition at load | an image the auditor's model refuses at load (513 constants, as after ee78152), under a certificate at an older profile major; then at the auditor's own profile | `definition-differs` at step 4; then `program-image` |
| `language none` | a certificate whose runs name no source, failing a re-run, under an auditor of any language and the certificate's profile | the re-run's own name: `none` is covered |
| an auditor that cannot evaluate | a replay audited without mpmath; an enclosure forced to its cap | `definition-unavailable` |
| no source | a replay audited with no source handed | `source-missing` |
| the source | one byte changed | `source-digest` |
| the language | a source the language refuses | `source-refused` |
| the format | a main run at fp128 naming an fp64 source | `source-format` |
| the graph | another system's graph digest | `source-graph` |
| the params | a source param naming no param; `0.50` for `1/2` | `source-param` |
| the compile | a source param's value changed (the bank differs); the steps changed (the image differs) | `source-image` |
| the compiler | a certificate naming `cftc 2`, audited by `cftc 1`, whose recompile differs | `compiler-differs` |
| the wider-source relation | another source; other params; another target; the same format; another segment count; streams or start not widened | `aux-source`, `aux-format`, `aux-segments`, `aux-streams`, `aux-start` |
| the wider-source image | version 1's wider image (the widened bank) certified as the wider-source run | `source-image` (its own compile, at step 4a) |
| h-slots with a source | a half-step run naming slots 0 and 1 of Lorenz-63's 0, 1 and 2 | `aux-h-slots` |
| the initial state | a generator argument changed | `initial-state` |
| times | month 13, February 30, 24:00:00, a leap second, a lowercase z, an offset, no seconds; started after finished | `malformed`, `provenance-order` |
| absence words | `withheld` where only `unknown` or `none` may stand; a writer asked for the text `none` | `malformed` |
| texts | a space not encoded; `%41` for `A`, a byte that may stand as itself; lower-case hex digits; 256 characters | `malformed` |
| the environment | names out of order, repeated, in lower case | `line-order`, `line-unexpected`, `malformed` |
| the signature file | a line missing; a key of 63 digits | `signature-format` |
| the signature | one bit of it flipped; another certificate's signature file | `signature` |
| the signing key | a valid signature by a key other than `issuer-key` | `signature-key` |
| the keyring | a keyring naming the key as someone else | `signer` |
| `supersedes` | another certificate handed as the superseded one | `supersedes` |
| the definition re-run | a hand-written image whose bank's beta is not the source's | `definition-end` |
| the versions | a version-2 body under `cft-certificate 1`; a version-1 body under `cft-certificate 2`; `cft-certificate 3` | `unknown-line` (at the first version-2 line), `line-missing` (at `profile`), `version` |
| two version-1 controls that move | test_cert.py's `test_magic_and_version` (:442) and the case `2` of `test_a_version_of_any_size_is_a_version` (:2337) put a version-1 body under `cft-certificate 2` and require `version`. Through the dispatching reader that body reaches version 2's reader | `line-missing` (at `profile`), in both tests and in cft-audit's gate, which replays their calls. The other cases of the second test, 2^63 and a version of 5,000 nines, stay `version` |
| version 1 unchanged | every other version-1 control, and the corpus's version-1 verdicts byte for byte, through the dispatching reader | as in version 1 |

## 15. What version 2 still does not do

- **Sign a time.** No time is checked. An RFC 3161 token over the body
  hash would bound `issued` from above. That is for a later version; the
  body hash is what such a token would stamp.
- **Check a time, a place, the issuer without a keyring, the environment,
  or the device's extra lines.** Each is reported.
- **Bind a key to a person.** The keyring is the auditor's input. Version
  2 does not distribute keys or revoke them.
- **Audit sources or replays in C.** cft-audit takes no source, because
  there is no C compiler or interpreter of the language. So a
  certificate with a replay in a re-run segment, or with a wider-source
  run, is the golden auditor's. Where marks come by design (M2 past its
  range), that can be every segment.
- **Decide across definitions.** An auditor whose profile or language
  does not cover a certificate's checks what reproduces under its own
  definition. Where something fails, it refuses `definition-differs`
  rather than decide. Deciding needs the named definition, which means
  the golden model at a commit that implements it.
- **Prove a slower image right.** The audit checks the replayed values
  against the definition instead.
- **Carry a bound, or a value that is not an exact rational.** This is
  unchanged from version 1. The math library will put energies with exp
  or log within a program's reach, but an accuracy entry is still a
  polynomial drift or a difference of states.
- **Certify deposits, lane masks, index tables, or streams that change
  from segment to segment.** Unchanged.
- **Certify cft-orbits' exact route, or give it a wider run.** Its
  constants are derived in each format by its own builder, and a
  wider-source run would need that builder as a named compiler. That is
  not designed here.
- **Record a remote run's depth, or its device's extra lines.** They are
  `unknown`, as in version 1.
- **Countersign.** An auditor's signed verdict is not designed.
- **Publish.** The publication record is step 7's: the gallery's
  DataCite or RO-Crate metadata, with the licence and the contact.
  Version 2 gives that record the certificate's name (its body hash),
  and relations to point at: `IsCompiledBy`, `IsDerivedFrom`,
  `Obsoletes`.
- **Interoperate.** No PROV-O, SLSA or RO-Crate serialization is part of
  version 2. Sections 2 and 3 map the fields, and that mapping is how an
  exporter would write one.
- **Hide provenance with the salt.** A keyed certificate's provenance
  lines are in the clear, or withheld.
- **Make a version-1 certificate version 2.** A version-1 certificate
  stays version 1. Re-certifying the run writes a new certificate, which
  may name the old one in `supersedes`.

## 16. Questions for Logan, with recommendations

These replace the eight questions of 0186a5d. Each decision the study
takes is here, with its recommendation; the section named holds the
argument.

**Marked lanes (item 2)**

1. **What version 2 certifies.** The program's values. A lane the
   machine marks is replayed, and its segment carries the replayed
   value. A mark left unreplayed is refused by name. Version 1 stays the
   record of the machine's own values, mark and all (the lead's
   decision). *Recommended: yes.* (Section 7.)
2. **Who replays.** The golden model on the host is the arbiter, and
   every audit replays by it. A producer may replay with a slower image
   instead; the audit checks that against the golden model. cft-audit
   cannot audit a replayed segment until a C implementation of the
   language exists. *Recommended: yes.* (Sections 7.3 and 7.5.)
3. **M2 at fp256: its range, and what happens past it.** The plan says
   "a stated range, beyond which a lane is marked and replayed", and
   states no width. That is two choices, and they combine:
   - **How wide the range is.**
     - *Wide*, so that no argument a program reaches leaves it, and
       marks stay rare. 2^1024 needs about 1,300 bits of 2/pi
       (gen_2opi.py's rule). That costs five or six scratch slots a
       lane, the STLs that fill them from the bank each segment, and the
       LDX that picks the window by the exponent.
     - *Narrow*: cheaper, but programs leave it. A long run, a forcing
       sin(t) for one, then marks its lanes in every segment.
   - **What happens past it.**
     - *Mark and replay*, as the plan says. The run is certified, at the
       replays' cost: on the host, or on the tile by a slower full-range
       image. A replayed segment is audited by the golden model alone.
     - *Refuse by name.* The routine's own range test knows. Either a
       word in a scratch slot the language defines carries the refusal
       out of the lane, or a writer that replays tests each marked
       lane's argument against the range. The cost is a scratch slot
       and its instructions in every lane, or the range carried to every
       writer. The run is not certified as version 2; version 1 still
       records it.

   *Recommended: a wide range, its cost measured by M2, with mark and
   replay past it. Past a wide range, lanes are rare, so replaying them
   costs less than a refusal's carrier in every lane, and the run stays
   certified.* (Sections 7.1, 7.3 and 7.5.)

**Sources and wider runs (item 3)**

4. **Wider runs.** Add `wider-source`, the same source compiled one
   format wider, beside version 1's `wider`. They estimate different
   errors: on Lorenz-63 they differ by the constants' rounding, 3.5e-15
   at t = 3. *Recommended: keep both, each named.* (Section 8.4.)
5. **Naming the source.** Optional for each run, and required for
   replays and wider-source runs. The keyed mode does not hide it, as it
   does not hide the image. *Recommended: yes.* (Section 8.6.)

**The definition**

6. **Which definition a certificate claims.** Each certificate names
   two things:
   - the conformance profile, extended to version the program model: any
     change to what an accepted image computes, or to whether an image
     loads, steps it, as ee78152's change to seq.py's loader would have.
     The golden corpus and a set of load cases are the gate's backstop;
   - a new language version.

   An auditor under a definition that does not cover the certificate's
   refuses a failure as `definition-differs`, blaming the version, not
   the certificate. Majors would step often while the language is young
   (about four since L1). *Recommended: yes. Extending the profile
   changes CONFORMANCE.md's versioning rule, which is a contract change.*
   (Section 7.6.)
7. **mpmath.** The golden model decides transcendentals through mpmath,
   so the certificate reports the writer's mpmath version when it
   replayed, and the verdict reports the auditor's. MPFR is not carried:
   nothing in making or auditing a certificate calls it. *Recommended:
   yes.* (Section 5.)
8. **The compiler's identity.** cftc's `VERSION` becomes an output
   version, held by a new check in the `lang` stage, and cftc gains a
   format override and `--compiler-id`. *Recommended: yes, with C4 or
   version 2's build, whichever comes first.* (Sections 8.3 and 13.)

**Provenance**

9. **The fields** (section 5).
   - Carried: an identifier, the issuer and its key, the times, the
     host's OS and architecture, the writer, its runtime and the
     compiler's build, the device's platform, XRT version, clock and
     serial, the environment, `supersedes`, the initial generator, and
     how the replays were made.
   - Not carried: the host name, the user, the CPU model, paths, the
     licence, a contact, and free text.
   - The issuer and the device serial are written only on request.
   - `host-os` is by default the OS's name alone (`linux`, `windows`).
     Its version, which for Linux is the kernel's, is written only on
     request, as deb-buildinfo treats a kernel version.
   - An issuer, when there is one, is a name, an ORCID or an
     organisation.

   *Recommended: as listed, with an ORCID for a person, as CodeMeta and
   CODECHECK ask.*
10. **The keyed mode and provenance.** The salt protects states, as in
    version 1, and no provenance line: each line is published or
    withheld. *Recommended: yes. `withheld` hides a line more simply
    than a keyed hash would.* (Section 4, rule 3.)

**Signing and generators**

11. **The signature.** Ed25519 (RFC 8032) over the body hash, in a
    five-line file of this project's own; or OpenSSH's SSHSIG, to sign
    with his SSH key. *Recommended: Ed25519.* (Section 10.)
12. **Initial-state generators.** Named generators in the golden model,
    A1's first, so that an open certificate's initial state can be
    regenerated. *Recommended: yes, after version 2's core.* (Section
    9.3.)

**For the lead, not Logan:**
- **Decided** (the lead's ledger, 2026-10-02 11:13). The device's extra
  lines follow as ABI 0.18, with version 2's build. The corpus cases of
  section 13, and whether cft-segrun reads cftc's manifest, go to the
  version-2 build parcel's brief.
- **R8 and ST_REPORTS.** The XRT backend's mask (0x30) drops STATUS[6],
  so a card certificate would lose the mark. R8 has been told and is
  fixing it.
- **New with this revision:**
  - where the profile and language versions live (the golden model,
    cft.h, cftc's manifest);
  - the profile's program sets: the golden corpus's states, and the load
    cases;
  - the gates that hold them (section 13);
  - the `lang` stage's check on cftc's `VERSION`.

## 17. Sources

All read on 2026-10-02, as section 2 marks them (page or search).

- ISO/IEC 17025:2017, through these secondary sources:
  - H. A. Wade, "How to Read & Interpret ISO/IEC 17025 Calibration
    Certificates", Quality Magazine, 2024-09-03:
    https://qualitymag.com/articles/98235-how-to-read-and-interpret-iso-iec-17025-calibration-certificates
  - European co-operation for Accreditation, FAQ 42.1:
    https://european-accreditation.org/sp_accordion_faqs/42-1-question-on-reporting-iso-iec-170252017-cl-7-8-2-1-l/
  - European co-operation for Accreditation, FAQ 45.2:
    https://european-accreditation.org/sp_accordion_faqs/45-2-question-on-amendments-to-test-reports-iso-iec-17025-clause-7-8-8-1/
  - CASRAI, "Calibration Certificates & NIST Traceability":
    https://casrai.org/guides/calibration-certificate
- VIM (JCGM 200), entry 2.41: https://jcgm.bipm.org/vim/en/2.41.html
- PTB, the Digital Calibration Certificate: https://www.dmet.ptb.de/dcc
  and its schema 3.0.0,
  https://www.ptb.de/dcc/v3.0.0/autogenerated-docs/dcc_xsd.htm
- W3C PROV-DM: https://www.w3.org/TR/prov-dm/ ; PROV-O:
  https://www.w3.org/TR/prov-o/
- SLSA provenance v1.0: https://slsa.dev/spec/v1.0/provenance ; v0.2:
  https://slsa.dev/spec/v0.2/provenance
- in-toto attestation framework v1:
  https://github.com/in-toto/attestation/blob/main/spec/v1/README.md
  (with statement.md and envelope.md beside it)
- DSSE: https://github.com/secure-systems-lab/dsse/blob/master/protocol.md
- deb-buildinfo(5):
  https://manpages.debian.org/testing/dpkg-dev/deb-buildinfo.5.en.html
- SOURCE_DATE_EPOCH: https://reproducible-builds.org/specs/source-date-epoch/
- RO-Crate 1.1:
  https://www.researchobject.org/ro-crate/specification/1.1/root-data-entity.html
  and
  https://www.researchobject.org/ro-crate/specification/1.1/provenance.html
- Workflow Run Crate profiles:
  https://www.researchobject.org/workflow-run-crate/profiles/process_run_crate/
  (and `workflow_run_crate/`, `provenance_run_crate/`)
- CodeMeta terms: https://codemeta.github.io/terms/
- DataCite Metadata Schema 4.6:
  https://datacite-metadata-schema.readthedocs.io/en/4.6/properties/overview/
  and its relationType appendix
- SWHID: https://www.swhid.org/ and
  https://www.swhid.org/swhid-specification/v1.2/5.Core_identifiers/
- cascad: https://www.cascad.tech/
- CODECHECK configuration 1.0: https://codecheck.org.uk/spec/config/1.0/
- ACM Artifact Review and Badging v1.1, as reproduced by SIGIR:
  https://sigir.org/general-information/acm-sigir-artifact-badging/ ;
  its Artifacts Available text as WNS3 2024 gives it:
  https://www.nsnam.org/research/wns3/wns3-2024/artifacts ; ETAPS
  artifact badges: https://etaps.org/about/artifact-badges
- RFC 8032: https://www.rfc-editor.org/rfc/rfc8032 ; RFC 3161:
  https://www.rfc-editor.org/rfc/rfc3161 ; RFC 3339:
  https://www.rfc-editor.org/rfc/rfc3339
- OpenSSH PROTOCOL.sshsig:
  https://raw.githubusercontent.com/openssh/openssh-portable/master/PROTOCOL.sshsig

From this tree: [CERTIFICATES.md](../CERTIFICATES.md),
[ROADMAP.md](../ROADMAP.md) (step 6's plan, and step 3's "What it is
not"), [SEQUENCER.md](../SEQUENCER.md) (R23),
[LANGUAGE.md](../LANGUAGE.md), [ORBITS.md](../ORBITS.md) ("Certified
runs"), [HOSTAPI.md](../HOSTAPI.md) ("Identity at ABI 0.15"),
[ACC-A-estimates.md](ACC-A-estimates.md),
[CONFORMANCE.md](../../CONFORMANCE.md) ("Versioning"), python/cftc,
python/cft_golden/transcend.py, python/tests/test_cert.py,
programs/acceptance.py, certificates/MANIFEST, and the step-6 round's
surveys, R8's ledger and verifier-VCV2's ledger
(`Data/runs/2026-10-02-step6-round/`).

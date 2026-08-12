# Primary Source Ledger

Last checked: 2026-07-14

Only the fact listed in the final column is licensed by each source for this
study. Broader claims require additional evidence.

| ID | Primary/official source | Fact supported |
|---|---|---|
| S01 | [NIST FIPS 180-4, Secure Hash Standard](https://csrc.nist.gov/files/pubs/fips/180-4/final/docs/fips180-4.pdf) | Defines approved secure hash algorithms used to compute message digests |
| S02 | [NIST FIPS 186-5, Digital Signature Standard](https://csrc.nist.gov/pubs/fips/186-5/final) | Digital signatures detect unauthorized modification and authenticate a signatory under the signature model |
| S03 | [NIST Digital Signatures overview](https://csrc.nist.gov/Projects/digital-signatures) | Separates signer assurance from assurance that signed information was not modified after signing |
| S04 | [Git data model](https://git-scm.com/docs/gitdatamodel.html) | Git objects are content-addressed and commits identify trees/parents/metadata |
| S05 | [Git signature formats](https://git-scm.com/docs/signature-format.html) | Documents supported signature containers for Git objects |
| S06 | [Git tag](https://git-scm.com/docs/git-tag.html) | Annotated tags can be cryptographically signed and verified |
| S07 | [Git SHA-256 transition](https://git-scm.com/docs/hash-function-transition/2.49.0.html) | Git's object-format transition is distinct from hashing exported release artifacts |
| S08 | [Semantic Versioning 2.0.0](https://semver.org/) | Public API compatibility rules; major version zero denotes initial development |
| S09 | [Python packaging version specifiers](https://packaging.python.org/en/latest/specifications/version-specifiers/) | Defines Python development and prerelease version syntax |
| S10 | [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) | Defines a generic statement binding subjects to a predicate |
| S11 | [SLSA Build Provenance v1.2](https://slsa.dev/spec/v1.2/build-provenance) | Defines the SLSA provenance predicate, build definition, external/internal parameters, resolved dependencies, builder, and run details |
| S12 | [SLSA Build Track](https://slsa.dev/spec/v1.2/build-track-basics) | Defines increasing provenance/build assurance properties; it does not certify scientific truth |
| S13 | [SLSA artifact verification](https://slsa.dev/spec/v1.2/verifying-artifacts) | Verification includes artifact identity and provenance policy, not signature cryptography alone |
| S14 | [Sigstore: signing blobs](https://docs.sigstore.dev/cosign/signing/signing_with_blobs/) | Documents artifact/blob signing and bundle production |
| S15 | [Sigstore: verification](https://docs.sigstore.dev/cosign/verifying/verify/) | Documents identity-aware signature verification and required verifier inputs |
| S16 | [GitHub artifact attestations](https://docs.github.com/en/actions/concepts/security/artifact-attestations) | GitHub Actions can create signed provenance linking artifacts to a workflow; attestations do not guarantee artifact safety or correctness |
| S17 | [GitHub: generate artifact attestations](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/use-artifact-attestations) | Documents workflow permissions and attestation generation |
| S18 | [GitHub: offline attestation verification](https://docs.github.com/en/actions/how-tos/secure-your-work/use-artifact-attestations/verify-attestations-offline) | Documents retaining bundles/trust material for offline verification |
| S19 | [Zenodo versioning](https://zenodo.org/help/versioning) | Each published version receives a version DOI while a concept DOI represents all versions |
| S20 | [OSF registrations and preregistrations](https://help.osf.io/article/330-welcome-to-registrations) | A preregistration is a time-stamped read-only plan submitted before data collection/analysis; submitted registration files cannot be edited |
| S21 | [ACM Artifact Review and Badging v1.1](https://www.acm.org/publications/policies/artifact-review-and-badging-current) | Separates artifact availability/evaluation from independently reproduced or replicated results |
| S22 | [RFC 8785, JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785.html) | Defines an invariant I-JSON serialization for repeatable hashing/signing; it is informational, not IETF Standards Track |
| S23 | [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) | Fixes `_type` as `https://in-toto.io/Statement/v1` and binds subjects by digest to a named predicate type |
| S24 | [in-toto Envelope v1](https://github.com/in-toto/attestation/blob/main/spec/v1/envelope.md) | Defines the authentication envelope and recommends DSSE without requiring consumers to trust predicate media-type hints |
| S25 | [Sigstore Bundle Format](https://docs.sigstore.dev/about/bundle/) | A Sigstore attestation bundle contains a DSSE envelope whose payload is an in-toto Statement plus verification material such as certificates, timestamps, and transparency entries; exact bundle version must be pinned |
| S26 | [Trail of Bits rfc8785.py v0.1.4](https://github.com/trailofbits/rfc8785.py/tree/v0.1.4) | Identifies the pure-Python JCS implementation selected for the synthetic pilot; conformance still requires independent vectors |
| S27 | [DSSE protocol](https://github.com/secure-systems-lab/dsse/blob/master/protocol.md) | Defines pre-authentication encoding that binds payload type and payload bytes before signature verification; DSSE itself does not define PKI or identity trust |
| S28 | [actions/attest v4.1.1](https://github.com/actions/attest/releases/tag/v4.1.1) and [exact commit](https://github.com/actions/attest/commit/a1948c3f048ba23858d222213b7c278aabede763) | Identifies the official action release and exact verified commit selected for the draft production workflow; new integrations use `actions/attest` rather than its legacy provenance wrapper |
| S29 | [GitHub CLI v2.96.0](https://github.com/cli/cli/releases/tag/v2.96.0) and [exact commit](https://github.com/cli/cli/commit/b300f2ec7ec9dc9addc39b2ad88c54097ded7ca0) | Identifies the verifier release and source revision selected for the production-gate draft |
| S30 | [GitHub CLI attestation verification manual](https://cli.github.com/manual/gh_attestation_verify) | Defines bundle/trusted-root, exact certificate identity, signer/source digest, source ref, predicate, hosted-runner, and JSON-output policy flags; warns that workflow-controlled predicate content is not independently truthful |
| S31 | [GitHub CLI trusted-root manual](https://cli.github.com/manual/gh_attestation_trusted-root) | Documents producing trusted-root material for offline verification; an archived root still needs an independently trusted bootstrap and lifecycle policy |
| S32 | [GitHub Actions secure-use reference](https://docs.github.com/en/actions/reference/security/secure-use) | States that a full-length action commit SHA is the immutable action reference and must be checked against the authentic action repository |
| S33 | [GitHub immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases) | Published immutable releases lock the associated tag and assets and generate a release attestation; the feature must be enabled and applies only to future releases |
| S34 | [GitHub release-integrity verification](https://docs.github.com/en/code-security/how-tos/secure-your-supply-chain/secure-your-dependencies/verify-release-integrity) | Documents release and asset verification and notes that generated source ZIP/TAR downloads cannot be verified as release assets |
| S35 | [Zenodo published-file management](https://help.zenodo.org/docs/deposit/manage-files/) | Zenodo permits some post-publication file corrections without changing the DOI; this project therefore imposes a stricter new-bytes/new-version rule rather than claiming repository-level immutability |
| S36 | [Crossref versioning, corrections, and retractions](https://www.crossref.org/documentation/principles-practices/best-practices/versioning/) | Editorially significant changes should be represented by a linked correction/update/retraction object rather than silently replacing the original record |
| S37 | [Pinned `actions/attest` v4.1.1 README](https://github.com/actions/attest/blob/a1948c3f048ba23858d222213b7c278aabede763/README.md) | Distinguishes default mode, where the action generates SLSA provenance, from custom mode, where the workflow supplies the predicate type and content |
| S38 | [Pinned bundled default-provenance implementation](https://github.com/actions/attest/blob/a1948c3f048ba23858d222213b7c278aabede763/dist/index.js#L123497-L123544) | The selected action's default predicate contains workflow external parameters and a resolved Git dependency, but not A.M.Y's proposed source-dirty object or custom material dependencies |
| S39 | [Science record for Stodden et al.](https://doi.org/10.1126/science.aah6168) | The article *Enhancing reproducibility for computational methods* is a 2016 Science record, volume 354, issue 6317, pages 1240–1241 |
| S40 | [Current arXiv record 2606.04990](https://arxiv.org/abs/2606.04990) | Supplies the current official title, author list, version history, and preprint status used to check the formal paper's local `wang2026provenance` metadata |
| S41 | [NEFFy publisher record](https://doi.org/10.1093/bioinformatics/btaf222) | Establishes that the related-work title named by the DNA paper resolves to a publisher record; it does not validate the paper's unretained novelty-search procedure |
| S42 | [Caveat emptor publisher record](https://doi.org/10.1093/nar/gkag608) | Establishes that the related-work title named by the DNA paper resolves to a publisher record; it does not validate the paper's unretained novelty-search procedure |
| S43 | [AI in bioinformatics publisher record](https://doi.org/10.1016/j.compbiolchem.2026.109217) | Establishes that the related-work title named by the DNA paper resolves to a publisher record; it does not validate the paper's unretained novelty-search procedure |
| S44 | [JSON Schema Core, Draft 2020-12](https://json-schema.org/draft/2020-12/json-schema-core) | Defines the core schema vocabulary used to validate the v2 policy and terminal-result document structures; schema validity does not authenticate the schema bytes |
| S45 | [Cosign advisory GHSA-whqx-f9j3-ch6m](https://github.com/sigstore/cosign/security/advisories/GHSA-whqx-f9j3-ch6m) | Cosign versions through 2.6.1 and 3.0.3 could accept an unrelated valid Rekor entry in affected verification paths; 2.6.2 and 3.0.4 are the first patched releases in those maintained major lines |
| S46 | [Cosign `verify-blob` command reference](https://github.com/sigstore/cosign/blob/main/doc/cosign_verify-blob.md) | Defines bundle, exact certificate identity, exact OIDC issuer, optional trusted-root, timeout, and insecure bypass flags for blob verification; this study forbids regex identities and the SCT/Tlog bypasses |
| S47 | [Python `subprocess` documentation](https://docs.python.org/3/library/subprocess.html) | `start_new_session=True` requests `setsid()`, `close_fds=True` closes inherited descriptors other than standard streams, and an explicit `env` mapping replaces rather than augments the inherited environment; these controls do not constitute a network or filesystem sandbox |
| S48 | [Python `time` documentation](https://docs.python.org/3/library/time.html#time.CLOCK_BOOTTIME) | On Linux, `CLOCK_BOOTTIME` is monotonic and includes time while the system is suspended; generic monotonic-clock availability alone does not establish that property |
| S49 | [Linux `clock_gettime(2)`](https://man7.org/linux/man-pages/man2/clock_gettime.2.html) | Defines Linux `CLOCK_BOOTTIME` as suspend-aware and nonsettable, unlike `CLOCK_MONOTONIC` which omits suspended time |
| S50 | [Apple `mach_continuous_time`](https://developer.apple.com/documentation/driverkit/mach_continuous_time) | Defines a monotonic tick clock that continues while macOS is asleep; `mach_absolute_time` does not have that sleep-inclusive property |
| S51 | [Linux `rename(2)`](https://man7.org/linux/man-pages/man2/rename.2.html) | Ordinary rename may atomically replace an existing destination, while `RENAME_NOREPLACE` fails if the destination exists and depends on filesystem support |
| S52 | [POSIX `fsync`](https://man7.org/linux/man-pages/man3/fsync.3p.html) | `fsync` requests synchronized completion for the referenced open file and may fail with EINTR, EIO, or EINVAL; exact persistence guarantees remain implementation/configuration dependent |
| S53 | [Docker none network driver](https://docs.docker.com/engine/network/drivers/none/) | `--network none` isolates a container from external networking but still creates a loopback device; this is not equivalent to proving that no socket communication is possible |
| S54 | [The Update Framework Specification v1.0.34](https://theupdateframework.github.io/specification/v1.0.34/index.html) | Defines trusted metadata roles and client checks for rollback, freeze, mix-and-match, wrong-file, and bounded-download attacks in software update systems; these properties require TUF state and do not arise from a stateless artifact signature |
| S55 | [Reproducible Builds definition](https://reproducible-builds.org/docs/definition/) | Defines a reproducible build as one for which the same source, build environment, and instructions let another party recreate bit-for-bit identical specified artifacts |
| S56 | [National Academies, *Reproducibility and Replicability in Science*](https://nap.nationalacademies.org/catalog/25303/reproducibility-and-replicability-in-science) | The consensus study distinguishes computational reproducibility from replication with new data and frames access to data, code, and computational methods as part of assessing prior results |
| S57 | [Center for Open Science, Registered Reports](https://www.cos.io/initiatives/registered-reports) | Describes peer review of the research question and methodology before outcomes are known and in-principle acceptance conditional on following the registered protocol and quality controls |
| S58 | [Lu et al., *The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery*](https://arxiv.org/abs/2408.06292) | The authors describe a framework that generates research ideas, writes and runs code, produces figures and papers, and applies a simulated review process in three machine-learning subfields |

## Interpretation rules

- A SHA standard supports digest computation, not author identity.
- A digital-signature standard supports authenticity/integrity properties under
  a trust model, not the truth of the signed proposition.
- SLSA and in-toto are supply-chain provenance formats, not peer review.
- A DOI supplies a persistent version identifier; it is not a cryptographic
  signature and does not itself prove correctness.
- Canonical JSON makes serialization repeatable; authenticity still requires an
  authenticated digest/subject and trust policy.
- Artifact availability, artifact functionality, reproduction, and replication
  are reported as separate outcomes.
- A real bibliographic record does not authenticate a local citation, reproduce
  a search strategy, or validate a novelty judgment.
- A primary paper about an autonomous research agent supports what its authors
  reported about that system; it is not independent verification of those
  capabilities or of generated scientific claims.

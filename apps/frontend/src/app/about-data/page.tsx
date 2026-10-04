import type { Metadata } from "next";

import { ConfidenceBadge, OriginBadge } from "@/components/graph-ui";
import { DataVersion } from "@/components/privacy/data-version";
import { List, NoticeLayout, NoticeSection, NoticeSub, NoticeTable } from "@/components/privacy/notice-layout";
import { PrivacyEmail } from "@/components/privacy/privacy-contact";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";
import { PRIVACY_EMAIL } from "@/lib/api/config";

export const metadata: Metadata = {
  title: "About this data",
  description: "Where the atlas comes from, how confidence works, and how researchers and doctors can claim or remove their entry.",
};

const TOC = [
  { id: "sources", title: "Sources and licences" },
  { id: "trust", title: "Confidence and labels" },
  { id: "version", title: "Data version" },
  { id: "people", title: "People in the atlas" },
  { id: "claim", title: "Claim, correct or remove" },
];

const link = "font-medium text-foreground underline underline-offset-2";

function Src({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a href={href} target="_blank" rel="noopener noreferrer" className={link}>
      {children}
    </a>
  );
}

/** Public graph ids only (e.g. `RES:…`, `INST:…`, `ORCID:…`); anything else is ignored. */
const ENTRY_ID = /^[A-Za-z][A-Za-z0-9_]{0,15}:[A-Za-z0-9_.-]{1,64}$/;

export default async function AboutDataPage(props: PageProps<"/about-data">) {
  const { entry: rawEntry } = await props.searchParams;
  const entry = typeof rawEntry === "string" && ENTRY_ID.test(rawEntry) ? rawEntry : null;
  const subjectText = `Atlas entry: claim, correct or remove${entry ? ` (${entry})` : ""}`;
  const bodyText = entry
    ? `Entry: ${entry}\nI would like to: claim / correct / remove (please choose)\n`
    : "";
  const claimSubject = encodeURIComponent(subjectText);
  const claimHref = `mailto:${PRIVACY_EMAIL}?subject=${claimSubject}${bodyText ? `&body=${encodeURIComponent(bodyText)}` : ""}`;
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="About this data"
        title="Where the atlas comes from"
        description="The graph is built only from public scientific databases and literature. It contains no individual patients. Researchers and doctors appear only with public professional information and can claim or remove their entry."
      />
      <div className="mt-10">
        <NoticeLayout toc={TOC}>
          <NoticeSection id="sources" title="Sources and licences">
            <p>
              Every link in the atlas records its source, the date it was retrieved and a confidence level. We thank the
              teams behind these resources.
            </p>
            <NoticeTable
              caption="Data sources"
              head={["Source", "What we use", "Licence and attribution"]}
              rows={[
                [<Src key="m" href="https://mondo.monarchinitiative.org/">MONDO</Src>, "Disease identifiers, names and synonyms", "CC BY 4.0, Monarch Initiative"],
                [<Src key="h" href="https://www.genenames.org/">HGNC</Src>, "Approved gene symbols and aliases", "Freely available under the HGNC terms of use"],
                [<Src key="hp" href="https://hpo.jax.org/">Human Phenotype Ontology (HPO)</Src>, "Symptom terms and disease–symptom links", "HPO licence, free to use with attribution; this atlas uses the HPO (hpo.jax.org)"],
                [<Src key="c" href="https://www.ncbi.nlm.nih.gov/clinvar/">ClinVar</Src>, "Variant classifications for genes in scope", "Public domain (NCBI, U.S. National Library of Medicine)"],
                [<Src key="mane" href="https://www.ncbi.nlm.nih.gov/refseq/MANE/">NCBI MANE</Src>, "Where each gene sits on the genome (chromosome, start, end; GRCh38)", "Public data, NCBI and EMBL-EBI"],
                ["OMIM numbers", "Disease identifiers", "Taken from HPO annotations, MONDO cross-references and ClinVar; OMIM's own files are not used"],
                [<Src key="cg" href="https://clinicalgenome.org/">ClinGen</Src>, "Gene–disease validity and dosage sensitivity", "Freely available under the ClinGen terms of use"],
                [<Src key="r" href="https://reactome.org/">Reactome</Src>, "Gene to pathway mappings", "Freely available under the Reactome licence terms"],
                [<Src key="g" href="https://geneontology.org/">Gene Ontology (GO)</Src>, "Gene functions and pathways", "CC BY 4.0, Gene Ontology Consortium"],
                [<Src key="o" href="https://www.orphadata.com/">Orphanet</Src>, "Gene associations, symptoms, epidemiology", "CC BY 4.0, Orphanet / INSERM (Orphadata); links we compute from it are our modification, not Orphanet's"],
                [<Src key="p" href="https://pubmed.ncbi.nlm.nih.gov/">PubMed</Src>, "Abstracts, authors and affiliations", "NLM terms; abstracts remain the publishers' and authors' work, quoted with a link"],
                [<Src key="ct" href="https://clinicaltrials.gov/">ClinicalTrials.gov</Src>, "Studies, status, sites and investigators", "Public U.S. government data (NLM)"],
                [<Src key="nih" href="https://reporter.nih.gov/">NIH RePORTER</Src>, "Grants, principal investigators, institutions", "Public U.S. government data (NIH)"],
                ["Patient-organisation websites", "Organisation name, diseases served, registries and studies, contact page", "Public web pages, summarised as facts with a link to the page; content remains the organisation's"],
              ]}
            />
          </NoticeSection>

          <NoticeSection id="trust" title="Confidence and labels">
            <NoticeSub title="Confidence">
              <p>
                Each piece of evidence counts by its kind: curated databases most, then peer-reviewed studies, reviews,
                preprints, links inferred by AI, and patient-reported information least. A link computed by the atlas counts by
                its own score and never reaches High. Several independent sources raise confidence; contradicting findings
                lower it. The result is shown as
              </p>
              <p className="flex flex-wrap items-center gap-2">
                <ConfidenceBadge confidence={0.9} /> <ConfidenceBadge confidence={0.6} /> <ConfidenceBadge confidence={0.3} />
              </p>
              <p>with the full breakdown, sources and quotes one click away.</p>
            </NoticeSub>
            <NoticeSub title="Data, hypothesis, and patient-reported">
              <List
                items={[
                  <span key="o" className="inline-flex flex-wrap items-center gap-2">
                    <OriginBadge origin="observed" /> a link stated by a source (a database entry or a quoted sentence in a paper).
                  </span>,
                  <span key="i" className="inline-flex flex-wrap items-center gap-2">
                    <OriginBadge origin="inferred" /> a link computed by the atlas, for example a shared pathway or similar
                    symptoms. A hypothesis to check, not a finding.
                  </span>,
                  <span key="p" className="inline-flex flex-wrap items-center gap-2">
                    <OriginBadge origin="patient_reported" /> <OriginBadge origin="user_contributed" /> shared by users, labelled
                    as such, reviewed first and never treated as cited evidence.
                  </span>,
                ]}
              />
              <p>
                A computed link is one the atlas works out from the data instead of reading it from a source: two diseases
                that list many of the same specific symptoms (rarer symptoms weigh more, as do those a disease often shows), two diseases linked
                to variants in the same gene, genes that act in the same pathway, or genes that lie close together on a
                chromosome. Each is drawn dashed, labelled a hypothesis and shown with its confidence and one line on why it
                exists. Closeness on a chromosome alone is weak evidence: nearby genes can be lost or duplicated together,
                but most are unrelated.
              </p>
              <p>
                When no route between two things passes the confidence threshold, the atlas says so and names the missing
                evidence instead of guessing.
              </p>
            </NoticeSub>
          </NoticeSection>

          <NoticeSection id="version" title="Data version">
            <p>
              The atlas is rebuilt as a whole from its sources; each build has a version recorded with source versions, file
              hashes and counts. The version you are seeing: <DataVersion />. Symptom annotations come from the HPO release of
              2 September 2026.
            </p>
          </NoticeSection>

          <NoticeSection id="people" title="People in the atlas">
            <p>
              This section is our notice to researchers and doctors who appear in the atlas (GDPR Art. 14), because their
              information was not collected from them directly.
            </p>
            <List
              items={[
                <>
                  <strong>What:</strong> name, institution, and public professional activity: papers you authored, grants you
                  lead, clinical trials you investigate, and your institution&apos;s public pages. Nothing private, no contact
                  details beyond what those sources publish.
                </>,
                <>
                  <strong>Where from:</strong> PubMed author and affiliation metadata, NIH RePORTER, ClinicalTrials.gov and
                  institution pages. Authors and investigators are taken from this metadata, never generated by an AI model.
                </>,
                <>
                  <strong>Why:</strong> so that patient communities and researchers can find who already works on a disease
                  mechanism, even under a different gene or disease name.
                </>,
                <>
                  <strong>Legal basis:</strong> legitimate interest (GDPR Art. 6(1)(f)), limited to public professional
                  information.
                </>,
                <>
                  <strong>Who sees it:</strong> anyone using the atlas. It is not sold or used for advertising.
                </>,
                <>
                  <strong>How long:</strong> while it appears in the public sources; each new data version is rebuilt from
                  them.
                </>,
                <>
                  <strong>Your rights:</strong> access, correction, erasure, restriction and the right to object, plus the right
                  to complain to a supervisory authority. No automated decisions are made about you.
                </>,
              ]}
            />
          </NoticeSection>

          <NoticeSection id="claim" title="Claim, correct or remove your entry">
            {entry && (
              <p className="rounded-lg border bg-muted/40 px-3 py-2" data-testid="claim-entry">
                Your request is about the entry <code className="font-mono text-foreground">{entry}</code>.
              </p>
            )}
            <p>
              <strong>There is no in-app form for this yet.</strong> Please write to the privacy contact instead:
            </p>
            <ol className="list-decimal space-y-1.5 pl-5">
              <li>
                Send an e-mail to <PrivacyEmail />
                {PRIVACY_EMAIL && (
                  <>
                    {" "}
                    (
                    <a href={claimHref} className={link} data-testid="claim-mailto">
                      start the e-mail
                    </a>
                    )
                  </>
                )}{" "}
                with the subject &ldquo;{subjectText}&rdquo;.
              </li>
              <li>
                {entry
                  ? "Say whether you want to claim, correct or remove it; the entry id above tells us which one."
                  : "Include the link to your entry in the atlas and say whether you want to claim, correct or remove it."}
              </li>
              <li>
                Write from an e-mail address listed in a public source about you (for example your institution&apos;s page),
                so we can confirm it is you without asking for identity documents.
              </li>
            </ol>
            {!PRIVACY_EMAIL && (
              <p data-testid="claim-no-email">
                This deployment has not published its privacy address yet, so the request cannot be sent from here.
                Keep the subject above{entry ? " with the entry id" : ""}, and send it once the address appears on this
                page or in the privacy notice. Nothing about your entry changes until then.
              </p>
            )}
            <p>
              We reply within one month. If you object, we remove your entry and keep it out of future data versions unless
              there are compelling legitimate grounds, which we would explain to you.
            </p>
          </NoticeSection>
        </NoticeLayout>
      </div>
    </PageContainer>
  );
}

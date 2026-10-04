import type { Metadata } from "next";
import Link from "next/link";

import {
  List,
  NoticeLayout,
  NoticeSection,
  NoticeSub,
  NoticeTable,
  Summary,
} from "@/components/privacy/notice-layout";
import { PrivacyEmail, ToBeCompleted } from "@/components/privacy/privacy-contact";
import { PageContainer, PageHeader } from "@/components/shell/page-placeholder";

export const metadata: Metadata = {
  title: "Privacy notice",
  description: "What Amber collects, why, how long it is kept, and how to use your rights.",
};

const LAST_UPDATED = "5 October 2026";

const TOC = [
  { id: "who", title: "Who is responsible" },
  { id: "what", title: "What we collect" },
  { id: "why", title: "Why, and on which legal basis" },
  { id: "never", title: "What we never do" },
  { id: "recipients", title: "Who receives data" },
  { id: "retention", title: "How long we keep it" },
  { id: "rights", title: "Your rights" },
  { id: "california", title: "California residents" },
  { id: "children", title: "Children" },
  { id: "ai", title: "AI transparency" },
  { id: "security", title: "Security and incidents" },
  { id: "contact", title: "Contact and complaints" },
];

const link = "font-medium text-foreground underline underline-offset-2";

export default function PrivacyPage() {
  return (
    <PageContainer className="max-w-6xl">
      <PageHeader
        eyebrow="Privacy"
        title="Privacy notice"
        description="What Amber collects, why, how long it is kept, and how to use your rights. In plain language, short version first."
      />
      <p className="mt-3 text-xs text-muted-foreground">Last updated {LAST_UPDATED}</p>

      <div className="mt-8 space-y-10">
        <section aria-labelledby="short-h" className="space-y-4">
          <h2 id="short-h" className="text-xl font-semibold tracking-tight">
            The short version
          </h2>
          <Summary
            items={[
              {
                title: "Exploring is anonymous",
                body: "Searching and browsing the atlas needs no account, and we keep no data about guests. We only count, anonymously, which kinds of pages and features are used.",
              },
              {
                title: "Health data only with your consent",
                body: "One explicit consent covers your health information (chats, profile, documents); contributing to the shared atlas needs a separate one. Each is withdrawn in one click.",
              },
              {
                title: "Personal details removed before AI",
                body: "Names, birth dates, addresses and patient IDs are removed before any text reaches an AI model. Uploaded files are deleted right after reading.",
              },
              {
                title: "Nothing sold, nothing shared",
                body: "No advertising, no third-party trackers, no data brokers, no training of AI models on your data.",
              },
              {
                title: "You are in control",
                body: (
                  <>
                    See, correct, download or delete everything in your{" "}
                    <Link href="/profile" className={link}>
                      profile
                    </Link>
                    .
                  </>
                ),
              },
              {
                title: "Information, not diagnosis",
                body: "Amber shows sourced information. It never makes a diagnosis or decisions about you.",
              },
            ]}
          />
        </section>

        <NoticeLayout toc={TOC}>
          <NoticeSection id="who" title="Who is responsible">
            <p>
              Amber — Rare Disease Atlas is run by <ToBeCompleted>controller name and postal address</ToBeCompleted>, the
              controller of your personal data. Privacy contact: <PrivacyEmail />.
            </p>
          </NoticeSection>

          <NoticeSection id="what" title="What we collect">
            <NoticeSub title="If you only explore">
              <p>
                Nothing that identifies you. Guests have no account and no stored data; visits are only counted
                anonymously (see Usage counts). Your browser keeps two small settings on your own device, your theme
                (light or dark) and the explanation style you picked; they contain no health information and are never
                sent to us.
              </p>
            </NoticeSub>
            <NoticeSub title="Usage counts">
              <p>
                On the hosted site, Amber counts how it is used, with Umami running on the operator&apos;s own server. A
                count holds the kind of page (&ldquo;a disease page&rdquo;, &ldquo;a conversation&rdquo;, never which
                disease or which conversation), the website you came from (its address only), your screen size and
                browser language. For a few features Amber counts that they were used, for example that a question was
                sent to Dr. Wu, never what it said. Nothing that names you, your account or anything you type is sent,
                no cookies are set and nothing is stored in your browser. Like any web server, the counting server also
                receives your IP address and your browser&apos;s user agent (browser, operating system, device type) with
                each request. The counts apply to every visitor of the hosted site.
              </p>
            </NoticeSub>
            <NoticeSub title="Account data">
              <List
                items={[
                  "From OpenAI when you sign in with ChatGPT: your name, e-mail address and ChatGPT account ID.",
                  "From Google when you sign in with Google (where offered): your name, e-mail address and Google account ID. We keep no Google tokens.",
                  "With ChatGPT only: an access token, stored encrypted, so the assistant can run on your own ChatGPT plan.",
                  "Your settings: role, language, expert mode, the time you confirmed you are 16 or older, and whether your browser sent a Global Privacy Control signal.",
                  "Only if you are a doctor or researcher and add them: your first and last name, up to three institutions, your ORCID iD and a private link to your entry in the atlas. Visible only to you, not a verification.",
                  "A session cookie that keeps you signed in. It is strictly necessary; we set no optional cookies, so there is no cookie banner.",
                  "Technical logs (error types, not content) for security, kept at most 30 days.",
                ]}
              />
            </NoticeSub>
            <div id="health-data" className="scroll-mt-20">
              <NoticeSub title="Health and genetic data (special category)">
                <p>
                  Health and genetic information is special-category data under the GDPR and sensitive personal information
                  under California law. We only have it if you add it:
                </p>
                <List
                  items={[
                    "Your profile: diagnoses, genes, variants, symptoms (present or not), age or age range, when symptoms started, and optionally your country. Never names, birth dates, addresses or patient numbers.",
                    "Your chats with Dr. Wu, stored with personal details removed.",
                    "Documents you upload: the file is read and deleted immediately; we keep the document type, page count and the findings, each with a short redacted snippet.",
                    "Contributions you choose to publish in the shared atlas.",
                  ]}
                />
              </NoticeSub>
            </div>
          </NoticeSection>

          <NoticeSection id="why" title="Why, and on which legal basis">
            <NoticeTable
              caption="Purposes and legal bases"
              head={["Purpose", "Data", "Legal basis"]}
              rows={[
                ["Your account and the features you ask for", "Account data, settings", "Contract (GDPR Art. 6(1)(b))"],
                [
                  "Optional work details of doctors and researchers, to find your entry in the atlas",
                  "Name, institutions, ORCID iD, the entry you link",
                  "Contract (Art. 6(1)(b))",
                ],
                [
                  "Your chats with Dr. Wu, your private profile and reading your documents, to find connections for you",
                  "Health and genetic data you type, confirm or upload",
                  "Your explicit consent to the use of your health information, asked once before the first use (Art. 9(2)(a))",
                ],
                [
                  "Publishing your contributions in the shared atlas",
                  "What you submit, without your name",
                  "Your separate explicit consent for contributing (Art. 9(2)(a))",
                ],
                ["Security and abuse prevention", "Technical logs, rate-limit counters", "Legitimate interest (Art. 6(1)(f))"],
                [
                  "Anonymous usage counts, to see when Amber is used and which features help",
                  "Kind of page, feature used, referring website, screen size, language; the IP address and user agent every web request carries",
                  "Legitimate interest (Art. 6(1)(f))",
                ],
              ]}
            />
            <p>
              Your data is used only to provide the service you asked for: finding connections, explanations and document
              extraction for you.
            </p>
          </NoticeSection>

          <NoticeSection id="never" title="What we never do">
            <List
              items={[
                <>
                  <strong>We never sell</strong> your personal information.
                </>,
                <>
                  <strong>We never share it for advertising</strong>: no ad pixels, retargeting, data brokers or lookalike
                  audiences.
                </>,
                <>
                  <strong>No third-party trackers and no analytics cookies.</strong> Usage is only counted anonymously, on
                  the operator&apos;s own server.
                </>,
                <>
                  <strong>No training of AI models</strong> on your data, by us or by any vendor.
                </>,
                <>
                  <strong>No disclosure</strong> of your medical information to anyone, including patient groups or
                  researchers, without your explicit authorisation. Contributions are published only with your separate
                  consent and without your name.
                </>,
                <>
                  <strong>No diagnosis.</strong> Amber shows information and its sources; questions about diagnosis or trial
                  eligibility are marked as needing expert review.
                </>,
              ]}
            />
          </NoticeSection>

          <NoticeSection id="recipients" title="Who receives data">
            <NoticeTable
              caption="Recipients"
              head={["Recipient", "What it receives", "Why"]}
              rows={[
                [
                  "OpenAI",
                  "Only redacted text (personal details removed) from your chats and documents, and, with ChatGPT, your access token",
                  "Runs Dr. Wu and document extraction: on your own ChatGPT plan if you signed in with ChatGPT, otherwise on Amber's own OpenAI account. OpenAI acts as a service provider bound by contract to this purpose.",
                ],
                ["Google (only if you sign in with Google)", "Nothing from us; Google tells us your name, e-mail address and account ID at sign-in", "Sign-in only."],
                ["Public data sources (PubMed, ClinicalTrials.gov, and others)", "No user data", "The atlas is built from them; searches use public terms only."],
                [
                  "Our usage counter (Umami, on the operator's own server)",
                  "The usage counts above, with the IP address and user agent every web request carries",
                  <>
                    Anonymous usage counts (<ToBeCompleted>analytics server hosting provider and region</ToBeCompleted>).
                  </>,
                ],
                [
                  "Our own infrastructure",
                  "Everything else",
                  <>
                    The app, database and logs run on infrastructure operated by the team (
                    <ToBeCompleted>hosting provider and region</ToBeCompleted>).
                  </>,
                ]
              ]}
            />
            <NoticeSub title="International transfers">
              <p>
                OpenAI is based in the United States. Transfers rely on the EU–US Data Privacy Framework or Standard
                Contractual Clauses (<ToBeCompleted>mechanism per vendor</ToBeCompleted>). We use OpenAI&apos;s data-retention and
                residency options where our account supports them.
              </p>
            </NoticeSub>
          </NoticeSection>

          <NoticeSection id="retention" title="How long we keep it">
            <NoticeTable
              caption="Retention per category"
              head={["Data", "How long"]}
              rows={[
                ["Uploaded files", "Deleted as soon as the text is extracted (held in memory only)"],
                ["Findings, document details and extraction jobs", "Until you delete the document, withdraw consent to the use of your health information, or delete your account"],
                ["Profile", "Until you edit it, withdraw consent to the use of your health information, or delete your account"],
                ["Chats", "Until you delete the chat, withdraw consent to the use of your health information, or delete your account"],
                ["Contributions", "Until you remove them, withdraw contribute consent, or delete your account"],
                ["Consent records", "Until you delete your account (kept after withdrawal as proof of what you agreed to)"],
                ["Account and settings", "Until you delete your account"],
                ["Work details (doctors and researchers)", "Until you remove them, switch your role to patient, or delete your account"],
                ["ChatGPT access token", "Until you sign out or delete your account"],
                ["Google sign-in", "Only your Google account ID with the account data; no Google tokens are kept"],
                ["Logs and AI traces (no content, or redacted only)", "At most 30 days"],
                ["Backups", "Deleted data disappears within one backup cycle (at most 30 days)"],
                ["Guests", "Nothing is stored about you; visits only add to the usage counts"],
                ["Usage counts", <ToBeCompleted key="usage-retention">retention of usage counts on the analytics server</ToBeCompleted>],
              ]}
            />
          </NoticeSection>

          <NoticeSection id="rights" title="Your rights">
            <p>
              You can use most rights directly in the app. Signed-in requests are verified by your session; we never ask for
              identity documents.
            </p>
            <NoticeTable
              caption="Your rights and how to use them"
              head={["Right", "How"]}
              rows={[
                [
                  "Access and portability",
                  <>
                    <Link href="/profile#your-data" className={link}>
                      Download my data
                    </Link>{" "}
                    gives you everything as a JSON file.
                  </>,
                ],
                [
                  "Correction",
                  <>
                    Edit any item in your{" "}
                    <Link href="/profile#health-profile" className={link}>
                      profile
                    </Link>{" "}
                    and confirm or reject findings.
                  </>,
                ],
                [
                  "Deletion",
                  <>
                    <Link href="/profile#your-data" className={link}>
                      Delete my account
                    </Link>{" "}
                    removes everything, including your contributions.
                  </>,
                ],
                [
                  "Withdraw consent",
                  <>
                    One click per consent in{" "}
                    <Link href="/profile#consents" className={link}>
                      your profile
                    </Link>
                    . It stops the processing and deletes the data held under it.
                  </>,
                ],
                ["Object", "Researchers and doctors listed in the atlas can ask to claim, correct or remove their entry (see About this data)."],
                ["Restriction, or anything else", <>Write to <PrivacyEmail />.</>],
              ]}
            />
            <p>
              We answer within one month. You can also send requests by e-mail, or through an authorised agent. Using your
              rights never changes the service you get.
            </p>
          </NoticeSection>

          <NoticeSection id="california" title="California residents">
            <p>
              Under the CCPA as amended by the CPRA you have the right to know and access, delete and correct your personal
              information, to opt out of its sale or sharing, and to limit the use of sensitive personal information. You can
              use them as described under Your rights.
            </p>
            <List
              items={[
                <>
                  <strong>Categories collected:</strong> identifiers (name, e-mail, ChatGPT or Google account ID), account
                  login credentials (an encrypted ChatGPT access token), sensitive personal information about health and genetics that
                  you add, and internet activity (the anonymous usage counts). Purposes and retention are listed above.
                </>,
                <>
                  <strong>No sale or sharing:</strong> we do not sell personal information or share it for cross-context
                  behavioural advertising, and have not done so in the past 12 months. This includes data of anyone under 16.
                </>,
                <>
                  <strong>Global Privacy Control:</strong> we honour the GPC signal from your browser as an opt-out of sale and
                  sharing and record it on your account. Your profile shows whether it was received. The anonymous usage
                  counts on our own server are neither sale nor sharing, so the signal does not switch them off.
                </>,
                <>
                  <strong>Sensitive personal information</strong> is used only to provide the service you asked for, so the
                  right to limit its use is met by design.
                </>,
                <>
                  <strong>Response times:</strong> we confirm receipt within 10 business days and respond within 45 days (once
                  extendable by 45 days with notice).
                </>,
                <>
                  <strong>Non-discrimination:</strong> you get the same service whether or not you use any right.
                </>,
                <>
                  <strong>Medical information</strong> is not disclosed to anyone without your written authorisation.
                </>,
              ]}
            />
            <p>This notice is reviewed at least every 12 months.</p>
          </NoticeSection>

          <NoticeSection id="children" title="Children">
            <p>
              Accounts are for people aged 16 or older. Many people with rare diseases are children, so parents and legal
              guardians can use Amber on a child&apos;s behalf: when you upload, describe or contribute information about a
              child, you confirm that you hold parental responsibility. Data about children is handled with the same
              protections and is never sold or shared.
            </p>
          </NoticeSection>

          <NoticeSection id="ai" title="AI transparency">
            <List
              items={[
                "Dr. Wu is an AI system, and it is labelled as one wherever it appears. You always know when you are talking to an AI.",
                "AI-extracted findings are marked as such and used only after you confirm them.",
                "Amber makes no automated decisions with legal or similarly significant effects. It does not diagnose, decide trial eligibility or rank who receives care.",
                "Every claim in the atlas links to its source and shows a confidence level, and observed data is kept apart from inferred hypotheses.",
              ]}
            />
          </NoticeSection>

          <NoticeSection id="security" title="Security and incidents">
            <p>
              Data is encrypted in transit and at rest, every user table is protected so that one account can never read
              another&apos;s data, and personal details are removed before any AI processing.
            </p>
            <p>
              If a breach affects personal data, we notify the competent supervisory authority within 72 hours and affected
              users without undue delay when the risk is high. California residents are notified without unreasonable delay,
              and the California Attorney General when more than 500 residents are affected.
            </p>
          </NoticeSection>

          <NoticeSection id="contact" title="Contact and complaints">
            <p>
              Privacy questions and requests: <PrivacyEmail />. You also have the right to lodge a complaint with a data
              protection supervisory authority, in particular where you live or work (lead authority:{" "}
              <ToBeCompleted>supervisory authority</ToBeCompleted>).
            </p>
            <p className="rounded-lg border border-dashed p-3 text-sm">
              This notice describes how the software works. It is pending legal review:{" "}
              <ToBeCompleted>legal review</ToBeCompleted>.
            </p>
          </NoticeSection>
        </NoticeLayout>
      </div>
    </PageContainer>
  );
}

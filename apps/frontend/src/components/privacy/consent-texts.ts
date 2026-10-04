import type { ConsentType } from "@/lib/api/types";

/**
 * The just-in-time notices shown in the consent dialog (GDPR Art. 9(2)(a)
 * explicit consent, Art. 13 notice; CCPA notice at collection). The version
 * is stored with every grant (`POST /consents`), so bump it whenever the
 * wording below changes in substance.
 */
export const CONSENT_VERSION: Record<ConsentType, string> = {
  health_data: "health-data-2026-10-04",
  contribute: "contribute-2026-10-04",
  connect: "connect-signups-2026-10-04",
};

export type ConsentNotice = {
  /** One-sentence summary of what the user agrees to. */
  summary: string;
  /** "What we process" (categories of personal and sensitive information). */
  processed: string[];
  /** "Why" (purpose). */
  purpose: string;
  /** How the data is protected and handled. */
  safeguards: string[];
  /** Retention, per category. */
  retention: string[];
  /** How to withdraw, and what withdrawal deletes. */
  withdrawal: string;
  /** The explicit statement next to the (unticked) checkbox. */
  agreement: string;
  /** Button that grants the consent. */
  grantLabel: string;
};

export const CONSENT_NOTICES: Record<ConsentType, ConsentNotice> = {
  health_data: {
    summary:
      "To help you, Amber has to process health and genetic information: what you tell Dr. Wu, your profile and the documents you upload. We ask for your explicit consent once, for all three.",
    processed: [
      "What you type to Dr. Wu, the AI assistant, and its replies.",
      "Your private profile: the diseases, genes, variants, symptoms, age range, onset and country you confirm.",
      "Documents you upload (a genetic report, clinical letter, research paper or registry document) and the findings extracted from them.",
      "All of this is health and genetic information: sensitive personal information.",
    ],
    purpose:
      "Only to find connections in the atlas for you: similar conditions, patient communities, research and next steps. Never for advertising, profiling or training AI models.",
    safeguards: [
      "Names, birth dates, addresses and patient IDs are removed on our server before any AI model sees your text or documents.",
      "Original files are deleted right after the text is extracted. We never keep them.",
      "Only redacted text goes to OpenAI: on your own ChatGPT plan, or, if you signed in with Google, on Amber's own OpenAI account.",
      "Nothing is sold or shared. Nothing goes into the shared atlas unless you separately agree to contribute.",
    ],
    retention: [
      "Original files: deleted immediately after extraction.",
      "Chats, profile, documents' findings: kept until you delete them, withdraw this consent or delete your account.",
    ],
    withdrawal:
      "You can withdraw at any time in your profile with one click. Withdrawing deletes your profile, your chats with Dr. Wu, your documents with their findings and processing jobs. Your account, settings and contributions stay.",
    agreement:
      "I explicitly consent to Amber processing the health and genetic information I share in chats, my profile and uploaded documents, as described above.",
    grantLabel: "I agree, continue",
  },
  contribute: {
    summary:
      "Contributing adds information you choose to the shared atlas that everyone can see. We need your separate, explicit consent for that.",
    processed: [
      "Only what you submit in the contribution form: a disease, symptoms present or absent and an optional age range, or a resource such as a registry or natural history study.",
      "Health information in a symptom profile is sensitive personal information.",
      "It is stored with a link to your account so you can see and remove it, but it is shown in the atlas without your name or email.",
    ],
    purpose:
      "To help other families and researchers see patterns and find existing work. Contributions are labelled patient-reported, wait for review, and are never treated as cited evidence.",
    safeguards: [
      "Never include names, birth dates, addresses, patient IDs or anything else that identifies a person.",
      "Nothing is sold or shared for advertising. No medical information is disclosed to patient groups or researchers beyond the contribution you choose to publish.",
      "Your private profile stays private. Contributing does not publish it.",
    ],
    retention: [
      "Contributions: kept until you remove them, withdraw this consent or delete your account.",
    ],
    withdrawal:
      "You can withdraw at any time in your profile with one click. Withdrawing removes all your contributions from the shared atlas.",
    agreement:
      "I explicitly consent to Amber publishing the contributions I submit in the shared atlas, labelled as patient-reported, as described above.",
    grantLabel: "I agree, continue",
  },
  connect: {
    summary:
      "Studies, surveys and contacts: Amber lets you write to verified doctors and researchers who accept messages. This is a separate purpose, so we ask for your separate consent.",
    processed: [
      "The messages you write and receive, and the display name you choose for a conversation.",
      "Your age group (18 or older, or 16 or 17) and, if you are 16 or 17, that a parent or guardian agrees (self-declared, not checked).",
    ],
    purpose:
      "Only to let you contact the person you choose. Messages are not a medical consultation or a medical record.",
    safeguards: [
      "Messages are stored encrypted and shown only to you and the person you write to.",
      "No AI model reads them. The Amber team reads a conversation only when you report it, and every such access is logged.",
      "Your e-mail, account name and profile are never shown to the other person.",
    ],
    retention: [
      "Messages: until you delete them, withdraw this consent or delete your account; conversations inactive for 12 months are deleted.",
    ],
    withdrawal:
      "You can withdraw at any time in your profile with one click. Withdrawing deletes your messages and closes your conversations.",
    agreement:
      "I consent to Amber processing my messages and age group so I can contact doctors and researchers, as described above.",
    grantLabel: "I agree, continue",
  },
};

/** What withdrawing deletes, for the profile's consent section. */
export const WITHDRAWAL_EFFECT: Record<ConsentType, string> = {
  health_data:
    "Withdrawing deletes your profile, your chats with Dr. Wu, and your documents with their findings and processing jobs. Your account, settings and contributions stay.",
  contribute: "Withdrawing removes all your contributions from the shared atlas.",
  connect: "Withdrawing deletes your messages and closes your conversations.",
};

export const CONSENT_LABELS: Record<ConsentType, { title: string; description: string }> = {
  health_data: {
    title: "Use of your health information",
    description: "Lets Amber process what you tell Dr. Wu, your profile and the documents you upload, to find connections for you.",
  },
  contribute: {
    title: "Contribute to the shared atlas",
    description: "Lets you publish patient-reported symptom profiles and resources in the atlas.",
  },
  connect: {
    title: "Studies, surveys and contacts",
    description: "Lets you write to verified doctors and researchers who accept messages.",
  },
};
